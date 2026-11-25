# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""'Is this net fast?' as a computation (haslam.circuit.edges): driver rise time against route delay."""
from circuit_fixtures import C, IC, R, board, fp
from shapely.geometry import box

from haslam.board.model import Track
from haslam.circuit import edges as E
from haslam.circuit.brief import build
from haslam.circuit.netlist import Netlist
from haslam.circuit.roles import infer_roles


def _parts():
    fpga = IC('U1', 'ICE40UP5K-SG48', 'Package_DFN_QFN:QFN-48-1EP_7x7mm_P0.5mm',
              [('1', 'IOB_3', 'LED_DATA', 'bidirectional'), ('2', 'IOB_4', 'SPI_CLK', 'bidirectional'),
               ('5', 'VCCIO', '+3V3', 'power_in'), ('49', 'GND', 'GND', 'power_in')])
    hc = IC('U2', '74HC595', 'Package_SO:SOIC-16_3.9x9.9mm_P1.27mm',
            [('14', 'SER', 'LED_DATA', 'input'), ('11', 'SRCLK', 'SPI_CLK', 'input'), ('9', 'QH\'', 'SLOW_OUT', 'output'),
             ('16', 'VCC', '+3V3', 'power_in'), ('8', 'GND', 'GND', 'power_in')])
    sens = IC('U3', 'XYZ123', 'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm',
              [('1', 'OUT', 'MYSTERY', 'output'), ('2', 'VDD', '+3V3', 'power_in'), ('3', 'GND', 'GND', 'power_in')])
    j = fp('J1', 'Conn', 'Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical',
           [('1', 'SLOW_OUT', '', ''), ('2', 'MYSTERY', '', ''), ('3', 'GND', '', '')])
    return [fpga, hc, sens, j, C('C1', '100nF', '+3V3', 'GND'), C('C2', '10uF', '+3V3', 'GND', lib='Capacitor_SMD:C_0805_2012Metric')]


def _roles(size_mm=None):
    b = board(_parts())
    if size_mm:
        b.outline = [box(0, 0, size_mm, size_mm)]
    nl = Netlist.from_board(b)
    return nl, infer_roles(nl)


def test_propagation_delay_and_critical_lengths():
    # FR-4 er 4.5: stripline sqrt(4.5)/c = 7.08 ps/mm; microstrip sqrt(0.475*4.5 + 0.67)/c = 5.59 ps/mm
    assert abs(E.t_pd_ps_mm(4.5, False) - 7.076) < 0.01
    assert abs(E.t_pd_ps_mm(4.5, True) - 5.592) < 0.01
    rev, term = E.critical_mm(1.0, 7.076)
    assert abs(rev - 23.55) < 0.05 and abs(term - 70.66) < 0.05


def test_driver_edges_come_from_families_and_are_marked_assumed():
    nl, r = _roles()
    e = E.driver_edge(nl, r, 'LED_DATA')
    assert e.family == 'fpga' and e.ref == 'U1' and e.assumed and e.source
    slow = E.driver_edge(nl, r, 'SLOW_OUT')
    assert slow.family == '74HC' and slow.t_r_ns > e.t_r_ns
    assert E.driver_edge(nl, r, 'MYSTERY') is None          # a part no family row covers has no t_r
    assert r.nets['MYSTERY'].attrs['edge']['t_r_ns'] is None


def test_a_fast_edge_makes_a_plain_net_high_speed_only_where_the_board_is_long_enough():
    _, small = _roles(10.0)            # 20 mm of w + h: no route can reach t_r/2 of a fast FPGA edge
    assert small.nets['LED_DATA'].role == 'signal'
    _, big = _roles(150.0)
    nr = big.nets['LED_DATA']
    assert nr.role == 'high_speed' and nr.subrole == 'fast_edge', nr
    assert nr.attrs['edge']['can_ring'] and any('t_r' in e.fact for e in nr.evidence)
    assert big.nets['SLOW_OUT'].role == 'signal'           # a 74HC edge needs a far longer route than 300 mm
    _, none = _roles()
    assert 'can_ring' not in none.nets['LED_DATA'].attrs['edge']   # no outline: lengths stated, no promotion


def test_interfaces_with_their_own_termination_rules_are_not_judged_here():
    mcu = IC('U1', 'STM32F405RGT6', 'Package_QFP:LQFP-64_10x10mm_P0.5mm',
             [('44', 'PA11', 'USB_DM', 'bidirectional'), ('45', 'PA12', 'USB_DP', 'bidirectional'),
              ('1', 'VDD', '+3V3', 'power_in'), ('2', 'VSS', 'GND', 'power_in')])
    usb = fp('J1', 'USB_B_Micro', 'Connector_USB:USB_Micro-B_Molex-105017-0001',
             [('2', 'USB_DM', 'D-', 'bidirectional'), ('3', 'USB_DP', 'D+', 'bidirectional'), ('5', 'GND', 'GND', 'power_in')])
    nl = Netlist.from_board(board([mcu, usb, C('C1', '100nF', '+3V3', 'GND')]))
    r = infer_roles(nl)
    assert 'interface' in r.nets['USB_DP'].attrs['edge']['judged_by']


