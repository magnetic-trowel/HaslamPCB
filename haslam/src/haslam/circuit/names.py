# SPDX-FileCopyrightText: 2026 HaslamPCB contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Supply and ground names: the name rules that placement, physics and routing share when a
board's brief is not at hand (a brief's net roles, haslam.circuit.roles, come first wherever there
is one). One copy, so the stages agree on which nets are grounds and rails.

    GND_RE      a ground net's name (GND, AGND, PGND, VSS, 0V, GROUND, EARTH)
    PWR_RE      a supply rail's name (+3V3, 3V3, VCC_x, VDD..., AVDD, 12V0)
    SUPPLY_PIN  a part's supply pin function (VCC, VDD..., AVDD, PVIN, VIN, V+)
"""
import re

GND_RE = re.compile(r'(^|[^A-Z])(A|D|P|S|C)?GND|^/?VSS|^0V$|GROUND|EARTH', re.I)
PWR_RE = re.compile(r'^/?(\+?\d+(\.\d+)?V\d*|\+[A-Z0-9_.]+|V(CC|DD|BUS|IN|SYS|BAT|MOT|M|PP|REG|CORE|CAP|S)[A-Z0-9_.]*|'
                    r'[AD]V(DD|CC)[A-Z0-9_]*|\d+V\d+|[0-9]+V[0-9]*_?[A-Z]*)$', re.I)
SUPPLY_PIN = re.compile(r"^(V(CC|DD|IN|BAT|BUS|S|M|PP|IO|CORE|DDA|DDIO|USB|SYS|P|\+)\w*|AVDD|DVDD|IOVDD|PVDD|PVIN|"
                        r"AVCC|DVCC|VIN\d*|PWR|POWER|\+V\w*|V\+|VREG_IN|IN)$", re.I)
