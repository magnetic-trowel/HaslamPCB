# SPDX-FileCopyrightText: 2026 kicad-auto-everything contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which MCU pins can be ADC inputs, for parts whose symbols name the pin only by its GPIO.

A board stores each pad's pin function (the symbol's pin name, or the alternate the designer
chose), not the pin's other functions. KiCad's RP2040 and nRF52 symbols name ADC pins
'GPIO26/ADC0' and 'AIN0/P0.02', and kae.circuit.roles reads that '/' alternate. KiCad's ESP32,
ATmega and most module symbols say only 'IO35', 'GPIO4' or 'PC0' (checked against KiCad 10.0.7's
RF_Module, MCU_Espressif and MCU_Microchip_ATmega libraries: no ADC alternates there), so a
net such as ADC_BAT on an ESP32 IO35 has no pin-level fact behind its name.

This table is that fact, from the vendors' datasheets (pin numbers are facts, not library
content). It is evidence for an analog role, never a role by itself: most ADC-capable pins
carry digital signals (ESP32 IO32/IO33 are often I2C), so roles weighs it WEAK, beside the name
and the RC-filter topology.

    adc_channel(part_text, pin_fn) -> (channel, source) | None
"""
from __future__ import annotations

import re

_ESP32 = ('ESP-IDF GPIO summary, ESP32 (ADC1_CH0-7: GPIO36-39, 32-35; ADC2_CH0-9: GPIO4, 0, 2, 15, 13, 12, 14, 27, 25, 26) '
          'https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/gpio.html')
_ESP32_S2 = ('ESP-IDF GPIO summary, ESP32-S2 (ADC1_CH0-9: GPIO1-10, ADC2_CH0-9: GPIO11-20) '
             'https://docs.espressif.com/projects/esp-idf/en/stable/esp32s2/api-reference/peripherals/gpio.html')
_ESP32_S3 = ('ESP-IDF GPIO summary, ESP32-S3 (ADC1_CH0-9: GPIO1-10, ADC2_CH0-9: GPIO11-20) '
             'https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/peripherals/gpio.html')
_ESP32_C3 = ('ESP-IDF GPIO summary, ESP32-C3 (ADC1_CH0-4: GPIO0-4, ADC2_CH0: GPIO5) '
             'https://docs.espressif.com/projects/esp-idf/en/stable/esp32c3/api-reference/peripherals/gpio.html')
_ESP32_C6 = ('ESP-IDF GPIO summary, ESP32-C6 (ADC1_CH0-6: GPIO0-6) '
             'https://docs.espressif.com/projects/esp-idf/en/stable/esp32c6/api-reference/peripherals/gpio.html')
_ESP32_H2 = ('ESP-IDF GPIO summary, ESP32-H2 (ADC1_CH0-4: GPIO1-5) '
             'https://docs.espressif.com/projects/esp-idf/en/stable/esp32h2/api-reference/peripherals/gpio.html')
_M328 = 'Microchip ATmega328P datasheet (DS40002061), section 1 "Pin Configurations": PC0-PC5 are ADC0-ADC5'
_M32U4 = 'Microchip ATmega16U4/32U4 datasheet (Atmel-7766), section 1.1 "Pin Configurations": ADC0-1, ADC4-13'
_M2560 = 'Microchip ATmega640/1280/2560 datasheet (DS40002211), "Pin Configurations": PF0-7 ADC0-7, PK0-7 ADC8-15'
_TINY85 = 'Microchip ATtiny25/45/85 datasheet (DS40002066), "Pin Configurations": PB5 ADC0, PB2 ADC1, PB4 ADC2, PB3 ADC3'
_STM32 = ('STM32 datasheets, "Pin definitions" tables (assumed common set: PA0-PA7, PB0-PB1, PC0-PC5 carry ADC inputs on '
          'the F0/F1/F2/F4/F7/G0/G4/L0/L1/L4 lines; the part datasheet is authoritative)')

# ESP32 (classic) GPIO -> channel; chip and module pin names that are not GPIOn
_ESP32_ADC = {**{g: f"ADC1_CH{c}" for g, c in ((36, 0), (37, 1), (38, 2), (39, 3), (32, 4), (33, 5), (34, 6), (35, 7))},
              **{g: f"ADC2_CH{c}" for g, c in ((4, 0), (0, 1), (2, 2), (15, 3), (13, 4), (12, 5), (14, 6), (27, 7), (25, 8), (26, 9))}}
_ESP32_ALIAS = {'SENSOR_VP': 36, 'SENSOR_CAPP': 37, 'SENSOR_CAPN': 38, 'SENSOR_VN': 39, 'VP': 36, 'VN': 39,
                '32K_XP': 32, '32K_XN': 33, 'XTAL_32K_P': 32, 'XTAL_32K_N': 33, 'VDET_1': 34, 'VDET_2': 35}

# (part-text regex, {pin-name regex -> channel function}, source), the first family match wins
_FAMILIES = [
    (re.compile(r'ESP32-?S3', re.I), 'gpio', lambda g: f"ADC1_CH{g - 1}" if 1 <= g <= 10 else f"ADC2_CH{g - 11}" if 11 <= g <= 20 else None,
     _ESP32_S3),
    (re.compile(r'ESP32-?S2', re.I), 'gpio', lambda g: f"ADC1_CH{g - 1}" if 1 <= g <= 10 else f"ADC2_CH{g - 11}" if 11 <= g <= 20 else None,
     _ESP32_S2),
    (re.compile(r'ESP32-?C3|ESP8685', re.I), 'gpio', lambda g: f"ADC1_CH{g}" if 0 <= g <= 4 else 'ADC2_CH0' if g == 5 else None, _ESP32_C3),
    (re.compile(r'ESP32-?C6', re.I), 'gpio', lambda g: f"ADC1_CH{g}" if 0 <= g <= 6 else None, _ESP32_C6),
    (re.compile(r'ESP32-?H2', re.I), 'gpio', lambda g: f"ADC1_CH{g - 1}" if 1 <= g <= 5 else None, _ESP32_H2),
    # classic ESP32 last among the ESP32s: 'ESP32-WROOM-32', 'ESP32-D0WD', 'ESP32-PICO', 'ESP32-WROVER'
    (re.compile(r'ESP32(?!-?[SCHP]\d)', re.I), 'gpio', _ESP32_ADC.get, _ESP32),
    (re.compile(r'ATMEGA(48|88|168|328)', re.I), 'port', {('C', i): f"ADC{i}" for i in range(6)}.get, _M328),
    (re.compile(r'ATMEGA(16|32)U4', re.I), 'port', {('F', 0): 'ADC0', ('F', 1): 'ADC1', ('F', 4): 'ADC4', ('F', 5): 'ADC5', ('F', 6): 'ADC6',
                                                    ('F', 7): 'ADC7', ('D', 4): 'ADC8', ('D', 6): 'ADC9', ('D', 7): 'ADC10',
                                                    ('B', 4): 'ADC11', ('B', 5): 'ADC12', ('B', 6): 'ADC13'}.get, _M32U4),
    (re.compile(r'ATMEGA(640|1280|1281|2560|2561)', re.I), 'port',
     {**{('F', i): f"ADC{i}" for i in range(8)}, **{('K', i): f"ADC{8 + i}" for i in range(8)}}.get, _M2560),
    (re.compile(r'ATTINY(25|45|85)', re.I), 'port', {('B', 5): 'ADC0', ('B', 2): 'ADC1', ('B', 4): 'ADC2', ('B', 3): 'ADC3'}.get, _TINY85),
    (re.compile(r'STM32', re.I), 'port', {**{('A', i): f"ADC_IN (PA{i})" for i in range(8)}, ('B', 0): 'ADC_IN (PB0)',
                                          ('B', 1): 'ADC_IN (PB1)', **{('C', i): f"ADC_IN (PC{i})" for i in range(6)}}.get, _STM32),
]
_PORT = re.compile(r'^P([A-K])(\d{1,2})(?:$|[/_ (])')


def _gpio_number(fn: str) -> int | None:
    f = fn.upper()
    for alias, g in _ESP32_ALIAS.items():
        if f == alias or f.startswith(alias + '/'):
            return g
    m = re.match(r'^(?:GPIO|IO)(\d{1,2})(?:$|[/_ (])', f)
    return int(m.group(1)) if m else None


def adc_channel(part_text: str, pin_fn: str) -> tuple[str, str] | None:
    """(ADC channel, datasheet source) when pin `pin_fn` (upper case, as kae.circuit's Pin.fn) of the part
    described by `part_text` (Part.text(): value, lib id, part-number fields) can be an ADC input, else None.
    A pin that names an ADC itself ('ADC6', 'GPIO26/ADC0') is read by roles' pin patterns, not here."""
    if not pin_fn:
        return None
    for rx_, kind, get, src in _FAMILIES:
        if not rx_.search(part_text or ''):
            continue
        if kind == 'gpio':
            g = _gpio_number(pin_fn)
            ch = get(g) if g is not None else None
        else:
            m = _PORT.match(pin_fn.upper())
            ch = get((m.group(1), int(m.group(2)))) if m else None
        return (ch, src) if ch else None
    return None