def test_long_routes_raise_ringing_hazards_and_short_ones_do_not():
    b = board(_parts())
    b.outline = [box(0, 0, 200.0, 200.0)]
    for f in b.footprints:
        for p in f.pads:
            p.layers = ['F.Cu']
            p.x, p.y = {'U1': (10.0, 10.0), 'U2': (150.0, 10.0)}.get(f.ref, (5.0, 5.0))
    brief = build(b)
    hz = E.long_net_hazards(brief, b)
    codes = {(h['code'], h['objects'][0]) for h in hz}
    assert ('edge_ringing_risk', 'LED_DATA') in codes      # 140 mm unrouted estimate on stripline-free 2 layers
    h = next(h for h in hz if h['objects'][0] == 'LED_DATA')
    assert h['evidence']['length'].startswith('estimated') and 'U1' in h['objects']
    # routed short: a 10 mm track between the pads of a moved receiver
    for f in b.footprints:
        if f.ref == 'U2':
            for p in f.pads:
                p.x, p.y = 20.0, 10.0
    b.tracks = [Track(uuid='t1', net='LED_DATA', layer='F.Cu', width=0.2, start=(10.0, 10.0), end=(20.0, 10.0))]
    hz = E.long_net_hazards(brief, b)
    assert not any(h['objects'][0] == 'LED_DATA' for h in hz), hz


def test_board_hazards_finish_reports_edges_without_a_brief():
    from haslam.board_hazards import edge_hazards
    b = board(_parts())
    b.outline = [box(0, 0, 200.0, 200.0)]
    for f in b.footprints:
        for p in f.pads:
            p.layers = ['F.Cu']
            p.x, p.y = {'U1': (10.0, 10.0), 'U2': (150.0, 10.0)}.get(f.ref, (5.0, 5.0))
    assert any(h['code'] == 'edge_ringing_risk' for h in edge_hazards(b))


def test_fast_edge_weight_is_a_setting():
    from haslam.route.constraints import setting
    assert setting('fast_edge_weight') == 1.5
    assert setting('fast_edge_weight', opts={'fast_edge_weight': 1}) == 1.0


def test_mcu_pins_take_their_reset_default_edge_and_say_so():
    """The netlist cannot tell what slew firmware sets: an STM32 pin is OSPEEDR=00 at reset (DS8626: 100 ns at 50 pF),
    an nRF52 pin standard drive (8 ns at 15 pF), an ESP32 or RP2040 pin an assumed 10 ns; the edge entry and the
    hazard fix say a pin set fast needs review."""
    parts = [IC('U1', 'STM32F103C8T6', 'Package_QFP:LQFP-48_7x7mm_P0.5mm', [('10', 'PA0', 'LONG_A', 'bidirectional'),
                                                                          ('1', 'VDD', '+3V3', 'power_in'), ('2', 'VSS', 'GND', 'power_in')]),
             IC('U2', 'nRF52840', 'Package_DFN_QFN:QFN-73', [('5', 'P0.05', 'LONG_B', 'bidirectional'),
                                                             ('1', 'VDD', '+3V3', 'power_in'), ('2', 'VSS', 'GND', 'power_in')]),
             fp('U3', 'ESP32-WROOM-32', 'RF_Module:ESP32-WROOM-32', [('8', 'LONG_C', 'IO32', 'bidirectional'),
                                                                    ('2', '+3V3', '3V3', 'power_in'), ('1', 'GND', 'GND', 'power_in')]),
             fp('J1', 'Conn', 'Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical',
                [('1', 'LONG_A', '', ''), ('2', 'LONG_B', '', ''), ('3', 'LONG_C', '', ''), ('4', 'GND', '', '')]),
             C('C1', '100nF', '+3V3', 'GND')]
    b = board(parts)
    b.outline = [box(0, 0, 300.0, 300.0)]
    nl = Netlist.from_board(b)
    r = infer_roles(nl)
    got = {n: r.nets[n].attrs['edge'] for n in ('LONG_A', 'LONG_B', 'LONG_C')}
    assert [got[n]['t_r_ns'] for n in ('LONG_A', 'LONG_B', 'LONG_C')] == [100.0, 8.0, 10.0], got
    assert all('reset-default' in got[n]['slew'] for n in got)
    assert all(r.nets[n].subrole != 'fast_edge' for n in got)     # slow defaults: no promotion even at 600 mm
    for f in b.footprints:
        for p in f.pads:
            p.layers = ['F.Cu']
            p.x, p.y = (290.0, 290.0) if f.ref == 'J1' else (5.0, 5.0)
    hz = [h for h in E.long_net_hazards(build(b), b) if h['objects'][0] == 'LONG_B']
    assert hz and 'reset-default' in hz[0]['fix'], hz
