"""MK3 2.1 Original: main-CPU PCs and TMS34010 I/O after the first DCS wait, up to the third frame after the first DMA trigger (data).

Method (python -B tools/mk3/post_sound_pcs.py --check re-measures and compares everything below):
tools/mk3/reference_video.py runs the pinned MAME 0.280 debugger from reset with the factory CMOS seed, default
DIPs and no inputs for 4 emulated seconds. A loop-compressed instruction trace starts at 0xffaa8990 (cycle
545,036) and is split at the frontiers by the start cycle of each traced instruction; only the distinct PCs of
each segment are kept. Loop compression skips a PC only after it was traced twice, so the union is complete; a
PC that is still in the 64-entry loop history when a frontier is crossed can be missing from the later segment.
Frontiers come from the handler-entry breakpoints (pushed PC/ST read from the stack) and from a registerpoint
on ST.IE. Cycles are instruction-start totalcycles (160 ns each).

Interrupts stay disabled from reset to the EINT at 0xff815070. DI has been pending since the DPYINT line of the
first enabled frame, and INTENB already holds DI, so that EINT accepts the display interrupt inside itself
(check_interrupt from EINT, 34010ops.hxx:605-609): the first enable and the first acceptance are one instruction.
"""
FRONTIERS=dict(
    trace_start=dict(pc=0xffaa8990,cycle=545036),
    # EINT: 3 cycles; the acceptance adds 16 (tms34010.cpp:700-704), pushes PC then ST and loads ST=0x10.
    first_enable=dict(pc=0xff815070,cycle=19650544,instruction='EINT'),
    first_interrupt=dict(vector=0xfffffea0,source='DI',handler=0xff81a7c0,handler_entry_cycle=19650563,
                         pushed_pc=0xff815080,pushed_status=0x40200030,status_after=0x10,sp_after=0x010fffb0),
    # First boundary at which ST.IE is observed set: inside the DI handler (which re-enables interrupts).
    first_boundary_with_ie=dict(pc=0xff81a8a0,cycle=19650659,status=0x20200030),
    # First acceptance at a timeslice start, right after the DPYINT line timer (frame 173, T = 173 x 18,279,250 ns).
    first_timer_interrupt=dict(vector=0xfffffea0,source='DI',boundary_cycle=19764439,handler_entry_cycle=19764455,
                               last_instruction=dict(pc=0xff928140,cycle=19764437),pushed_pc=0xff928130,pushed_status=0x00200030),
    # First DMA trigger, inside the TRAP 1 handler: MOVE -*B14,-*B10,1 at 0xff804640 (segment 4) writes LRSKIP 0 and
    # DMA_COMMAND 0xc002 (mirror 0x01a80010). A watchpoint's pc is past the opcode already fetched: 0xff804650.
    first_dma=dict(pc=0xff804640,cycle=20795274,command=0xc002,watchpoint_pc=0xff804650),
    # Third DI handler entry after the first DMA: end of segment 4.
    frame3_after_dma=dict(handler=0xff81a7c0,handler_entry_cycle=21135398,pushed_pc=0xff805d20,pushed_status=0x20200030))
