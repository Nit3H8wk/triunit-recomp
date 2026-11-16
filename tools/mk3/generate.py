"""Offline MK3 2.1 AOT translation of the whole TMS34010 program image (J1, plan 2026-11-10-mk3-jogavel-acelerado.md).

One aligned scan of the authenticated image (tools/mk2/offline_decode.scan_aligned) feeds a static closure from the 32
vectors, every measured PC below (SLICES, EXTERNAL_PCS) and the ROM pointer candidates (aligned 32-bit constants that
point at a decodable program instruction), with the MK2 architectural dispatch: CALL/JUMP/EXGPC/RETS/RETI compute
their destination at run time and enter the PC dispatcher; a PC outside the candidate rejects with its PC.
Verified = the measured PCs, emitted exactly as the measured-only build did. Profile::Strict keeps that build's
observable behaviour (unobserved direct branch and unverified entry reject); Profile::Game runs the translated
candidate and logs first executions (mk3_profile.hpp). An instruction form without translated semantics rejects
in both profiles. Output: C++ units per 0x80000-bit PC range plus a page dispatcher; no runtime opcode decoding.
"""
from collections import Counter
from pathlib import Path
import argparse,hashlib,json,os,re,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk2.offline_decode import BASE,END,scan_aligned
from tools.mk2 import generate_video_irq as emitter,static_batch
from tools.mk3 import roms,post_sound_pcs
from tools.setup import mk3 as setup_mk3
ROOT=Path(__file__).resolve().parents[2]
# Lots 1-2: Original reached PCs from the reset vector to the CALLA of the CMOS routine (test_reset.py compares every
# register, write and device read of this slice with the pinned MAME from its own reset).
RESET_END=0xffadaf40
RESET_PCS=tuple(int(x,16) for x in '''
ff8148b0 ff8148c0 ff8148d0 ff8148e0 ff814910 ff814930 ff814960 ff814990 ff8149a0 ff8149d0 ff8149f0 ff814a20 ff814a40
ff814a50 ff814a70 ff814aa0 ff814ad0 ff814ae0 ff814af0 ff814b10'''.split())
# Original reached PCs from the CMOS routine entry (CALLA at 0xff814b10) to its return, measured with the
# pinned MAME debugger trace from reset with the factory CMOS seed (tools/mk3/generate.py --help).
CMOS_END=0xff814b40
CMOS_PCS=(0xffadaf40,)+tuple(int(x,16) for x in '''
ffada5e0 ffada600 ffada620 ffada650 ffada670 ffada680 ffada6b0 ffada6d0 ffada6e0 ffada700 ffada720 ffada740 ffada760
ffada770 ffada7a0 ffada7b0 ffada7c0 ffada7d0 ffada800 ffada820 ffada840 ffada870 ffada880 ffada8a0 ffada8b0 ffada8d0
ffada8f0 ffada910 ffada920 ffada950 ffada970 ffada980 ffada9a0 ffada9c0 ffada9f0 ffadaa00 ffadaa20 ffadaa40 ffadaa50
ffadaa70 ffadaa90 ffadaae0 ffadab00 ffadab20 ffadab50 ffadab60 ffadab80 ffadab90 ffadabb0 ffadabd0 ffadabf0 ffadac00
ffadac30 ffadac50 ffadae30 ffadae50 ffadae60 ffadae90 ffadaea0 ffadaec0 ffadaed0 ffadaef0 ffadaf10 ffadaf30 ffadaf60
ffadaf70 ffadaf90 ffadafb0 ffadb950 ffadb960 ffadb980 ffadb9a0 ffadb9d0 ffadb9f0 ffadba00 ffadc230 ffadc240 ffadc250
ffadc280 ffadc290 ffadc2c0 ffadc2d0 ffadc2e0 ffadc300 ffadc320 ffadc330 ffadc340 ffadc360 ffadc380 ffadc390 ffadc3c0
ffadc3d0 ffadc3f0 ffadc420 ffadc430 ffadc450 ffadc460 ffadc480 ffadc4a0 ffadc4b0 ffadc4c0 ffadc4e0 ffadc500 ffadc510
ffadc540 ffadc550 ffadc570 ffadc5a0 ffadc5b0 ffadc5d0 ffadc640 ffadc660 ffadc680 ffadc690 ffadc6b0 ffadc6c0 ffadc6d0
ffadc6f0 ffadc700 ffadc720 ffadc740 ffadc750 ffadc770 ffadc790 ffadc7a0 ffadc7c0 ffadc7d0 ffadc7e0 ffadc800 ffadc810
ffadc830 ffadc850'''.split())

