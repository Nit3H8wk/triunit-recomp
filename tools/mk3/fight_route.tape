# MK3 2.1 J3 route reset -> round start (tools/mk3/replay.py format: "cycle port value"; port 0 IN0, 1 IN1, 2 DSW, 3 IN2; active low)
# from the first TMS boundary >= cycle the port reads value. CMOS seed, default DIPs (CMOS coinage: 2 coins = 1 credit).
125000000 3 65534
125625000 3 65535
131250000 3 65534
131875000 3 65535
143750000 3 65531
144375000 3 65535
187500000 0 65519
188125000 0 65535