HANDLERS={'NMI':0xff81bb20,'HI':0xff81bb20,'DI':0xff81a7c0,'WV':0xff81bb20,'INT1':0xff8045d0,'INT2':0xff81bb00}  # vector targets in the program image
# Segment 0: 0xffaa8990 (cycle 545,036) up to the EINT, interrupts disabled. 765 distinct PCs
# (136 already in tools/mk3/generate.py slices); 1744 traced lines, 9375018 loop-skipped instructions.
WAIT_TO_EINT_PCS=tuple(int(x,16) for x in '''
ff806020 ff806040 ff806050 ff806060 ff806090 ff8060c0 ff8060f0 ff806100 ff806130 ff806160 ff806190 ff8061c0 ff8061f0
ff806220 ff806240 ff806270 ff8062a0 ff8062d0 ff806300 ff806330 ff806360 ff806390 ff8063b0 ff8063c0 ff8063d0 ff806400
ff806410 ff806440 ff806470 ff8064a0 ff8064c0 ff8064f0 ff806510 ff806530 ff806550 ff806580 ff8065b0 ff8065e0 ff806610
ff806640 ff806670 ff8066a0 ff8066d0 ff806700 ff806710 ff806730 ff806740 ff806750 ff806760 ff806780 ff806790 ff8067b0
ff8067e0 ff806810 ff806840 ff806850 ff806860 ff814de0 ff814e00 ff814e10 ff814e40 ff814e60 ff814e70 ff814ea0 ff814eb0
ff814ee0 ff814f00 ff814f30 ff814f60 ff814fb0 ff814fc0 ff814ff0 ff815010 ff815040 ff8194a0 ff8194b0 ff8194e0 ff819500
ff819520 ff819550 ff819560 ff819590 ff8195c0 ff8195f0 ff819620 ff819650 ff819680 ff8196b0 ff8196e0 ff819700 ff819730
ff819760 ff819790 ff8197c0 ff8197e0 ff819810 ff819840 ff819860 ff819890 ff8198c0 ff8198e0 ff8198f0 ff819910 ff819940
ff819950 ff819970 ff8199a0 ff8199b0 ff8199c0 ff8199d0 ff8199e0 ff8199f0 ff819a00 ff819a10 ff819a40 ff819a60 ff819a90
ff819ac0 ff819af0 ff819b00 ff819b30 ff819b60 ff819b90 ff819bb0 ff819be0 ff819ee0 ff819ef0 ff819f20 ff819f30 ff819f60
ff819f80 ff819fb0 ff819fc0 ff819fd0 ff81a000 ff81a020 ff81a050 ff81a060 ff81a080 ff81a0b0 ff81a0e0 ff81a110 ff81a120
ff81a130 ff81a150 ff90bbf0 ff90bc00 ff90bc30 ff90bc60 ff90bc90 ff90bcc0 ff90bcf0 ff90bd20 ff90bd50 ff90bd80 ff90bdb0
ff9237d0 ff9237f0 ff923820 ff923830 ff923860 ff923890 ff9238c0 ff9238f0 ff923920 ff923950 ff923980 ff9239b0 ff9239c0
ff9239f0 ff923a00 ff923a30 ff923a60 ff923a70 ff923aa0 ff923ab0 ff923ac0 ff923af0 ff923b20 ff923b40 ff925280 ff9252b0
ff9252e0 ff925310 ff925320 ff925330 ff925360 ff925370 ff925380 ff925390 ff9253c0 ff925400 ff925430 ff925450 ff925950
ff925970 ff925990 ff9259c0 ff9259e0 ff9259f0 ff925a00 ff925a10 ff925a40 ff925a60 ff925a70 ff925a80 ff925aa0 ff925c00
ff925c20 ff925c40 ff925c70 ff925c80 ff925c90 ff925ca0 ff925cc0 ff925cd0 ff925d00 ff925d20 ff925d40 ff925d50 ff925d70
ff926040 ff926060 ff926080 ff926090 ff9260b0 ff9260c0 ff9260d0 ff9260e0 ff926100 ff926120 ff926130 ff926140 ff926160
ff926170 ff926180 ff926190 ff9261a0 ff9261c0 ff9261d0 ff9261f0 ff926210 ff926be0 ff926c00 ff926c20 ff926c30 ff926c60
ff926c90 ff926cc0 ff926cd0 ff926cf0 ff926d00 ff926d10 ff926d20 ff926d50 ff926d70 ff927d40 ff927d50 ff927d80 ff927d90
ff927db0 ff927dc0 ff927dd0 ff927df0 ff927e00 ff927e30 ff927e50 ff927e80 ff927e90 ff927ea0 ff927ec0 ff927ed0 ff927ee0
ff927f00 ff927f20 ff927f40 ff927f50 ff927f60 ff927f70 ff927fa0 ff927fd0 ff927ff0 ff95f550 ff95f580 ff95f5b0 ff95f5e0
ff95f610 ff95f640 ff95f670 ff95f6a0 ff95f6d0 ff95f700 ff961490 ff9614a0 ff9614b0 ff9614c0 ff9614d0 ff9614e0 ff9614f0
ff961500 ff961510 ff961520 ff961530 ff961540 ffaa87c0 ffaa87e0 ffaa8810 ffaa8820 ffaa8830 ffaa8840 ffaa8850 ffaa8870
ffaa8880 ffaa88b0 ffaa88c0 ffaa88d0 ffaa88f0 ffaa8920 ffaa8940 ffaa8960 ffaa8990 ffaa89c0 ffaa89d0 ffaa89f0 ffaa8a00
ffaa8a20 ffaa8a40 ffaa8a70 ffaa8a90 ffaa8aa0 ffaa8ac0 ffaa8af0 ffaa8b10 ffadb070 ffadb090 ffadb0a0 ffadb0c0 ffadb0d0
ffadb0f0 ffadb110 ffadb140 ffadb160 ffadb170 ffadb1a0 ffadb1b0 ffadb1c0 ffadb1d0 ffadb200 ffadb230 ffadb260 ffadb270
ffadb290 ffadb380 ffadb3a0 ffadb3b0 ffadb3d0 ffadb3f0 ffadb460 ffadb480 ffadb4b0 ffadb4d0 ffadb4e0 ffadb500 ffadb640
ffadb660 ffadb680 ffadb690 ffadb6c0 ffadb6d0 ffadb6f0 ffadb710 ffadb740 ffadb770 ffadb790 ffadb7c0 ffadb7d0 ffadb800
ffadb810 ffadb820 ffadb840 ffadb850 ffadb860 ffadb880 ffadb8a0 ffadb8b0 ffadb8d0 ffadb8f0 ffadb920 ffadb940 ffadb950
ffadb960 ffadb980 ffadb9a0 ffadb9d0 ffadb9f0 ffadba00 ffadc230 ffadc240 ffadc250 ffadc280 ffadc2e0 ffadc300 ffadc320
ffadc330 ffadc340 ffadc360 ffadc380 ffadc390 ffadc3c0 ffadc3d0 ffadc3f0 ffadc420 ffadc430 ffadc450 ffadc460 ffadc480
ffadc4a0 ffadc4b0 ffadc4c0 ffadc4e0 ffadc500 ffadc510 ffadc540 ffadc550 ffadc570 ffadc5a0 ffadc5b0 ffadc5d0 ffae22f0
ffae2310 ffae2330 ffae2350 ffae2380 ffae23b0 ffae23e0 ffae2400 ffae2700 ffae2720 ffae2740 ffae2770 ffae2790 ffae27a0
ffae27d0 ffae27e0 ffae27f0 ffae2800 ffae2830 ffae2860 ffae2890 ffae28a0 ffae28c0 ffae29b0 ffae29d0 ffae29f0 ffae2ac0
ffae2ae0 ffae2af0 ffae2b10 ffae2b30 ffae2b60 ffae2b80 ffae84a0 ffae84c0 ffae84e0 ffae84f0 ffae8500 ffae8530 ffae8540
ffae8550 ffae8560 ffae8570 ffae8580 ffae8590 ffae85a0 ffae85d0 ffae85e0 ffae85f0 ffae8600 ffae8610 ffae8620 ffae8630
ffae8640 ffae8650 ffae8660 ffae8670 ffae8680 ffae8690 ffae86a0 ffae86b0 ffae86c0 ffae8730 ffae8740 ffae8750 ffae8760
ffae8770 ffae8780 ffae8790 ffae87a0 ffae87b0 ffae87c0 ffae87d0 ffae87e0 ffae87f0 ffae8800 ffae8830 ffae8840 ffae8850
ffae8860 ffae8870 ffae8880 ffae8890 ffae88a0 ffae88b0 ffae88c0 ffae88d0 ffae88e0 ffae88f0 ffae8900 ffae8910 ffae8920
ffae8940 ffae8950 ffae8960 ffae9930 ffae9960 ffae9990 ffae99c0 ffae99d0 ffae99e0 ffae9a10 ffae9a30 ffae9a60 ffae9a90
ffae9ac0 ffae9af0 ffae9b00 ffae9b10 ffae9c40 ffae9c70 ffae9ca0 ffae9cb0 ffae9ce0 ffae9d00 ffae9d10 ffae9d40 ffae9d60
ffae9d70 ffae9da0 ffae9de0 ffae9e10 ffae9e40 ffae9e70 ffae9e80 ffae9eb0 ffae9ee0 ffae9f10 ffae9f40 ffae9f50 ffae9f80
ffae9f90 ffae9fb0 ffae9fe0 ffae9ff0 ffaea020 ffaea050 ffaea060 ffaea090 ffaea0a0 ffaea0c0 ffaea0f0 ffaea100 ffaea130
ffaea160 ffaea190 ffaea1c0 ffaea1f0 ffaea220 ffaea230 ffaea260 ffaea270 ffaea290 ffaea2c0 ffaea2d0 ffaea300 ffaea880
ffaea8b0 ffaea8e0 ffaea8f0 ffaea920 ffaea930 ffaea950 ffaea980 ffaea990 ffaea9c0 ffaea9e0 ffaeaa10 ffaeab60 ffaeab90
ffaeabc0 ffaeabd0 ffaeac00 ffaeac10 ffaeac30 ffaeac60 ffaeac70 ffaeaca0 ffaeacb0 ffaeace0 ffaeae10 ffaeae20 ffaeb230
ffaeb250 ffaeb280 ffaeb2a0 ffaeb2b0 ffaeb2c0 ffaeb2d0 ffaf49c0 ffaf49e0 ffaf4a10 ffaf4a20 ffaf4a50 ffaf4a80 ffaf4a90
ffaf4aa0 ffaf4ab0 ffaf4ac0 ffaf4ad0 ffaf4af0 ffaf4b00 ffaf4b10 ffaf4b20 ffaf4b30 ffaf4b40 ffaf4b50 ffaf4b60 ffaf4b70
ffaf4b90 ffaf4ba0 ffaf4bb0 ffaf4bc0 ffaf4bd0 ffaf4bf0 ffaf4c00 ffaf4c10 ffaf4c20 ffaf4c40 ffaf4c50 ffaf4c60 ffaf4c70
ffaf4c90 ffb02b60 ffb02b80 ffb02bb0 ffb02c00 ffb02c20 ffb02c30 ffb02c40 ffb02c50 ffb02c60 ffb02c70 ffb02c80 ffb02c90
ffb02ca0 ffb02cb0 ffb02cc0 ffb02cd0 ffb02cf0 ffb0b930 ffb0b940 ffb0b960 ffb0b990 ffb0b9a0 ffb0b9d0 ffb0b9e0 ffb0ba10
ffb0ba20 ffb0ba30 ffb0ba40 ffb0baa0 ffb0bab0 ffb0bae0 ffb0baf0 ffb0bb00 ffb0bb10 ffb0bb20 ffb0bb30 ffb0bb50 ffb0bb60
ffb0bb70 ffb0bb80 ffb0bbb0 ffb0bbc0 ffb0bbd0 ffb0bbe0 ffb0bbf0 ffb0bc00 ffb0bc20 ffb0bc30 ffb0bc40 ffb0bc50 ffb0bc80
ffb0bc90 ffb0bca0 ffb0bcb0 ffb0bcc0 ffb0bcd0 ffb0bcf0 ffb0bd00 ffb0bd10 ffb0bd20 ffb0bd50 ffb0bd60 ffb0bd70 ffb0bd80
ffb0bd90 ffb0bda0 ffb0bdc0 ffb0bdd0 ffb0bde0 ffb0bdf0 ffb0be20 ffb0be30 ffb0be40 ffb0be50 ffb0be60 ffb0be70 ffb0be90
ffb0bea0 ffb0beb0 ffb0bec0 ffb0bef0 ffb0bf10 ffb0bf20 ffb0bf30 ffb0bf40 ffb0bf50 ffb0bf60 ffb0bf90 ffb0bfc0 ffb0bfd0
ffb0bfe0 ffb0bff0 ffb0c000 ffb0c010 ffb0c020 ffb0c030 ffb0c040 ffb0c050 ffb0c060 ffb0c090 ffb0c0a0 ffb0c0b0 ffb0c0c0
ffb0c0d0 ffb0c0e0 ffb0c0f0 ffb0c1e0 ffb0c210 ffb0c240 ffb0c250 ffb0c260 ffb0c270 ffb0c280 ffb0c290'''.split())
EINT_PC=0xff815070  # segment 1: the single enabling/accepting instruction
# Segment 2: first DI handler entry (cycle 19650563) up to the second DI handler entry (cycle 19764455):
# handler, return to 0xff815080 and the main line of the first frame. 875 distinct PCs
# (573 not in segment 0); 1306 traced lines, 66700 loop-skipped instructions.
FIRST_FRAME_PCS=tuple(int(x,16) for x in '''
ff805a40 ff805a60 ff805a90 ff805ab0 ff805ae0 ff805b00 ff805b30 ff805b50 ff805b70 ff805b80 ff805bb0 ff805be0 ff805bf0
ff805c00 ff806020 ff806040 ff806050 ff806060 ff806090 ff8060c0 ff8060f0 ff806100 ff806130 ff806160 ff806190 ff8061c0
ff8061f0 ff806220 ff806240 ff806270 ff8062a0 ff8062d0 ff806300 ff806330 ff806360 ff806390 ff8063b0 ff8063c0 ff8063d0
ff806400 ff806410 ff806440 ff806470 ff8064a0 ff8064c0 ff8064f0 ff806510 ff806530 ff806550 ff806580 ff8065b0 ff8065e0
ff806610 ff806640 ff806670 ff8066a0 ff8066d0 ff806700 ff806710 ff806730 ff806740 ff806750 ff806760 ff806780 ff806790
ff8067b0 ff8067e0 ff806810 ff806840 ff806850 ff806860 ff815080 ff8150b0 ff8150c0 ff8150f0 ff815120 ff815220 ff815230
ff815260 ff815280 ff8152b0 ff8152e0 ff81a7c0 ff81a7e0 ff81a800 ff81a810 ff81a820 ff81a850 ff81a880 ff81a890 ff81a8a0
ff81a8f0 ff81a900 ff81a930 ff81a960 ff81a990 ff81a9c0 ff81a9f0 ff81aa20 ff81aa50 ff81aa80 ff81aab0 ff81aad0 ff81ab00
ff81ab10 ff81ab40 ff81ab50 ff81ab60 ff81ab90 ff81abc0 ff81abf0 ff81ac20 ff81ac40 ff81ac50 ff81ac80 ff81aca0 ff81acd0
ff81ad00 ff81ad30 ff81ad60 ff81ad90 ff81adc0 ff81ae50 ff81ae80 ff81aeb0 ff81aec0 ff81aef0 ff81af20 ff81af30 ff81af60
ff81af80 ff81afb0 ff81b030 ff81b040 ff81b070 ff81b0a0 ff81b0d0 ff81b100 ff81b130 ff81b140 ff81b170 ff81b190 ff81b2a0
ff81b2c0 ff81b2e0 ff81b600 ff81b630 ff81b660 ff81b690 ff81b6c0 ff81b6f0 ff81b700 ff81b710 ff81b750 ff81b780 ff81b7b0
ff81b7e0 ff81b810 ff81b840 ff81b850 ff81b860 ff81b9a0 ff90bbf0 ff90bc00 ff90bc30 ff90bc60 ff90bc90 ff90bcc0 ff90bcf0
ff90bd20 ff90bd50 ff90bd80 ff90bdb0 ff9237d0 ff9237f0 ff923820 ff923830 ff923860 ff923890 ff9238c0 ff9238f0 ff923920
ff923950 ff923980 ff9239b0 ff9239c0 ff9239f0 ff923a00 ff923a30 ff923a60 ff923a70 ff923aa0 ff923ab0 ff923ac0 ff923af0
ff923b20 ff923b40 ff925280 ff9252b0 ff9252e0 ff925310 ff925320 ff925330 ff925360 ff925370 ff925380 ff925390 ff9253c0
ff925400 ff925430 ff925450 ff925460 ff925490 ff9254c0 ff9254d0 ff9254e0 ff925510 ff925520 ff925530 ff925540 ff925550
ff925560 ff925570 ff925580 ff9255a0 ff9255b0 ff9255d0 ff9255e0 ff925610 ff925620 ff925630 ff925640 ff925650 ff925660
ff925670 ff9256a0 ff9256e0 ff9256f0 ff925700 ff925730 ff925950 ff925970 ff925990 ff9259c0 ff9259e0 ff9259f0 ff925a00
ff925a10 ff925a40 ff925a60 ff925a70 ff925a80 ff925aa0 ff925c00 ff925c20 ff925c40 ff925c70 ff925c80 ff925c90 ff925ca0
ff925cc0 ff925cd0 ff925d00 ff925d20 ff925d40 ff925d50 ff925d70 ff925dd0 ff925df0 ff926040 ff926060 ff926080 ff926090
ff9260b0 ff9260c0 ff9260d0 ff9260e0 ff926100 ff926120 ff926130 ff926140 ff926160 ff926170 ff926180 ff926190 ff9261a0
ff9261c0 ff9261d0 ff9261f0 ff926210 ff926780 ff9267b0 ff9267e0 ff926810 ff926820 ff926850 ff926860 ff926890 ff9268a0
ff9268b0 ff9268e0 ff926910 ff926920 ff926950 ff9269d0 ff9269e0 ff9269f0 ff926a10 ff926a20 ff926a40 ff926a50 ff926a60
ff926a80 ff926aa0 ff926f20 ff926f40 ff926f70 ff926f80 ff926f90 ff926fc0 ff926fd0 ff926fe0 ff927010 ff927020 ff927040
ff927050 ff927070 ff927090 ff9270a0 ff9270b0 ff9270c0 ff9270e0 ff9270f0 ff927110 ff927120 ff927150 ff927160 ff927170
ff927180 ff9271a0 ff9271b0 ff9271c0 ff9271d0 ff9271e0 ff927290 ff9272b0 ff9272c0 ff9272e0 ff9272f0 ff927300 ff927330
ff927340 ff927350 ff927370 ff927380 ff927390 ff9273c0 ff9273d0 ff9273f0 ff927620 ff927630 ff927660 ff927670 ff927680
ff9276b0 ff9276e0 ff9276f0 ff927700 ff927730 ff927740 ff927750 ff927770 ff927780 ff927790 ff9277a0 ff9277c0 ff9277d0
ff9277e0 ff927800 ff927d40 ff927d50 ff927d80 ff927d90 ff927db0 ff928000 ff928010 ff928030 ff928060 ff928070 ff9280a0
ff9280b0 ff9280e0 ff928100 ff928130 ff928140 ff94d0a0 ff94d0b0 ff94d0e0 ff94d110 ff94d140 ff94d170 ff94d190 ff94d1b0
ff94d1d0 ff94d200 ff94d210 ff94d220 ff94d250 ff94d270 ff94d2a0 ff94d2c0 ff94d2f0 ff94d310 ff94d340 ff94d360 ff94d380
ff94d390 ff94d3a0 ff94d3b0 ff94d3c0 ff94d3e0 ff94d400 ff94d430 ff94d440 ff94d470 ff94d490 ff94d4a0 ff94d4c0 ff94d4e0
ff94d500 ff94d520 ff94d550 ff94d560 ff94d580 ff94d5b0 ff94d5c0 ff94d5f0 ff94d610 ff94d620 ff94d640 ff94d660 ff94d680
ff94d6b0 ff94d6c0 ff94d6e0 ff94d710 ff94d730 ff94d760 ff94d790 ff94d7c0 ff94d7f0 ff94d800 ff94d820 ff94d850 ff94d870
ff94d8a0 ff94d8c0 ff94d8e0 ff94d910 ff94d930 ff94d960 ff94d980 ff94d9a0 ff94d9d0 ff94d9e0 ff94da00 ff94da30 ff94da50
ff94da80 ff94daa0 ff94dac0 ff94dae0 ff94db10 ff94db20 ff94db50 ff94db70 ff94db80 ff94dba0 ff94dbb0 ff94dbd0 ff94dc00
ff94dc20 ff94dc30 ff94dc50 ff94dc60 ff94dc80 ff94dca0 ff94dcb0 ff94dce0 ff94dd10 ff94dd40 ff94dd70 ff94dd80 ff94dda0
ff94ddd0 ff94ddf0 ff94de20 ff94de40 ff94de60 ff94de90 ff94deb0 ff94ded0 ff94df00 ff94df10 ff94df30 ff94df60 ff94df80
ff94dfb0 ff94dfc0 ff94dfe0 ff94e010 ff94e030 ff94e060 ff94f840 ff94f860 ff94f870 ff94f8a0 ff94f8d0 ff94f900 ff94f920
ff94f930 ff94f960 ff94f990 ff94f9c0 ff94f9e0 ff94fa10 ff94fa30 ff94fa60 ff94fa70 ff94fa90 ff94fac0 ff94faf0 ff94fb20
ff94fb40 ff94fb50 ff94fb80 ff94fbb0 ff94fbe0 ff94fc00 ff94fc30 ff94fc50 ff94fc80 ff94fc90 ff94fcb0 ff94fcc0 ff94fcd0
ff94fcf0 ff94fd20 ff94fd90 ff94fdb0 ff94fdc0 ff94fde0 ff94fdf0 ff94fe10 ff94fe30 ff94fe50 ff94fe60 ff94fe90 ff94fec0
ff94ff00 ff94ff10 ff94ff30 ff94ff50 ff94ff70 ff94ffa0 ff94ffb0 ff9502e0 ff9502f0 ff950310 ff950320 ff950330 ff950360
ff95bb30 ff95bb60 ff95bba0 ff95bbd0 ff95c060 ff95c070 ff95c090 ff95c0c0 ff95c7b0 ff95c7c0 ff95c7f0 ff95f550 ff95f580
ff95f5b0 ff95f5e0 ff95f610 ff95f640 ff95f670 ff95f6a0 ff95f6d0 ff95f700 ff95f710 ff95f730 ff95f760 ff95f790 ff95f7c0
ff95f7f0 ff95f820 ff95f830 ff95f860 ff961490 ff9614a0 ff9614b0 ff9614c0 ff9614d0 ff9614e0 ff9614f0 ff961500 ff961510
ff961520 ff961530 ff961540 ff966860 ff966880 ff966890 ff9668c0 ff9668d0 ff9668f0 ff966900 ff96ca10 ff96ca30 ff96ca60
ff96ded0 ff96dee0 ff96df00 ff96df10 ff96df40 ff96df70 ff96dfa0 ff96dfd0 ff96dfe0 ff96e010 ff96e020 ff96e040 ff96e070
ff96e080 ff96e0b0 ff96e0c0 ff96e0f0 ff96e100 ff96e130 ff96e1f0 ff96e210 ff96e240 ff96e270 ff96e2a0 ff96e2d0 ff96e2e0
ff96e310 ff96e340 ff96e350 ff96e380 ff96f280 ff96f290 ff96f2c0 ff96f2d0 ff96f300 ff96f310 ff96f320 ff96f350 ff96f380
ff96f3a0 ff96f3d0 ff96f400 ff96f430 ff96f450 ffaa7b80 ffaa7b90 ffaa7bc0 ffaa7bd0 ffaa7c00 ffaa7c10 ffab6cd0 ffab6cf0
ffab6d00 ffab6d20 ffab6d30 ffab6d60 ffab74a0 ffab74c0 ffab74f0 ffab7500 ffab7510 ffab7520 ffab7530 ffab7540 ffab7550
ffab7560 ffab7570 ffab7590 ffab75a0 ffab75c0 ffab75f0 ffab7600 ffab7610 ffab7620 ffab7630 ffab7640 ffab7650 ffab7680
ffab7690 ffab76b0 ffab76c0 ffab76d0 ffab76f0 ffab7720 ffab7750 ffab7770 ffab7780 ffab77b0 ffac7c10 ffac7c20 ffac7c50
ffac7c80 ffac7c90 ffac7cc0 ffac7cd0 ffac7ce0 ffac7d10 ffac7d20 ffadb0d0 ffadb0f0 ffadb110 ffadb140 ffadb160 ffadb170
ffadb1a0 ffadb1b0 ffadb1c0 ffadb1d0 ffadb200 ffadb230 ffadb260 ffadb270 ffadb290 ffadb380 ffadb3a0 ffadb3b0 ffadb3d0
ffadb3f0 ffadb460 ffadb480 ffadb4b0 ffadb4d0 ffadb4e0 ffadb500 ffadb640 ffadb660 ffadb680 ffadb690 ffadb6c0 ffadb8b0
ffadb8d0 ffadb8f0 ffadb920 ffadb940 ffadb950 ffadb960 ffadb980 ffadb9a0 ffadb9d0 ffadb9f0 ffadba00 ffadbd20 ffadbd30
ffadbd50 ffadbd60 ffadbd70 ffadbd90 ffadc230 ffadc240 ffadc250 ffadc280 ffadc2e0 ffadc300 ffadc320 ffadc330 ffadc340
ffadc360 ffadc380 ffadc390 ffadc3c0 ffadc3d0 ffadc3f0 ffadc420 ffadc430 ffadc450 ffadc460 ffadc480 ffadc4a0 ffadc4b0
ffadc4c0 ffadc4e0 ffadc500 ffadc510 ffadc540 ffadc550 ffadc570 ffadc5a0 ffadc5b0 ffadc5d0 ffae2310 ffae2330 ffae2350
ffae2380 ffae23b0 ffae23e0 ffae2400 ffae2af0 ffae2b10 ffae2b30 ffae2b60 ffae2b80 ffae2ee0 ffae2f00 ffae2f20 ffae2f50
ffae2f60 ffae2f70 ffae2f90 ffae2fb0 ffae3030 ffae3050 ffae3800 ffae3820 ffae3850 ffae3880 ffae3890 ffae38c0 ffae38e0
ffae3b30 ffae3b50 ffae3b80 ffae3bb0 ffae3bc0 ffae3bf0 ffae3c00 ffae3c10 ffae4250 ffaf49c0 ffaf49e0 ffaf4a10 ffaf4a20
ffaf4a50 ffaf4a80 ffaf4a90 ffaf4aa0 ffaf4ab0 ffaf4ac0 ffaf4ad0 ffaf4af0 ffaf4b00 ffaf4b10 ffaf4b20 ffaf4b30 ffaf4b40
ffaf4b50 ffaf4b60 ffaf4b70 ffaf4b90 ffaf4ba0 ffaf4bb0 ffaf4bc0 ffaf4bd0 ffaf4bf0 ffaf4c00 ffaf4c10 ffaf4c20 ffaf4c40
ffaf4c50 ffaf4c60 ffaf4c70 ffaf4c90'''.split())
# Segment 3: second DI handler entry (cycle 19764455) up to the first DMA trigger (cycle 20795274): frames 2-10 with nine
# more DI (each at a timeslice start) and the TRAP 1 of 0xff8044f0 into 0xff8045d0, which loads the DMA registers.
# 1007 distinct PCs (764 not in segments 0-2); 28449 traced lines, 293840 loop-skipped instructions.
FRAME2_TO_DMA_PCS=tuple(int(x,16) for x in '''
ff804000 ff804010 ff804030 ff804050 ff804060 ff804070 ff804080 ff804090 ff8040b0 ff8040c0 ff8040d0 ff8040e0 ff8040f0
ff804110 ff804130 ff804140 ff804160 ff804170 ff804180 ff8042a0 ff8042b0 ff8042c0 ff8042d0 ff8042e0 ff8042f0 ff804300
ff804310 ff804320 ff804330 ff804340 ff804350 ff804360 ff804390 ff8043a0 ff8043f0 ff804400 ff804410 ff804430 ff804440
ff804450 ff804460 ff804470 ff8044a0 ff8044b0 ff8044e0 ff8044f0 ff8045a0 ff8045b0 ff8045c0 ff8045d0 ff8045e0 ff8045f0
ff804600 ff804610 ff804620 ff804630 ff8049b0 ff8049e0 ff804a00 ff804a30 ff804a50 ff804a80 ff804aa0 ff804ab0 ff804ae0
ff804b10 ff804b40 ff804b70 ff804ba0 ff804bd0 ff804bf0 ff804c10 ff804c20 ff804c30 ff804c40 ff804c50 ff804c70 ff804ca0
ff804cd0 ff804cf0 ff804d10 ff804d20 ff804d30 ff804d40 ff804d50 ff804d60 ff804d80 ff804db0 ff804de0 ff804df0 ff804e20
ff804e50 ff804e80 ff804e90 ff804ec0 ff804ee0 ff804f10 ff804f40 ff804f50 ff804f80 ff804fb0 ff804fc0 ff804fd0 ff804fe0
ff804ff0 ff805000 ff805010 ff805020 ff805050 ff805060 ff805080 ff805a40 ff805a60 ff805a90 ff805ab0 ff805ae0 ff805b00
ff805b30 ff805b50 ff805b70 ff805b80 ff805bb0 ff805be0 ff805bf0 ff805c00 ff805c10 ff805c30 ff805c50 ff805c60 ff805c70
ff805c80 ff805c90 ff805d20 ff805d30 ff805d40 ff805d50 ff805d60 ff805d70 ff805d80 ff806780 ff806790 ff8067b0 ff8067e0
ff806810 ff806840 ff806850 ff806860 ff806e50 ff806e70 ff806ea0 ff806eb0 ff806ec0 ff806ef0 ff806f00 ff806f20 ff806f30
ff806f40 ff806f50 ff806f60 ff806f70 ff806f80 ff806fa0 ff806fd0 ff806ff0 ff807010 ff807080 ff8070a0 ff8070d0 ff8071d0
ff8071f0 ff807210 ff807220 ff807230 ff807240 ff807260 ff807270 ff807280 ff807290 ff8072b0 ff8072c0 ff8072d0 ff8072e0
ff8072f0 ff807310 ff8079e0 ff807a00 ff807a10 ff807a30 ff807a40 ff807a60 ff807f20 ff807f40 ff807f60 ff807f70 ff807f80
ff807f90 ff807fc0 ff807fd0 ff807fe0 ff807ff0 ff808000 ff808030 ff808040 ff808070 ff808090 ff8080f0 ff808100 ff808130
ff808160 ff808190 ff8081a0 ff8081c0 ff8081f0 ff808200 ff808230 ff808250 ff808260 ff808280 ff808290 ff8152e0 ff815310
ff815320 ff815360 ff815390 ff8153c0 ff8153f0 ff815410 ff815440 ff815470 ff8154a0 ff8154c0 ff8154f0 ff815520 ff815540
ff815570 ff8155a0 ff8155d0 ff8155f0 ff815620 ff815650 ff815680 ff8156b0 ff815820 ff815850 ff815860 ff815870 ff8159c0
ff8159f0 ff815a20 ff815a30 ff815a60 ff815a80 ff815a90 ff815aa0 ff815ad0 ff815ae0 ff815af0 ff815b20 ff815b50 ff815b80
ff815bb0 ff815be0 ff815bf0 ff815c10 ff815c20 ff815c60 ff815c70 ff815c80 ff815ca0 ff815cd0 ff815ce0 ff815cf0 ff815d00
ff815d10 ff815d20 ff815d30 ff815d40 ff815d60 ff815d70 ff815d80 ff815d90 ff815da0 ff815db0 ff815dc0 ff815dd0 ff815de0
ff815df0 ff815e00 ff815e20 ff815e40 ff815e50 ff81a7c0 ff81a7e0 ff81a800 ff81a810 ff81a820 ff81a850 ff81a880 ff81a890
ff81a8a0 ff81a8f0 ff81a900 ff81a930 ff81a960 ff81a990 ff81a9c0 ff81a9f0 ff81aa20 ff81aa50 ff81aa80 ff81aab0 ff81aad0
ff81ab00 ff81ab10 ff81ab40 ff81ad60 ff81ad90 ff81adc0 ff81ae50 ff81ae80 ff81aeb0 ff81aec0 ff81aef0 ff81af20 ff81af30
ff81af60 ff81af80 ff81afb0 ff81afc0 ff81b030 ff81b040 ff81b070 ff81b0a0 ff81b0d0 ff81b100 ff81b130 ff81b140 ff81b170
ff81b190 ff81b1a0 ff81b1b0 ff81b1e0 ff81b210 ff81b240 ff81b270 ff81b2a0 ff81b2c0 ff81b2e0 ff81b600 ff81b630 ff81b660
ff81b690 ff81b6c0 ff81b6f0 ff81b700 ff81b710 ff81b750 ff81b780 ff81b7b0 ff81b7e0 ff81b810 ff81b840 ff81b850 ff81b860
ff81b9a0 ff925320 ff925330 ff925360 ff925370 ff925380 ff925390 ff9253c0 ff925400 ff925430 ff925450 ff925460 ff925490
ff9254c0 ff9254d0 ff9254e0 ff925510 ff925520 ff925530 ff925540 ff925550 ff925560 ff925570 ff925580 ff9255a0 ff9255b0
ff9255d0 ff9255e0 ff925610 ff925620 ff925630 ff925640 ff925650 ff925660 ff925670 ff9256a0 ff9256e0 ff9256f0 ff925700
ff925730 ff925c00 ff925c20 ff925c40 ff925c70 ff925c80 ff925c90 ff925ca0 ff925cc0 ff925cd0 ff925d00 ff925d20 ff925d40
ff925d50 ff925d70 ff925dd0 ff925df0 ff926040 ff926060 ff926080 ff926090 ff9260b0 ff9260c0 ff9260d0 ff9260e0 ff926100
ff926120 ff926130 ff926140 ff926160 ff926170 ff926180 ff926190 ff9261a0 ff9261c0 ff9261d0 ff9261f0 ff926210 ff926780
ff9267b0 ff9267e0 ff926810 ff926820 ff926850 ff926860 ff926890 ff9268a0 ff9268b0 ff9268e0 ff926910 ff926920 ff926950
ff926960 ff926970 ff926980 ff9269a0 ff9269c0 ff9269d0 ff9269e0 ff9269f0 ff926a10 ff926a20 ff926a40 ff926a50 ff926a60
ff926a80 ff926aa0 ff926ab0 ff926f20 ff926f40 ff926f70 ff926f80 ff926f90 ff926fc0 ff926fd0 ff926fe0 ff927010 ff927020
ff927040 ff927050 ff927070 ff927090 ff9270a0 ff9270b0 ff9270c0 ff9270e0 ff927620 ff927630 ff927660 ff927670 ff927680
ff9276b0 ff9276e0 ff9276f0 ff927700 ff927730 ff927740 ff927750 ff927770 ff928130 ff928140 ff928150 ff928180 ff9281a0
ff92b610 ff92b620 ff92b650 ff92b680 ff92b6b0 ff92b6e0 ff92b710 ff92b730 ff92b760 ff92b780 ff92b7b0 ff92b7e0 ff92b800
ff92b810 ff92b820 ff92b840 ff92c010 ff92c030 ff92c040 ff92c070 ff92c120 ff92c140 ff92c170 ff92c4a0 ff92c4b0 ff92c4c0
ff92c4d0 ff92c500 ff92c520 ff92c530 ff92c550 ff92c560 ff92c580 ff92c590 ff92c5b0 ff92c5c0 ff92c5d0 ff92c5e0 ff92c620
ff92c640 ff92c670 ff92c6a0 ff92c6b0 ff92c6d0 ff92c6e0 ff92c6f0 ff92c700 ff92c710 ff92c720 ff92c730 ff92c750 ff92c760
ff92c780 ff92c790 ff92c7a0 ff92c7c0 ff92c7d0 ff92c800 ff92c820 ff92c850 ff92c860 ff92c880 ff92c8e0 ff92c900 ff92c910
ff92c920 ff92c930 ff92c940 ff92c960 ff92c980 ff92c9a0 ff92c9b0 ff92c9c0 ff92c9d0 ff92c9e0 ff92c9f0 ff92ca00 ff92ca10
ff92ca20 ff92ca30 ff92ca40 ff92ca50 ff92ca60 ff92ca70 ff92ca80 ff92ca90 ff92caa0 ff92cac0 ff92cad0 ff92caf0 ff92cb00
ff92cb20 ff92cb30 ff92cb40 ff92cb50 ff92cb60 ff92cb70 ff92cb80 ff92cb90 ff92cbb0 ff92d780 ff92d790 ff92d7a0 ff92d7b0
ff92d7e0 ff92d810 ff92d830 ff92d860 ff92d870 ff92d8a0 ff92d970 ff92d990 ff92d9a0 ff92d9b0 ff92d9c0 ff92d9d0 ff92d9e0
ff92d9f0 ff92da00 ff92da10 ff92da20 ff92da30 ff92da40 ff92da50 ff92da60 ff92da70 ff92da80 ff92da90 ff92daa0 ff92dab0
ff92dac0 ff92dad0 ff92dae0 ff92daf0 ff92db00 ff92db10 ff92db20 ff92db40 ff940970 ff9409a0 ff9409c0 ff9409f0 ff940a00
ff940a20 ff940a40 ff940a70 ff940aa0 ff940ad0 ff940b00 ff940b30 ff940b60 ff940b70 ff940ba0 ff940bc0 ff940bf0 ff940c20
ff940c50 ff940c80 ff940cb0 ff940ce0 ff940cf0 ff940d10 ff940d40 ff940d60 ff950530 ff950560 ff950580 ff950590 ff9505b0
ff9505e0 ff950610 ff950630 ff950640 ff950660 ff950690 ff95bb70 ff95bba0 ff95bbd0 ff95c080 ff95c090 ff95c0c0 ff96ca90
ff96cac0 ff96cad0 ff96caf0 ff96cb00 ff96cb30 ff96cb60 ff96cb90 ff96cba0 ff96cbc0 ff96cbd0 ff96cc00 ff96cc30 ff96cc60
ff96cc80 ff96cc90 ff96ccb0 ff96ccc0 ffaa80d0 ffaa8100 ffaa8230 ffaa8260 ffaa8390 ffaa83c0 ffaa84f0 ffaa8520 ffaa8650
ffaa8680 ffaa87b0 ffaaec00 ffaaec20 ffaaec50 ffaaed10 ffaaed40 ffaaed60 ffab7e00 ffab7e20 ffab7e40 ffab7e50 ffab7e70
ffab7e80 ffab7e90 ffab7eb0 ffab7ed0 ffab8350 ffab8380 ffab83b0 ffab8580 ffab85b0 ffab85c0 ffab85f0 ffab8600 ffab8620
ffab8650 ffab8670 ffab8680 ffab86a0 ffab86b0 ffab87e0 ffab87f0 ffab8800 ffab8810 ffab8830 ffab8840 ffab8850 ffab8870
ffab8880 ffab8890 ffab88a0 ffab88b0 ffab88c0 ffab88d0 ffab88e0 ffab8910 ffab8990 ffab89b0 ffab89e0 ffab8a00 ffab8a50
ffab8a70 ffab8aa0 ffab8ac0 ffab8b10 ffab8b30 ffab8b60 ffab8b80 ffab8bb0 ffab8bd0 ffab8be0 ffab8bf0 ffab8c00 ffab8c10
ffab8c20 ffab8c30 ffab8c50 ffab8e80 ffab8ea0 ffab8eb0 ffab8ed0 ffab8ee0 ffab8ef0 ffab8f00 ffab8f30 ffab8f60 ffab8f70
ffab8f90 ffab8fc0 ffab8fe0 ffab8ff0 ffab9000 ffab9020 ffab9040 ffab9060 ffab9070 ffab90a0 ffab90d0 ffab91d0 ffab91e0
ffab9210 ffab9220 ffab9240 ffab9260 ffab9290 ffab92a0 ffab92c0 ffab92f0 ffab9300 ffab9320 ffab9340 ffab9360 ffab9370
ffab9390 ffab93b0 ffab93d0 ffab93f0 ffab9410 ffab9430 ffab9450 ffab9460 ffab9480 ffab9490 ffab94a0 ffab94b0 ffab94d0
ffab94e0 ffab9500 ffab9510 ffab9530 ffab9540 ffab9550 ffab9580 ffab95b0 ffab98d0 ffab9c20 ffab9c30 ffab9c80 ffab9ca0
ffab9cb0 ffab9cd0 ffab9ce0 ffab9cf0 ffab9da0 ffab9db0 ffab9dc0 ffab9dd0 ffab9df0 ffab9e10 ffab9e20 ffab9e50 ffab9e70
ffab9ea0 ffab9ec0 ffab9f20 ffab9f50 ffab9f60 ffab9f90 ffab9fb0 ffab9fc0 ffab9ff0 ffaba000 ffaba010 ffaba020 ffaba030
ffaba040 ffaba050 ffaba060 ffaba070 ffaba080 ffaba0a0 ffaba140 ffaba150 ffaba1c0 ffaba1e0 ffaba7d0 ffaba7f0 ffaba800
ffaba820 ffaba840 ffaba850 ffaba860 ffaba880 ffaba8c0 ffaba8e0 ffaba970 ffaba990 ffabaa20 ffabaa40 ffabaad0 ffabaaf0
ffabab80 ffababa0 ffabac30 ffabac50 ffabace0 ffabad00 ffabad10 ffabad30 ffabaf80 ffabaf90 ffabafa0 ffabafb0 ffabafd0
ffabafe0 ffabb010 ffabb020 ffabb050 ffabb060 ffabb080 ffabb090 ffabb0a0 ffabb0b0 ffabb0c0 ffabb0d0 ffabb0e0 ffabb0f0
ffabb100 ffabb140 ffabb160 ffabb170 ffabb180 ffabb1a0 ffabb1b0 ffabb1c0 ffabb1f0 ffabb220 ffabb230 ffabb260 ffabb290
ffabb380 ffabb3a0 ffabb9a0 ffabb9b0 ffabb9c0 ffabb9d0 ffabb9e0 ffabba00 ffabba10 ffabba30 ffabba40 ffabba50 ffabba60
ffabba70 ffabbaa0 ffabbab0 ffabbac0 ffabbad0 ffabbbe0 ffabbbf0 ffabbc10 ffabbc50 ffabbc70 ffabbeb0 ffabbed0 ffabbee0
ffabbf00 ffabbf10 ffabbf20 ffabbf30 ffabbf50 ffabbf60 ffabbf80 ffabbf90 ffabbfa0 ffabbfc0 ffabc050 ffabc070 ffabc080
ffabc090 ffabc0a0 ffabc0c0 ffabc0d0 ffabc0e0 ffabc0f0 ffabc110 ffabc120 ffabc130 ffabc140 ffabc150 ffabc160 ffabc180
ffabd230 ffabd250 ffabd270 ffae3800 ffae3820 ffae3850 ffae3880 ffae3890 ffae38c0 ffae38e0 ffae3b30 ffae3b50 ffae3b80
ffae3bb0 ffae3bc0 ffae3bf0 ffae3c00 ffae3c10 ffae4250'''.split())
# Handler entries in segment 3: (entry cycle, handler, pushed PC, pushed ST, SP after, last instruction PC, its start cycle).
FRAME2_TO_DMA_ENTRIES=(
    (19878700,0xff81a7c0,0xff925ca0,0x40200030,0x010ffef0,0xff925c90,19878683),
    (19992965,0xff81a7c0,0xff805a60,0x60200030,0x010ffe90,0xff805a40,19992919),
    (20107191,0xff81a7c0,0xff9267b0,0x60200030,0x010fff90,0xff926810,20107173),
    (20221436,0xff81a7c0,0xff805a40,0x60200030,0x010fff70,0xff9267b0,20221416),
    (20335693,0xff81a7c0,0xff805b70,0x20200030,0x010fff70,0xff805b50,20335646),
    (20449932,0xff81a7c0,0xff805b70,0x60200030,0x010fff70,0xff805b50,20449885),
    (20564173,0xff81a7c0,0xff807230,0x00200030,0x010ffdf0,0xff807220,20564154),
    (20678417,0xff81a7c0,0xff807280,0x20200030,0x010ffdf0,0xff807270,20678400),
    (20792665,0xff81a7c0,0xff805c50,0x00200030,0x010ffe70,0xff805c30,20792644),
    (20795252,0xff8045d0,0xff804500,0x20000030,0x010ffb70,0xff8044f0,20795236),
)
# Segment 4: first DMA trigger (cycle 20795274) up to the third DI handler entry after it (cycle 21135398, end of the
# third frame after the first DMA): 410 TRAP 1 entries from 0xff8044f0 into the INT1/TRAP handler 0xff8045d0 (each one
# DMA from the display list), 63 0x800c fills from the MMTM at 0xff8052b0, 474 triggers in all, and two more DI.
# 543 distinct PCs (52 not in segments 0-3); 30931 traced lines. A trace started at 0xff804640 gives the same set.
DMA_TO_FRAME3_PCS=tuple(int(x,16) for x in '''
ff804000 ff804010 ff804030 ff804050 ff804060 ff804070 ff804080 ff804090 ff8040b0 ff8040c0 ff8040d0 ff8040e0 ff8040f0
ff804110 ff804130 ff804140 ff804160 ff804170 ff804180 ff8042a0 ff8042b0 ff8042c0 ff8042d0 ff8042e0 ff8042f0 ff804300
ff804310 ff804320 ff804330 ff804340 ff804350 ff804360 ff804390 ff8043a0 ff8043f0 ff804400 ff804410 ff804430 ff804440
ff804450 ff804460 ff804470 ff8044a0 ff8044b0 ff8044e0 ff8044f0 ff804500 ff804510 ff804520 ff804530 ff804560 ff8045a0
ff8045b0 ff8045c0 ff8045d0 ff8045e0 ff8045f0 ff804600 ff804610 ff804620 ff804630 ff804640 ff804650 ff804660 ff804670
ff804680 ff8046b0 ff8046c0 ff8046d0 ff8046e0 ff8049b0 ff8049e0 ff804a00 ff804a30 ff804a50 ff804a80 ff804aa0 ff804ab0
ff804ae0 ff804b10 ff804b40 ff804b70 ff804ba0 ff804bd0 ff804bf0 ff804c10 ff804c20 ff804c30 ff804c40 ff804c50 ff804c70
ff804ca0 ff804cd0 ff804cf0 ff804d10 ff804d20 ff804d30 ff804d40 ff804d50 ff804d60 ff804d80 ff804db0 ff804de0 ff804df0
ff804e20 ff804e50 ff804e80 ff804e90 ff804ec0 ff804ee0 ff804f10 ff804f40 ff804f50 ff804f80 ff804fb0 ff804fc0 ff804fd0
ff804fe0 ff804ff0 ff805000 ff805010 ff805020 ff805050 ff805060 ff805080 ff8050c0 ff8050d0 ff805100 ff805110 ff805140
ff805170 ff8051a0 ff8051c0 ff8051d0 ff8051f0 ff805200 ff805230 ff805240 ff805270 ff805280 ff8052b0 ff8052d0 ff8052f0
ff805300 ff805310 ff805330 ff805360 ff805540 ff805a40 ff805a60 ff805a90 ff805ab0 ff805ae0 ff805b00 ff805b30 ff805b50
ff805b70 ff805b80 ff805bb0 ff805be0 ff805bf0 ff805c00 ff805c10 ff805c30 ff805c50 ff805c60 ff805c70 ff805c80 ff805c90
ff805d20 ff805d30 ff805d40 ff805d50 ff805d60 ff805d70 ff805d80 ff806780 ff806790 ff8067b0 ff8067e0 ff806810 ff806840
ff806850 ff806860 ff8152e0 ff815310 ff815320 ff815360 ff815390 ff8153c0 ff8153f0 ff815410 ff815440 ff815470 ff8154a0
ff8154c0 ff8154f0 ff815520 ff815540 ff815570 ff8155a0 ff8155d0 ff8155f0 ff815620 ff815650 ff815680 ff8156b0 ff815820
ff815850 ff815860 ff815870 ff8159c0 ff8159f0 ff815a20 ff815a30 ff815a60 ff815a80 ff815a90 ff815aa0 ff815ad0 ff815ae0
ff815af0 ff815b20 ff815b50 ff815b80 ff815bb0 ff815be0 ff815bf0 ff815c10 ff815c20 ff815c60 ff815c70 ff815c80 ff815ca0
ff815cd0 ff815ce0 ff815cf0 ff815d00 ff815d10 ff815d20 ff815d90 ff815da0 ff815db0 ff815dc0 ff815dd0 ff815de0 ff815df0
ff815e00 ff815e20 ff815e40 ff815e50 ff81a7c0 ff81a7e0 ff81a800 ff81a810 ff81a820 ff81a850 ff81a880 ff81a890 ff81a8a0
ff81a8f0 ff81a900 ff81a930 ff81a960 ff81a990 ff81a9c0 ff81a9f0 ff81aa20 ff81aa50 ff81aa80 ff81aab0 ff81aad0 ff81ab00
ff81ab10 ff81ab40 ff81ad60 ff81ad90 ff81adc0 ff81ae50 ff81ae80 ff81aeb0 ff81aec0 ff81aef0 ff81af20 ff81af30 ff81af60
ff81af80 ff81afb0 ff81afc0 ff81aff0 ff81b020 ff81b030 ff81b040 ff81b070 ff81b0a0 ff81b0d0 ff81b100 ff81b130 ff81b140
ff81b170 ff81b190 ff81b2a0 ff81b2c0 ff81b2e0 ff81b600 ff81b630 ff81b660 ff81b690 ff81b6c0 ff81b6f0 ff81b700 ff81b710
ff81b750 ff81b780 ff81b7b0 ff81b7e0 ff81b810 ff81b840 ff81b850 ff81b860 ff81b9a0 ff925320 ff925330 ff925360 ff925370
ff925380 ff925390 ff9253c0 ff925400 ff925430 ff925450 ff925460 ff925490 ff9254c0 ff9254d0 ff9254e0 ff925510 ff925520
ff925530 ff925540 ff925550 ff925560 ff925570 ff925580 ff9255a0 ff9255b0 ff9255d0 ff9255e0 ff925610 ff925620 ff925630
ff925640 ff925650 ff925660 ff925670 ff9256a0 ff9256e0 ff9256f0 ff925700 ff925730 ff926780 ff9267b0 ff9267e0 ff926810
ff926820 ff926850 ff926860 ff926890 ff9268a0 ff9268b0 ff9268e0 ff926910 ff926920 ff926950 ff926960 ff926970 ff926980
ff9269a0 ff9269c0 ff9269d0 ff9269e0 ff9269f0 ff926a10 ff926a20 ff926a40 ff926a50 ff926a60 ff926a80 ff926aa0 ff926ab0
ff926ac0 ff926af0 ff926b00 ff926b10 ff926b20 ff926b30 ff926b40 ff926b50 ff926b80 ff926b90 ff926bc0 ff926bd0 ff927620
ff927630 ff927660 ff927670 ff927680 ff9276b0 ff9276e0 ff9276f0 ff927700 ff927730 ff927740 ff927750 ff927770 ff92c700
ff92c710 ff92c720 ff92c730 ff92c750 ff92c760 ff92c780 ff92c790 ff92c7a0 ff92c7c0 ff92c7d0 ff92c800 ff92c820 ff92c850
ff92c8b0 ff92c8e0 ff92c900 ff92c910 ff92c920 ff92c930 ff92c940 ff92c960 ff92c980 ff92c9a0 ff92c9b0 ff92c9c0 ff92c9d0
ff92c9e0 ff92c9f0 ff92ca00 ff92ca10 ff92ca20 ff92ca30 ff92ca40 ff92ca50 ff92ca60 ff92ca70 ff92ca80 ff92ca90 ff92caa0
ff92cac0 ff92cad0 ff92caf0 ff92cb00 ff92cb20 ff92cb30 ff92cb40 ff92cb50 ff92cb60 ff92cb70 ff92cb80 ff92cb90 ff92cbb0
ff92d790 ff92d7a0 ff92d7b0 ff92d7e0 ff92d810 ff92d830 ff92d860 ff92d870 ff92d8a0 ff92d970 ff92d990 ff92d9a0 ff92d9b0
ff92d9c0 ff92d9d0 ff92d9e0 ff92d9f0 ff92da00 ff92da10 ff92da20 ff92da30 ff92da40 ff92da50 ff92da60 ff92da70 ff92da80
ff92da90 ff92daa0 ff92dab0 ff92dac0 ff92dad0 ff92dae0 ff92daf0 ff92db00 ff92db10 ff92db20 ff92db40 ff950530 ff950560
ff950580 ff950590 ff9505b0 ff9505e0 ff950610 ff950630 ff950640 ff950660 ff950690 ffaa80d0 ffaa8100 ffaa8230 ffaa8260
ffaa8390 ffaa83c0 ffaa84f0 ffaa8520 ffaa8650 ffaa8680 ffaa87b0 ffae3800 ffae3820 ffae3850 ffae3880 ffae3890 ffae38c0
ffae38e0 ffae3b30 ffae3b50 ffae3b80 ffae3bb0 ffae3bc0 ffae3bf0 ffae3c00 ffae3c10 ffae4250'''.split())
# DI handler entries in segment 4, as FRAME2_TO_DMA_ENTRIES; and the TRAP 1 entries: count, (pushed PC, pushed ST, SP after,
# last instruction PC), the same for all.
DMA_TO_FRAME3_ENTRIES=(
    (20906909,0xff81a7c0,0xff805c30,0x00200030,0x010ffe70,0xff805c10,20906888),
    (21021157,0xff81a7c0,0xff805c50,0x00200030,0x010ffe70,0xff805c30,21021136),
)
DMA_TO_FRAME3_TRAPS=(410,((0xff804500,0x30,0x010ffb70,0xff8044f0),))
# Every main-CPU access to its I/O registers in segments 0-1: (cycle, kind, pc, register, value). No HCOUNT, VCOUNT
# or INTPEND read happens before the first interrupt. The 28-register table of 0xff81a160 is written a third time
# at 0xff81a120 (cycles 19,410,963-19,411,125, 6 cycles apart); it is kept as one row with its values.
IO_TABLE=dict(pc=0xff81a120,first_cycle=19410963,cycle_step=6,values=(0x2b,0x65,0x1f5,0x1f9,0x3,0x14,0x112,0x120,0xf010,0xfffc,0x112,0x2c,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x8,0x0,0x0,0x0,0x0,0x0,0x1c))
IO_ROWS=(
    (13083973,'W',0xffae8530,'CONVDP',0x13),
    (13086141,'W',0xffae8530,'CONVDP',0x13),
    (13089778,'W',0xffae8530,'CONVDP',0x13),
    (13097620,'W',0xffae8530,'CONVDP',0x13),
    (13100229,'W',0xffae8530,'CONVDP',0x13),
    (19411205,'W',0xff927fa0,'CONVSP',0x13),
    (19411208,'W',0xff927fd0,'CONVDP',0x13),
    (19607903,'W',0xff819760,'INTENB',0x404),
    (19609309,'R',0xff806090,'INTENB',0x404),
    (19609317,'W',0xff8060f0,'INTENB',0x404),)