# Lot 4: CMOS return 0xff814b40 (watchdog write, PIC handshake 0xffb09110, JA to the main init) up to the
# first DMA register write at 0xffaeff00, measured the same way.
PIC_END=0xffaeff00
PIC_PCS=tuple(int(x,16) for x in '''
ff814b40 ff814b70 ff814ba0 ffaefe90 ffaefea0 ffaefeb0 ffaefec0 ffaefef0 ffb09110 ffb09120 ffb09150 ffb09170 ffb09180
ffb091a0 ffb091d0 ffb091f0 ffb09220 ffb09250 ffb09280 ffb09290 ffb092e0 ffb09300 ffb09330 ffb09360 ffb09390 ffb093a0
ffb093f0'''.split())
# Lot 5a: 0xffaeff00 (DMA latches, second reset path, RAM clear, TMS34010 I/O table, DMA/video/palette setup,
# VRAM clear, text setup) up to the first PIXBLT B,XY at 0xffae8690. Shared routines already emitted by an
# earlier slice (the PIC handshake) are not emitted twice.
INIT_END=0xffae8690
INIT_PCS=tuple(int(x,16) for x in '''
ff814bd0 ff814be0 ff814bf0 ff814c00 ff814c30 ff814c40 ff814c70 ff814ca0 ff814cd0 ff814d00 ff814d30 ff814d60 ff814d90
ff814db0 ff8193e0 ff819400 ff819410 ff819440 ff819470 ff819480 ff819490 ff81a060 ff81a080 ff81a0b0 ff81a0e0 ff81a110
ff81a120 ff81a130 ff81a150 ffae84a0 ffae84c0 ffae84e0 ffae84f0 ffae8500 ffae8530 ffae8540 ffae8550 ffae8560 ffae8570
ffae8580 ffae8590 ffae85a0 ffae85d0 ffae85e0 ffae85f0 ffae8600 ffae8610 ffae8620 ffae8630 ffae8640 ffae8650 ffae8660
ffae8670 ffae8680 ffae8790 ffae87a0 ffae87b0 ffae87c0 ffae87d0 ffae87e0 ffae87f0 ffae8800 ffae8830 ffae8840 ffae8850
ffae8860 ffae8870 ffae8880 ffae8890 ffae88a0 ffae88b0 ffae88c0 ffae88d0 ffae88e0 ffae88f0 ffae8900 ffae8910 ffae8920
ffae8940 ffae8950 ffae8960 ffae9280 ffae9290 ffae92b0 ffae92e0 ffae92f0 ffae9300 ffae9400 ffae9410 ffae9420 ffae9450
ffae9480 ffae94a0 ffae94d0 ffae9500 ffae9510 ffae9540 ffae9550 ffae9580 ffae9590 ffae95c0 ffae95f0 ffae9600 ffae9630
ffae9640 ffae9660 ffae9690 ffaeb300 ffaeb310 ffaeb340 ffaeb370 ffaeb3a0 ffaeb3d0 ffaeb3e0 ffaeb3f0 ffaeb400 ffaeb410
ffaeb440 ffaeb470 ffaeb4a0 ffaeb4d0 ffaec380 ffaec390 ffaec3a0 ffaec3d0 ffaec400 ffaec430 ffaec440 ffaec470 ffaeff00
ffaeff30 ffaeff60 ffaeff90 ffaeffb0 ffaeffe0 ffaf0010 ffaf0040 ffaf0070 ffaf0080 ffaf0090 ffaf00b0 ffaf00d0 ffaf0100
ffaf0130 ffb09110 ffb09120 ffb09150 ffb09170 ffb09180 ffb091a0 ffb091d0 ffb091f0 ffb09220 ffb09250 ffb09280 ffb09290
ffb092e0 ffb09300 ffb09330 ffb09360 ffb09390 ffb093a0 ffb093f0'''.split())
SLICES={'Reset to CMOS check':(RESET_PCS,RESET_END),'CMOS check':(CMOS_PCS,CMOS_END),'PIC check':(PIC_PCS,PIC_END),
        'Init to text':(INIT_PCS,INIT_END),
        # Lot 5b: after each PIXBLT (handled by the runtime, not emitted) to the PIC serial-data clock at 0xffb096a0.
        'Text to serial':(tuple(int(x,16) for x in '''
ffae8560 ffae8570 ffae8580 ffae8590 ffae85a0 ffae85d0 ffae85e0 ffae85f0 ffae8600 ffae8610 ffae8620 ffae8630 ffae8640
ffae8650 ffae8660 ffae8670 ffae8680 ffae86a0 ffae86b0 ffae86c0 ffae8730 ffae8740 ffae8750 ffae8760 ffae8770 ffae8780
ffae96a0 ffb095e0 ffb095f0 ffb09600 ffb09610 ffb09640 ffb09650 ffb09680 ffb09690'''.split()),0xffb096a0),
        # Lot 5c: PIC serial number clock-out (16 bytes), checks and display setup, up to the first DCS wait at 0xffaa8990.
        'Serial to sound':(tuple(int(x,16) for x in '''
ffaa87c0 ffaa87e0 ffaa8810 ffaa8820 ffaa8830 ffaa8840 ffaa8850 ffaa8960 ffae84a0 ffae84c0 ffae84e0 ffae84f0 ffae8500
ffae8530 ffae8540 ffae8550 ffae8560 ffae8570 ffae8580 ffae8590 ffae85a0 ffae85d0 ffae85e0 ffae85f0 ffae8600 ffae8610
ffae8620 ffae8630 ffae8640 ffae8650 ffae8660 ffae8670 ffae8680 ffae8690 ffae86a0 ffae86b0 ffae86c0 ffae8730 ffae8740
ffae8750 ffae8760 ffae8770 ffae8780 ffae8790 ffae87a0 ffae87b0 ffae87c0 ffae87d0 ffae87e0 ffae87f0 ffae8800 ffae8830
ffae8840 ffae8850 ffae8860 ffae8870 ffae8880 ffae8890 ffae88a0 ffae88b0 ffae88c0 ffae88d0 ffae88e0 ffae88f0 ffae8900
ffae8910 ffae8920 ffae8940 ffae8950 ffae8960 ffae96c0 ffae96f0 ffae9720 ffae9730 ffae9760 ffae9770 ffae9790 ffae97c0
ffae97d0 ffae9800 ffae9830 ffae9850 ffae9860 ffae9880 ffae9890 ffae98b0 ffae98c0 ffae98e0 ffae98f0 ffae9900 ffb09400
ffb09410 ffb09440 ffb09450 ffb09460 ffb09470 ffb09480 ffb09490 ffb094a0 ffb094b0 ffb094c0 ffb094d0 ffb094e0 ffb094f0
ffb09500 ffb09510 ffb09520 ffb09530 ffb09540 ffb09570 ffb09580 ffb09590 ffb095a0 ffb095b0 ffb095c0 ffb095d0 ffb09680
ffb09690 ffb096a0 ffb096d0 ffb09700 ffb09710 ffb09730 ffb09760 ffb09790 ffb097b0 ffb097c0 ffb097d0 ffb097e0 ffb09810
ffb09820 ffb09830 ffb09840 ffb09870 ffb098a0 ffb098b0 ffb098d0 ffb09900 ffb09930 ffb09950 ffb09960 ffb09970 ffb09990
ffb099a0 ffb099b0 ffb099c0 ffb099f0 ffb09a10 ffb09a20 ffb09a30 ffb09a40 ffb09a50 ffb09a80 ffb09a90 ffb09ab0 ffb09ad0
ffb09ae0 ffb09af0 ffb09b20 ffb09b30 ffb09b40 ffb09b50 ffb09b60 ffb09b90 ffb09bc0 ffb09be0 ffb09bf0 ffb09c00 ffb09c10
ffb09c40 ffb09c70 ffb09c80 ffb09c90 ffb09cc0 ffb09ce0 ffb09cf0 ffb09d20 ffb09d40 ffb09d50 ffb09d60 ffb09d70 ffb09d80
ffb09db0 ffb09dc0 ffb09dd0 ffb09e00 ffb09e30 ffb09e40 ffb09e50 ffb09e60 ffb09e70 ffb09ea0 ffb09ed0 ffb09ef0 ffb09f00
ffb09f10 ffb09f20 ffb09f50 ffb09f80 ffb09f90 ffb09fa0 ffb09fb0 ffb09fe0 ffb0a010 ffb0a020 ffb0a030 ffb0a040 ffb0a060
ffb0a090 ffb0a0a0 ffb0a0d0 ffb0a0f0 ffb0a100 ffb0a110 ffb0a120 ffb0a130 ffb0a140 ffb0a150 ffb0a180 ffb0a190 ffb0a1a0
ffb0a1b0 ffb0a1e0 ffb0a210 ffb0a220 ffb0a230 ffb0a240 ffb0a250 ffb0a280 ffb0a2b0 ffb0a2c0 ffb0a2d0 ffb0a2e0 ffb0a2f0
ffb0a320 ffb0a350 ffb0a360 ffb0a370 ffb0a380 ffb0a3a0 ffb0a3d0 ffb0a3e0 ffb0a3f0 ffb0a400 ffb0a410 ffb0a440 ffb0a470
ffb0a480 ffb0a4b0 ffb0a4c0 ffb0a4f0 ffb0a500 ffb0a510 ffb0a520 ffb0a530 ffb0a540 ffb0a550 ffb0a560 ffb0a570 ffb0a580
ffb0a590 ffb0a5a0 ffb0a5b0 ffb0a5c0 ffb0a5d0 ffb0a5e0 ffb0a5f0 ffb0a600 ffb0a630 ffb0a640 ffb0a670 ffb0a680 ffb0a6b0
ffb0a6c0 ffb0a6d0 ffb0a6e0 ffb0a6f0 ffb0a700 ffb0a710 ffb0a720 ffb0a750 ffb0a760 ffb0a770 ffb0a790 ffb0a7f0 ffb0a800
ffb0a810 ffb0a830 ffb0a860 ffb0a870 ffb0a880 ffb0a8a0 ffb0a8d0 ffb0a8e0 ffb0a8f0 ffb0a900 ffb0a910 ffb0a940 ffb0a950
ffb0a960 ffb0a980 ffb0a990 ffb0a9b0 ffb0a9c0 ffb0a9d0 ffb0a9f0 ffb0aa20 ffb0aa30 ffb0aa50 ffb0aa60 ffb0aa90 ffb0aaa0
ffb0aab0 ffb0aad0 ffb0aae0 ffb0aaf0 ffb0ab20'''.split()),0xffaa8990),
        # Lot 6: DCS wait (MOVB @187FFC4h), sound command 0x0000 (two sound-port bytes), the 2,500,000-iteration watchdog
        # delay and the call for command 0x03E7, up to its DCS wait at 0xffaa8990 (TMS cycle 13045163). The not-taken
        # JRN (DCS input latch still full) was not reached and rejects.
        'Sound command to delay':(tuple(int(x,16) for x in '''
ffaa87c0 ffaa87e0 ffaa8810 ffaa8820 ffaa8830 ffaa8840 ffaa8850 ffaa8870 ffaa8880 ffaa88b0 ffaa88c0 ffaa88d0 ffaa88f0
ffaa8920 ffaa8940 ffaa8960 ffaa8990 ffaa89c0 ffaa89f0 ffae9930 ffae9960 ffae9990 ffae99c0 ffae99d0 ffae99e0 ffae9a10
ffae9a30'''.split()),0xffaa8990),
        # Lot 8: the measured PCs from the first DCS wait to the first EINT (tools/mk3/post_sound_pcs.py segment 0):
        # command 0x03E7 and its reply read, CMOS checks, the DCS reset, the third init and commands 00 00, 55 AA 64 9B.
        # The EINT at 0xff815070 is emitted and rejects (interrupts are not translated yet).
        'Sound wait to EINT':(post_sound_pcs.WAIT_TO_EINT_PCS+(post_sound_pcs.EINT_PC,),post_sound_pcs.EINT_PC),
        # Lot 9: the first DI handler (taken inside the EINT), its RETI to 0xff815080 and the main line of the first frame,
        # up to the second DI, taken at a timeslice start in the loop 0xff928130-0xff928140 (post_sound_pcs segment 2).
        'First frame':(post_sound_pcs.FIRST_FRAME_PCS,post_sound_pcs.FRONTIERS['first_timer_interrupt']['pushed_pc']),
        # Lot 9: frames 2-10 (nine more DI at timeslice starts) and the TRAP 1 into 0xff8045d0 up to the first DMA trigger
        # (post_sound_pcs segment 3), plus the trigger instruction itself.
        'Frames to DMA':(post_sound_pcs.FRAME2_TO_DMA_PCS+(post_sound_pcs.FRONTIERS['first_dma']['pc'],),post_sound_pcs.FRONTIERS['first_dma']['pc']+16),
        # Lot 10: from the first DMA trigger (the blitter runs in mk3::Dma) to the third DI after it (post_sound_pcs segment 4):
        # the TRAP 1 display-list handler, the 0x800c fills from the MMTM at 0xff8052b0 and the frame wait loop.
        'DMA to frame 3':(post_sound_pcs.DMA_TO_FRAME3_PCS,post_sound_pcs.FRONTIERS['frame3_after_dma']['handler'])}