# DMA_COMMAND writes in segments 0-1: (cycle, pc, value). None has bit 15, so no DMA interrupt is armed before
# the first interrupt. First trigger of the run: cycle 20795274.
DMA_COMMAND_ROWS=((19411226,0xff819590,0x0),(19411229,0xff8195c0,0x0))

def measure(seconds=4):
    from tools.mk3 import reference_video,test_video
    r=reference_video.capture(seconds,trace=True,stops=(FRONTIERS['first_enable']['cycle'],FRONTIERS['first_interrupt']['handler_entry_cycle'],
                                                        FRONTIERS['first_timer_interrupt']['handler_entry_cycle'],FRONTIERS['first_dma']['cycle'],
                                                        FRONTIERS['frame3_after_dma']['handler_entry_cycle']))
    assert FRONTIERS['first_dma']['pc'] in r['pcs'][4]
    lo,hi=FRONTIERS['trace_start']['cycle'],FRONTIERS['first_interrupt']['handler_entry_cycle'];a,b=r['irq'][:2]
    io=[x for x in r['io'] if lo<=x[4]<hi];table=[x for x in io if x[1]==IO_TABLE['pc']]
    entries=tuple((x['cycles'],x['handler'],x['pushed_pc'],x['pushed_status'],x['sp'],x['temps'][2],x['temps'][0]) for x in r['irq']
                  if FRONTIERS['first_timer_interrupt']['handler_entry_cycle']<x['cycles']<FRONTIERS['first_dma']['cycle'])
    first_dma=next((x[4],x[3],x[1]) for x in r['dma'] if x[2]>>4&15==1 and x[3]&0x8000)
    entries4=tuple((x['cycles'],x['handler'],x['pushed_pc'],x['pushed_status'],x['sp'],x['temps'][2],x['temps'][0]) for x in r['irq']
                   if FRONTIERS['first_dma']['cycle']<=x['cycles']<FRONTIERS['frame3_after_dma']['handler_entry_cycle'])
    return dict(handlers=r['handlers'],segment0=set(r['pcs'][0]),segment1=tuple(r['pcs'][1]),segment2=set(r['pcs'][2]),
        segment3=set(r['pcs'][3]),entries3=entries,first_dma=first_dma,segment4=set(r['pcs'][4]),
        entries4=tuple(e for e in entries4 if e[1]!=HANDLERS['INT1']),traps4=(sum(e[1]==HANDLERS['INT1'] for e in entries4),tuple(sorted({(e[2],e[3],e[4],e[5]) for e in entries4 if e[1]==HANDLERS['INT1']}))),
        frame3=next((x['handler'],x['cycles'],x['pushed_pc'],x['pushed_status']) for x in r['irq'] if x['cycles']>=FRONTIERS['frame3_after_dma']['handler_entry_cycle']),
        first_enable=(a['temps'][2],a['temps'][0]),first_ie=(r['first_ie']['pc'],r['first_ie']['cycles'],r['first_ie']['status']),
        first_interrupt=(a['handler'],a['cycles'],a['pushed_pc'],a['pushed_status'],a['status'],a['sp']),
        first_timer=(b['cycles'],b['temps'][2],b['temps'][0],b['pushed_pc'],b['pushed_status']),
        table=(table[0][4],tuple(x[3] for x in table),{x[4]-table[0][4]-6*i for i,x in enumerate(table)}),
        io=tuple((x[4],x[0],x[1],test_video.NAMES[(x[2]-test_video.IO)>>4],x[3]) for x in io if x[1]!=IO_TABLE['pc']),
        dma=tuple((x[4],x[1],x[3]) for x in r['dma'] if lo<=x[4]<hi and x[2]>>4&15==1),cleanup=r['cleanup']['exists_after'])

def stored():
    f=FRONTIERS;i,t=f['first_interrupt'],f['first_timer_interrupt']
    return dict(handlers=HANDLERS,segment0=set(WAIT_TO_EINT_PCS),segment1=(EINT_PC,),segment2=set(FIRST_FRAME_PCS),
        segment3=set(FRAME2_TO_DMA_PCS),entries3=FRAME2_TO_DMA_ENTRIES,segment4=set(DMA_TO_FRAME3_PCS),entries4=DMA_TO_FRAME3_ENTRIES,traps4=DMA_TO_FRAME3_TRAPS,
        frame3=tuple(f['frame3_after_dma'].values()),first_dma=tuple(f['first_dma'][k] for k in ('cycle','command','watchpoint_pc')),
        first_enable=(f['first_enable']['pc'],f['first_enable']['cycle']),first_ie=tuple(f['first_boundary_with_ie'].values()),
        first_interrupt=(i['handler'],i['handler_entry_cycle'],i['pushed_pc'],i['pushed_status'],i['status_after'],i['sp_after']),
        first_timer=(t['handler_entry_cycle'],t['last_instruction']['pc'],t['last_instruction']['cycle'],t['pushed_pc'],t['pushed_status']),
        table=(IO_TABLE['first_cycle'],IO_TABLE['values'],{0}),io=IO_ROWS,dma=DMA_COMMAND_ROWS,cleanup=False)

if __name__=='__main__':
    import sys;from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    if '--check' in sys.argv:
        got,want=measure(),stored();bad=[k for k in want if got[k]!=want[k]]
        if bad:raise SystemExit('MK3 post-sound measurement differs: '+', '.join(bad))
    print(dict(segment0=len(WAIT_TO_EINT_PCS),segment1=1,segment2=len(FIRST_FRAME_PCS),segment3=len(FRAME2_TO_DMA_PCS),segment4=len(DMA_TO_FRAME3_PCS),
               union=len(set(WAIT_TO_EINT_PCS)|{EINT_PC}|set(FIRST_FRAME_PCS)|set(FRAME2_TO_DMA_PCS)|set(DMA_TO_FRAME3_PCS)),
               io_rows=len(IO_ROWS)+len(IO_TABLE['values']),checked='--check' in sys.argv))