# PCs executed by runtime helpers instead of emitted blocks (still qualified as branch/fallthrough targets).
EXTERNAL_PCS={0xffae8690}


TRACE_ROOTS=(ROOT/'tools/mk3/attract_trace_roots.json',ROOT/'tools/mk3/fight_trace_roots.json')   # J2 attract, J3 reset -> round start
PROGRAM=dict(sha256=json.loads(roms.MANIFEST.read_text('utf-8'))['program_sha256'],size=(END-BASE)//8,base=BASE)
UNIT_BITS=0x80000   # one C++ unit per 64 KB of program image (MK2 static batch: 16 units)
# The pinned MAME execution table (34010tbl.hxx, tms34010_device::s_opcode_table, op >> 4): the decoder prints a mnemonic
# for some reserved encodings that MAME runs as unimpl (a 1-cycle no-op, m_pc + 16), e.g. 0x0f50 "PIXBLT XY,L", 0xdf80
# "LINE 1", 0x0d70 "EINT". Every emitted form follows this table, not the disassembly.
OPCODES=re.findall(r'&tms34010_device::(\w+)',(ROOT/'docs/investigation/decoder-research/upstream/34010tbl.hxx')
                   .read_text('utf-8').split('tms34020_device::opcode_func')[0])
assert len(OPCODES)==4096
def handler(raw):return OPCODES[raw[0]>>4]
def reserved(row):return handler(row[2])=='unimpl' and not row[3].startswith(('DW','EMU'))   # DW/EMU stay data rejections
# Route-verified keys (decision 1): written by the route engine (front B); absent = empty set. Refused when it names
# another program image, a malformed key, a receipt whose bytes differ from its digest, or a TMS block outside the candidate.
ROUTES=ROOT/'tools/mk3/route_verified.json'
KINDS=('TmsBlock','TmsEdge','AdspBlock','AdspEdge','DmaPath','IrqPath','DevicePath')   # mk3::Unverified order
def route_keys(path=None):
    path=Path(path or ROUTES)
    if not path.is_file():return dict(schema=None,keys={k:set() for k in KINDS},routes=0,receipts_present=0)
    data=json.loads(path.read_text('utf-8'))
    if data.get('schema')!='mk3-route-verified/1':raise ValueError('route_verified.json: unknown schema')
    if data.get('program_sha256')!=PROGRAM['sha256']:raise ValueError('route_verified.json names another program image')
    present=0
    for route in data.get('routes',[]):
        receipt=ROOT/route['receipt']
        if receipt.is_file():
            if hashlib.sha256(receipt.read_bytes()).hexdigest()!=route['receipt_sha256']:raise ValueError('route receipt differs from its digest: '+route['receipt'])
            present+=1
    keys={}
    for kind in KINDS:
        pairs=data.get(kind,[])
        if not all(isinstance(x,list) and len(x)==2 and all(isinstance(v,int) and not isinstance(v,bool) and 0<=v<2**32 for v in x) for x in pairs):
            raise ValueError('route_verified.json: malformed '+kind)
        keys[kind]={tuple(x) for x in pairs}
    return dict(schema=data['schema'],keys=keys,routes=len(data.get('routes',[])),receipts_present=present)

def verified():
    """Measured PC -> (slice, end) of the first slice listing it, as the measured-only build emitted it."""
    owner={}
    for name,(pcs,end) in SLICES.items():
        for pc in pcs:
            if pc not in EXTERNAL_PCS:owner.setdefault(pc,(name,end))
    return owner

def emit(pc,size,asm,raw,qualified,end,rom=None,edge=None,batch=False):
    """MK2 emitter, plus MK3-local forms it does not cover (semantics from the pinned 34010ops.hxx)."""
    op,*rest=asm.split(None,1);args=rest[0].split(',') if rest else []
    if op=='TRAP' and size==16:  # TRAP n: handler from the vector 0xffffffe0-0x20n of the authenticated image; 16 cycles.
        n=raw[0]&31;vector=0xffffffe0-(n<<5);target=int.from_bytes(rom[(vector-0xff800000)//8:][:4],'little')&~15
        if target not in qualified:raise ValueError(f'Unqualified TRAP {n} at {pc:08x}: {target:08x}')
        return f"o.Trap({n},{emitter.constant(pc+size)});"
    if op=='MODU' and size==16:  # MODU Rs,Rd: Rd = Rd % Rs (unsigned); Z from the result, V on a zero divisor; 35 cycles.
        return f"o.ModuloUnsigned({emitter.register(args[0])},{emitter.register(args[1])},{emitter.constant(pc+size)});"
    code=emitter.emit_instruction(pc,size,asm,raw,qualified,{},end=end,batch_forms=batch,unverified=edge)
    return code.replace('throw std::runtime_error("MK2 video IRQ unobserved branch");',f'o.Reject("unobserved branch",{emitter.constant(pc)});')

def trace_roots(rows):
    """Original route-trace PCs and destinations outside the static closure (TRACE_ROOTS: J2 attract, J3 reset -> round start);
    candidate roots only, not verified."""
    roots={int(x,16) for path in TRACE_ROOTS for x in json.loads(path.read_text('utf-8'))['roots'].split()}
    bad=[f'{pc:08x}' for pc in sorted(roots) if pc not in rows or not rows[pc][0] or rows[pc][3].startswith('DW')]
    if bad:raise ValueError('Route trace roots outside decodable code: '+' '.join(bad[:8]))
    return roots

def continuations(rows,graph):
    """J2: software-stack return addresses. GETPC Rd (Rd = address of the next instruction, 34010ops.hxx getpc) followed
    by ADDI K,Rd (IW sign-extended, IL whole) inside the closure: Rd = that address + K, pushed and later jumped to
    Candidate roots only; non-code targets are dropped."""
    out=set()
    for pc in graph:
        m=re.fullmatch(r'GETPC +([AB]\d+|SP)',rows[pc][3])
        n=pc+rows[pc][0]
        if not m or n not in rows:continue
        size,_,_,asm=rows[n]
        k=re.fullmatch(r'ADDI +([0-9A-F]+)h,'+m[1],asm)
        if not k:continue
        value=int(k[1],16)
        if size==32:value=((value&0xffff)^0x8000)-0x8000
        t=(n+value)&0xffffffff
        if t in rows and rows[t][0] and not rows[t][3].startswith('DW'):out.add(t)
    return out

# K2: inline-parameter call (k2-stops.json, class "inline-parameter call FF97EF90"). FF97EF90 pops its return address
# (MMFM SP,A5), reads a long and a word after the call (MOVE *A5+,A0,1; MOVE *A5+,A3,0) and returns by JUMP A5 to the
# return address + 0x30 bits, or by JUMP A6 through the 8 longs at FF992160 (CMPI 7h,A6; JRLS; CLR A6).
INLINE_CALLS={0xff97ef90:(0x30,0xff992160,8)}

def inline_calls(rom,rows,graph):
    """Continuations of INLINE_CALLS reached in `graph`: every CALLR/CALLA of the image to the routine (found by
    scanning all decoded positions) whose call site is in the closure, plus the table targets from the ROM. Candidate
    roots only, not verified; non-code targets are dropped."""
    out=set()
    for routine,(skip,table,count) in INLINE_CALLS.items():
        if routine not in graph:continue
        sites=[pc for pc,(size,_,_,asm) in rows.items() if size and re.fullmatch(rf'CALL[AR] +{routine:X}h',asm)]
        out|={pc+rows[pc][0]+skip for pc in sites if pc in graph}
        out|={int.from_bytes(rom[(table-BASE)//8+4*k:(table-BASE)//8+4*k+4],'little') for k in range(count)}
    return {t for t in out if t in rows and rows[t][0] and not rows[t][3].startswith('DW')}

def closures(rom,rows,measured):
    """Static closures (tools/mk2/static_batch.tms_graph): from the vectors and `measured`, then also from the pointer
    candidates and the attract-trace roots. TRAP n continuations (outside the MK2 CFG for n != 1) are added as roots
    until each closure is stable."""
    pointers={int.from_bytes(rom[n:n+4],'little') for n in range(0,len(rom)-3,2)}
    pointers={pc for pc in pointers if pc in rows and rows[pc][0] and not rows[pc][3].startswith('DW')}
    def closure(roots):
        roots=set(roots)
        while True:
            graph,_,_,open_edges=static_batch.tms_graph(rom,rows,reader_roots=sorted(roots),program=PROGRAM)
            more={pc+rows[pc][0] for pc in graph if rows[pc][3].startswith('TRAP ')}|continuations(rows,graph)|inline_calls(rom,rows,graph)
            more|={pc+16 for pc in graph if reserved(rows[pc]) and pc+16 in rows and rows[pc+16][0] and not rows[pc+16][3].startswith('DW')}
            more-=graph.keys()
            if not more:return graph,open_edges
            roots|=more
    return closure(measured),closure(measured|pointers|trace_roots(rows)),pointers

def units(rom,rows,routes=None):
    """C++ sources {name: text} and a compact receipt; one case per candidate PC (module docstring). routes: a
    route_verified.json path (default ROUTES)."""
    started=time.perf_counter();route=route_keys(routes)
    owner=verified();measured=set(owner)|EXTERNAL_PCS
    (static,_),(graph,open_edges),pointers=closures(rom,rows,measured)
    candidate=set(graph)|measured;analysed=time.perf_counter()
    blocks={};states=Counter();pending=Counter();examples={}
    for pc in sorted(candidate-EXTERNAL_PCS):
        size,_,raw,asm=rows[pc];op=asm.split()[0]
        if pc in owner:   # measured: the measured-only emission; direct branches into the candidate become checked edges
            edge=lambda t,pc=pc,size=size:(f'o.Edge({emitter.constant(t)},{emitter.constant(pc)},{int(t==pc+size)}); '
                                           if t in candidate else None)
            code=emit(pc,size,asm,raw,measured,owner[pc][1],rom,edge);states['verified_lot']+=1
        else:
            try:
                code=emit_unverified(pc,size,asm,raw,candidate,rom)
                states['verified_route' if (pc,0) in route['keys']['TmsBlock'] else 'unverified_translated']+=1
                if reserved(rows[pc]):states['reserved_opcode_noop']+=1   # subset of the two above
            except ValueError as error:
                code=f'o.Reject("untranslated TMS form",{emitter.constant(pc)});';states['unverified_untranslated']+=1
                key=form(asm);pending[key]+=1;examples.setdefault(key,f'{pc:08x} {error}')
            code=f'o.Block({emitter.constant(pc)}); '+code
        blocks[pc]=f'case 0x{pc:08x}u: {{ // {asm}\n    {code}\n    break;\n}}\n'
    outside={k for k in route['keys']['TmsBlock'] if k[0] not in candidate or k[1]}
    if outside:raise ValueError('route_verified.json: TmsBlock outside the static candidate: '+' '.join(f'{a:08x}' for a,_ in sorted(outside)[:8]))
    sources=partition(blocks,route['keys'])
    sites=Counter(rows[pc][3].split()[0] for pc in graph if rows[pc][3].split()[0] in ('CALL','JUMP','EXGPC','RETS','RETI'))
    exchanges={pc for pc in graph if rows[pc][3].startswith('EXGPC') and len(graph[pc])>1}
    receipt=dict(positions=len(rows),measured_pcs=len(measured),candidate_pcs=len(candidate),
        reachable_from_vectors_and_measured=len(set(static)|measured),
        only_by_pointer_candidates_or_trace_roots=len(candidate-set(static)-measured),pointer_candidates=len(pointers),
        route_trace_roots=len(trace_roots(rows)),
        cases=dict(states),pending_forms=dict(pending.most_common()),pending_examples=examples,
        computed_sites=dict(sites),computed_sites_without_static_destination=dict(
            JUMP=sites['JUMP'],CALL=sites['CALL'],EXGPC=sites['EXGPC']-len(exchanges),
            note='RETS/RETI return to pushed continuations (CALL/TRAP successors and interrupted PCs); JUMP/CALL/EXGPC '
                 'register destinations have no static evidence besides MOVI->EXGPC exchanges'),
        immediate_exchanges=len(exchanges),open_edges={k:len(v) for k,v in sorted(open_edges.items())},
        units=sum(n.startswith('mk3_tms_unit_') for n in sources),
        route_verified=dict(schema=route['schema'],routes=route['routes'],receipts_present=route['receipts_present'],
                            keys={k:len(v) for k,v in route['keys'].items()}),
        analysis_seconds=round(analysed-started,3),generation_seconds=round(time.perf_counter()-analysed,3))
    return sources,receipt

def form(asm):
    """Pending-form key: mnemonic and operand shape (registers -> R, constants -> K)."""
    op,*rest=asm.split(None,1)
    shape=re.sub(r'\b[0-9A-F]+h\b','K',re.sub(r'\b(?:[AB](?:1[0-5]|[0-9])|SP)\b','R',rest[0])) if rest else ''
    return (op+' '+shape).strip()

def emit_unverified(pc,size,asm,raw,candidate,rom):
    code=family(pc,size,asm,raw,candidate)
    if code is None:code=emit(pc,size,asm,raw,candidate,-1,rom,batch=True)
    code=code.replace(f'o.Reject("unobserved branch",{emitter.constant(pc)});',f'o.Reject("branch outside the static candidate",{emitter.constant(pc)});')
    unknown=set(re.findall(r'\bo\.(\w+)\(',code))-OPS
    if unknown:raise ValueError('Ops lacks '+','.join(sorted(unknown)))
    return code

def family(pc,size,asm,raw,candidate):
    """MK3 forms of the unverified candidate that the MK2 emitter lacks or translates for MK2 contexts only (34010ops.hxx
    at the pinned commit). None: the MK2 emitter with its batch forms. Every form here is covered by test_families.py."""
    op,*rest=asm.split(None,1);args=rest[0].split(',') if rest else []
    nxt=emitter.constant(pc+size);r=emitter.register
    h=handler(raw)
    if h=='unimpl' and not asm.startswith(('DW','EMU')):return f'o.Reserved({emitter.constant(pc+16)});'
    graphics={'pixblt_l_l':'Blit(true,true,','pixblt_l_xy':'Blit(true,false,','pixblt_xy_l':'Blit(false,true,',
              'pixblt_xy_xy':'Blit(false,false,','pixblt_b_l':'BlitBinary(true,','pixblt_b_xy':'BlitBinary(false,',
              'fill_l':'Fill(true,','line':f"Line({'true' if raw[0]&0x80 else 'false'},"}
    if h in graphics and size==16:return f'o.{graphics[h]}{nxt});'
    if size==16 and op in ('MPYS','MPYU','DIVU') and len(args)==2 and args[1]=='SP':   # Rd = SP, register 15 of both files
        return f"o.{dict(MPYS='MultiplySigned',MPYU='MultiplyUnsigned',DIVU='DivideUnsigned')[op]}({r(args[0])},15,false,{nxt});"
    if op in ('CALLA','JA') and size==48 and emitter.transfer_target(op,args[0]) not in candidate:
        # destination outside the program image (data pointer candidates): explicit boundary before the branch, as for
        # the conditional branches outside the candidate
        return f'o.Reject("branch outside the static candidate",{emitter.constant(pc)});'
    if size==16 and op in ('SLA','SRA','SRL') and len(args)==2 and not args[0].endswith('h'):
        # SLA_R: count Rs & 31; SRA_R/SRL_R: count (-Rs) & 31 (2's complement field, as the K forms are encoded).
        count=f'({r(args[0])}&31)' if op=='SLA' else f'((0u-{r(args[0])})&31)'
        if op=='SRL':return f'o.Shift({r(args[1])},{count},true,{nxt});'
        return f"o.ShiftArithmetic({r(args[1])},{count},{'true' if op=='SRA' else 'false'},{nxt});"
    if size==16 and op=='DIVS' and len(args)==2 and args[1]!='SP' and not int(args[1][1:])&1:
        return f"o.DivideSigned({r(args[0])},{int(args[1][1:])},{'true' if args[1][0]=='B' else 'false'},{nxt});"
    if size==16 and op in ('MODS','CPW') and len(args)==2:
        return f"o.{'ModuloSigned' if op=='MODS' else 'CompareWindow'}({r(args[0])},{r(args[1])},{nxt});"
    if size==16 and op=='NEGB' and len(args)==1:return f'o.NegateBorrow({r(args[0])},{nxt});'
    if size==16 and op=='PIXT':
        shape=tuple('XY' if a=='XY' else '*' if a.startswith('*') else 'R' for a in args)
        regs=[r(a.lstrip('*')) for a in args if a!='XY']
        return {('R','*'):lambda s,d:f'o.PixelStore({d},{s},{nxt},2);',
                ('R','*','XY'):lambda s,d:f'o.WriteXYPixel({d},{s},{nxt});',
                ('*','R'):lambda s,d:f'o.PixelLoad(o.ReadPixel({s}),{d},{nxt},4);',
                ('*','*'):lambda s,d:f'o.PixelStore({d},o.ReadPixel({s}),{nxt},4);',
                ('*','XY','R'):lambda s,d:f'o.PixelLoad(o.ReadPixel(o.XYToLinear({s},true)),{d},{nxt},6);',
                ('*','XY','*','XY'):lambda s,d:f'o.CopyXYPixel({s},{d},{nxt});'}[shape](*regs)
    if op=='MOVB' and len(args)==2 and all(a.startswith(('*','@')) for a in args):
        (source,pre,post,kind),(target,pre2,post2,kind2)=emitter.memory(args[0],0),emitter.memory(args[1],0)
        cost={('offset','offset',48):5,('absolute','absolute',80):6}.get((kind,kind2,size))
        if cost and not (pre or post or pre2 or post2):   # MOVB_NO_NO, MOVB_AA (the indirect pair is the MK2 emitter's)
            return f'const uint32_t value=o.Read8({source}); o.WriteByte({target},value); o.Finish({nxt},{cost});'
    if op=='MOVE' and size==48 and len(args)==2 and args[0].startswith('@') and raw[0]&0xffe0==0x07e0:
        # MOVB_AR (0x07e0-0x07ff): the pinned disassembler prints it as MOVE @L,Rd; Rd sign-extended byte, NZ, V clear.
        dest=('B' if raw[0]&0x10 else 'A')+str(raw[0]&15)
        if args[1]!=dest and not (dest[1:]=='15' and args[1]=='SP'):raise ValueError('MOVB @L,Rd register differs from its opcode')
        return f'o.Load({r(args[1])},uint32_t(int32_t(int8_t(o.Read8({emitter.constant(emitter.immediate(args[0][1:]))})))),{nxt},5);'
    return None

# mk3::Ops members generated code may call (native/mk3/mk3_cpu.hpp); any other call is an untranslated form.
OPS={'Finish','Zero','Load','Clear','Arithmetic','Shift','MultiplyUnsigned','DivideUnsigned','ModuloUnsigned','FieldWidth',
     'LeadingOne','AddCarry','ShiftArithmetic','SignExtend','Rotate','SubtractXY','AddXY','MoveX','ReadField','WriteField',
     'WriteByte','Read8','Read16','Read32','Call','ReturnSubroutine','ReturnInterrupt','PushStatus','PopStatus','PutStatus',
     'InterruptEnable','Trap','SetField','Mmtm','Mmfm','Reject','Edge','Block','SubtractBorrow','NegateBorrow','Absolute',
     'MultiplySigned','DivideSignedSingle','DivideSigned','ModuloSigned','ExchangeField','XYToLinear','ConvertXY',
     'CompareWindow','ReadPixel','PixelStore','PixelLoad','WriteXYPixel','CopyXYPixel','DrawAdvance','FillXY','Fill','BlitBinary',
     'Blit','Line','Reserved'}

def partition(blocks,routes=None):
    """Pages of 256 PC slots, one function each (as tools/mk2/generate_architectural.partition), in units per range."""
    header=f'// Generated offline by tools/mk3/generate.py; do not hand edit.\n// MK3 rev 2.1 program SHA256 {PROGRAM["sha256"]}\n'
    pages={}
    for pc,block in sorted(blocks.items()):pages.setdefault(pc>>12,[]).append(block)
    bodies={};dispatch=[]
    for page,entries in sorted(pages.items()):
        bodies.setdefault(f'mk3_tms_unit_{(page<<12)&~(UNIT_BITS-1):08x}.cpp',[]).append(
            f'bool TmsPage_{page:x}(Ops& o) {{\n    [[maybe_unused]] auto& s = o.s;\n    switch (s.pc) {{\n'
            +''.join(entries)+'    default: return false;\n    }\n    return true;\n}\n')
        dispatch.append(f'    case 0x{page:x}u: return TmsPage_{page:x}(o);\n')
    sources={name:header+'#include "mk3_cpu.hpp"\nnamespace mk3 {\n'+''.join(body)+'}\n' for name,body in bodies.items()}
    sources['mk3_tms_dispatch.cpp']=(header+'#include "mk3_cpu.hpp"\nnamespace mk3 {\n'
        +''.join(f'bool TmsPage_{p:x}(Ops&);\n' for p in sorted(pages))
        +'bool StepTranslated(Ops& o) {\n    switch (o.s.pc >> 12) {\n'+''.join(dispatch)+'    default: return false;\n    }\n}\n'
        +'// tools/mk3/route_verified.json keys {kind, id, from} (mk3_profile.hpp RouteVerified)\n'
        +'const RouteVerified& RouteVerifiedSet() {\n    static const RouteVerified set{{\n'
        +''.join(f'        {{{n},0x{a:08x}u,0x{b:08x}u}},\n' for n,kind in enumerate(KINDS) for a,b in sorted((routes or {}).get(kind,())))
        +'    }};\n    return set;\n}\n}\n')
    return sources

def scan(rom):
    """The single decoder run of a generation: every aligned position of the authenticated image."""
    return scan_aligned(rom,PROGRAM)

def write(directory,rom,rows=None):
    """Writes the units into `directory` (a test's own scratch tree); returns their paths and the receipt."""
    if rows is None:rows,_=scan(rom)
    text,receipt=units(rom,rows);paths=[]
    for name,source in text.items():
        path=Path(directory)/name;path.write_text(source,encoding='utf-8',newline='\n');paths.append(path)
    return paths,receipt

# Native test/driver build of the units: same flags as the earlier single-command builds, separate compilation in two
# workers with the project's single bounded object cache (tools/quality/cpp_build.py, build/native/compiler-cache).
FLAGS=['-std=c++17','-O2','-Wall','-Wextra','-Werror','-static','-municode']
RUNTIME=('mk3_program.cpp','mk3_dcs.cpp','mk3_cmos_check.cpp','mk3_pic.cpp')

def build(scratch,sources,executable,*,defines=(),rows=None,timeout=1800,unicode=True):
    """Writes the units into `scratch` and links them with `sources` (the driver plus its runtime files). Returns the
    cpp_build result with the generation receipt under 'generation'."""
    from tools.quality import cpp_build
    rom=roms.program_image(ROOT/'roms/mk3',roms.definition())
    started=time.perf_counter()
    if rows is None:rows,proof=scan(rom)
    else:proof=None
    units,receipt=write(scratch,rom,rows)
    receipt['scan']=proof and {k:proof[k] for k in ('positions','truncated','compile_seconds','decode_seconds')}
    receipt['wall_seconds']=round(time.perf_counter()-started,3)
    cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
    result=cpp_build.build(cc,[*(f for f in FLAGS if unicode or f!='-municode'),*defines,'-I'+str(ROOT/'native/include'),'-I'+str(ROOT/'native/mk3'),'-I'+str(ROOT/'native/mk2'),setup_mk3.include()],
                           [*sources,*units],['-lbcrypt'],executable,scratch,env=env,timeout=timeout,compile_from_scratch=True)
    result['generation']=receipt
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true',help='generate twice from one scan and require identical units; '
                        'with a recorded units_sha256 in build/native/mk3-m2/j1-tms.json, require that digest too')
    a=parser.parse_args()
    rom=roms.program_image(ROOT/'roms/mk3',roms.definition());rows,proof=scan(rom)
    sources,receipt=units(rom,rows)
    digest=lambda src:hashlib.sha256(''.join(f'{n}|{len(t)}|{t}' for n,t in sorted(src.items())).encode()).hexdigest()
    receipt['units_sha256']=digest(sources)
    if a.check:
        if digest(units(rom,rows)[0])!=receipt['units_sha256']:raise SystemExit('MK3 TMS generation is not deterministic')
        recorded=ROOT/'build/native/mk3-m2/j1-tms.json'
        want=json.loads(recorded.read_text('utf-8')).get('units_sha256') if recorded.is_file() else None
        if want and want!=receipt['units_sha256']:raise SystemExit('MK3 TMS units differ from the recorded J1 candidate')
    print(json.dumps(dict(receipt,scan={k:proof[k] for k in ('positions','truncated','compile_seconds','decode_seconds')}),indent=1))
