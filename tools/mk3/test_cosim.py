"""M2 lots 6, 8, 9 and 10: native TMS34010 + DCS 8K ADSP-2105 + DMA blitter co-simulation (native/mk3/mk3_board.hpp) vs
the pinned Original.

One native run from reset under the MAME timeslice contract; every DCS host event comes from the native TMS writes
and sound-port reads, every DMA from the native register writes (mk3::Dma, graphics ROMs authenticated by roms.verify
and loaded by the native side). Compared with the Original (MAME debugger, read-only, from reset with the CMOS seed):
- TMS: PC, ST, cycles and 31 registers at each checkpoint up to the frontier (the first unobserved branch after the
  third frame that follows the first DMA, which must reject); every ordered write before TMS RLE_FROM in full;
  later writes as the breaks of the run "same address and value, 5 cycles after the previous write" plus count and
  last write (the watchdog writes of the delay loops); every ordered device read (address, value, cycle) in full.
- Host events: io[1] writes, sound-port writes and the sound-port read (dcs data_r), in order, cycle and value.
- Interrupts: every handler entry (breakpoints on the vector targets of the authenticated image): entry cycle, handler,
  the PC and ST the acceptance pushed, SP and ST after it (the DI in the EINT, ten DI at timeslice starts, TRAP 1).
- Scheduler: the ADSP registers each TMS instruction sees (symlist :dcs:dcs at the checkpoints and at every TMS
  instruction in SAMPLES: both early sound-port writes, command 03 E7 and its reply read, the DCS reset and release,
  commands 00 00 and 55 AA 64 9B, the boosted quanta and scanlines).
- ADSP: the same observations tools/mk3/test_adsp.py compares (window trace, extension rows, accesses, images, latch).
- DMA (second Original run, tools/mk3/reference_dma.py: Lua taps + debugger): per trigger up to the frontier, the trigger
  cycle, the 18 registers after the write (DMA_COMMAND bit 15 apart), the exact set of video RAM words changed since the
  previous trigger and the hash of the whole video RAM; every instruction boundary where (DMA_COMMAND & 0x8000) |
  (INTPEND & INT1) changes (DMA start and the done timer), with its PC.
Negative controls mutate one field each, or one scheduler parameter in the native run, and must be detected.
"""
import array,copy,json,os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import post_sound_pcs,reference,reference_dma,test_reset

ROOT=Path(__file__).resolve().parents[2]
RECEIPT=ROOT/'build/native/mk3-m2/cosim.json'
RLE_FROM=545200
# Inclusive TMS cycle windows sampled at every instruction (native/tests/mk3_cosim_tests.cpp kSamples). The first one is
# traced from the sound_wait checkpoint; the others come from a registerpoint.
SAMPLES=((545036,545600),(13045163,13045700),(13083100,13083400),(19398900,19399400),(19410900,19411400),(19621050,19621400),
         (19643900,19644500),(19650500,19650700),(19764380,19764700),(20795200,20795600))
SAMPLE_FIRST,SAMPLE_LAST=SAMPLES[0]
POINTS={'cmos_check':(0xff814b40,0),'pic_check':(0xffaeff00,0),'init_text':(0xffae8690,0),'serial':(0xffb096a0,0),
        'sound_wait':(0xffaa8990,0),'sound_wait2':(0xffaa8990,545037),'delay':(0xffae9930,0),'delay_end':(0xffae99d0,0),
        'sound_wait3':(0xffaa8990,600000),'dcs_read':(0xffae9c40,600000),'cmos_scan':(0xffadc240,13090000),
        'delay2':(0xffaeb2a0,13800000),'delay2_mid':(0xffaeb2a0,16600000),'dcs_reset':(0xffaa8a40,600000),
        'reset_release':(0xffaa8ac0,600000),'io_table':(0xff81a120,19000000),'command_00':(0xffaa8880,19600000),
        'command_55':(0xffaa8880,19640000),'eint':(0xff815070,0),'first_ie':(0xff81a8a0,0),'di_return':(0xff815080,0),
        'timer_handler_ie':(0xff81a8a0,19764455),'timer_return':(0xff928130,19764456),'trap1':(0xff8045e0,20795200),
        'first_dma':(0xff804640,20795274),'first_reti':(0xff8046e0,20795274),'fill':(0xff8052b0,20795274),
        # DI handler, second instruction (a breakpoint on the entry would hide the handler-entry breakpoint)
        'frame1_di':(0xff81a7e0,20906900),'frame3_di':(0xff81a7e0,21135390),
        # JRxx at 0xff9253c0 to 0xff9253d0, first reached by the Original at 21184790 (after post_sound_pcs segment 4).
        'frontier':(0xff9253c0,21184789)}
FRONTIER='MK3 unobserved branch; PC 4287779776; address 4287779776'
P=(1<<61)-1   # video RAM / graphics hashes (native/tests/mk3_cosim_tests.cpp Hash)
IE=0x00200000
HOST_KINDS=('io1','io1','dcs_w','dcs_r')   # mk3::HostEvent::Kind -> Original watchpoint
in_window=lambda cycles:any(a<=cycles<=b for a,b in SAMPLES)
NL='\\n'


def native():
    """Strict profile of the whole-image units (tools/mk3/generate.py), generated and built in the scratch tree."""
    from tools.mk3 import generate
    cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
    with q.scratch_tree() as (temp,cleanup):
        exe=temp/'mk3-cosim.exe';pc,cycle=POINTS['frontier']
        build=generate.build(temp,[ROOT/'native/tests/mk3_cosim_tests.cpp',ROOT/'native/mk3/mk3_adsp.cpp',*(ROOT/'native/mk3'/n for n in generate.RUNTIME),
                                   ROOT/'native/mk2/mk2_dcs.cpp',ROOT/'native/src/mk5_program.cpp'],exe,
                             defines=(f'-DFRONTIER_PC={pc:#x}u',f'-DFRONTIER_CYCLE={cycle}u'))
        assert build['passed'],q.compact(build)
        out=temp/'native.json'
        # Graphics ROMs: the project's manifest rows of the "video" region (authenticated by reference_dma.identities).
        (temp/'gfx.txt').write_text(''.join(f'{o} {s} {p}\n' for p,o,s in reference_dma.graphics_rows()),encoding='utf-8')
        run=q.command([exe,ROOT/'roms/mk3',reference.SEED,out,str(RLE_FROM),temp/'gfx.txt'],temp,cwd=ROOT,env=env,timeout=300);assert run['passed'],q.compact(run)
        data=json.loads(out.read_text('ascii'))
    assert not cleanup['exists_after']
    return data,build['wall_seconds'],run['wall_seconds']


def parse_extra(text):
    samples,rle,current,reads,host,irq=[],dict(breaks=[]),None,[],[],[]
    for line in text.splitlines():
        part=line.strip().split()
        if not part:continue
        if part[0]=='MK3_L':reads.append([int(part[1],16),int(part[2],16),int(part[3]),int(part[4])]);continue
        if part[0]=='MK3_H':host.append([part[1],int(part[2],16),int(part[3])]);continue
        if part[0]=='MK3_IRQ':irq.append([int(part[3]),int(part[1],16),int(part[6],16),int(part[5],16),int(part[4],16),int(part[2],16)]);continue
        if part[0]=='MK3_S':current=dict(name='',pc=int(part[1],16),cycles=int(part[2]),dcs={});samples.append(current)
        elif part[0]=='MK3_CPU':current=dict(name=part[1],pc=int(part[2],16),cycles=int(part[4]),dcs={});samples.append(current)
        elif part[0]=='MK3_K':rle['breaks'].append([int(part[1],16),int(part[2],16),int(part[3])])
        elif part[0]=='MK3_E':rle.update(count=int(part[1]),last=[int(part[2],16),int(part[3],16),int(part[4])])
        elif current is not None and len(part)>2 and part[1]=='=':current['dcs'][part[0]]=int(part[2],16)
    return dict(samples=samples,rle=rle,reads=reads,host=host,irq=irq)


def original():
    """TMS checkpoints, bus before RLE_FROM, run-length breaks after it, device reads and host events up to the frontier
    and the ADSP symbols each sampled TMS instruction sees; every handler entry with what the acceptance pushed."""
    from tools.mk3 import reference_video,roms
    handlers=sorted(set(reference_video.handlers(roms.program_image(ROOT/'roms/mk3',roms.definition())).values()))
    symbols='symlist :dcs:dcs'
    row=f'printf "MK3_S %X %d{NL}",pc,totalcycles;{symbols}'
    sample=f'trace cosim.tr,:maincpu,noloop,{{{row}}}'
    end=f'temp5=1;printf "MK3_E %d %X %X %d{NL}",temp0,temp1,temp2,temp3;quit'   # temp5 ends the run-length watch at the frontier
    points=[(name,pc,f'totalcycles>={cycle:x}',symbols,*((sample,) if name=='sound_wait' else (end,) if name=='frontier' else ()))
            for name,(pc,cycle) in POINTS.items()]
    run=(f'(temp4=(wpaddr!=temp1||wpdata!=temp2||totalcycles!=temp3+5)),(temp0=temp0+(totalcycles>={RLE_FROM:x}&&temp5==0)),'
         f'(temp1=wpaddr),(temp2=wpdata),(temp3=totalcycles),(temp4&&totalcycles>={RLE_FROM:x}&&temp5==0)')
    late=f'totalcycles>={RLE_FROM:x}&&temp5==0'
    extra=[f'wpset 0,ffffffff,w,({run}),{{printf "MK3_K %X %X %d{NL}",wpaddr,wpdata,totalcycles;g}}',
           f'bpset ffae9990,totalcycles>{SAMPLE_LAST:x},{{bpdisable {len(points)+1:x};trace off,:maincpu;g}}',
           *(f'wpset {base:x},{size:x},r,{late},{{printf "MK3_L %X %X %d %d{NL}",wpaddr,wpdata,totalcycles,wpsize;g}}'
             for base,size in reference.DEVICES+((0xc0000000,0x200),)),
           *(f'wpset {base:x},{size:x},{rw},temp5==0,{{printf "MK3_H {kind} %X %d{NL}",wpdata,totalcycles;g}}'
             for base,size,rw,kind in ((0x0187ff90,0x10,'w','io1'),(0x01680000,0x20,'w','dcs_w'),(0x01680000,0x20,'r','dcs_r'))),
           *(f'bpset {pc:x},temp5==0,{{printf "MK3_IRQ %X %X %d %X %X %X{NL}",pc,st,totalcycles,sp,d@sp,d@(sp+20);g}}' for pc in handlers),
           'rpset {'+'||'.join(f'(totalcycles>={a:x}&&totalcycles<={b:x})' for a,b in SAMPLES[1:])+'},{'+row+';g}']
    return reference.capture(points,RLE_FROM,seconds=4,extra=extra,extra_parse=parse_extra)


def sample_difference(nat,ref,fields,masks):
    """First difference between the ADSP state a TMS instruction sees natively and in the Original, or None.
    Native samples are per TMS cycle; a frozen ADSP (past its translation frontier) has nothing to compare."""
    by_cycle={s['cycles']:s for s in nat}
    compared=0
    for r in ref:   # a checkpoint inside a window is sampled twice (trace or registerpoint row, and breakpoint row)
        if not r['name'] and not in_window(r['cycles']):continue
        n=by_cycle.get(r['cycles'])
        if n is None or n['pc']!=r['pc'] or (r['name'] and n['name']!=r['name']):return f'sample at TMS {r["cycles"]}: native {n and (n["name"],n["pc"])} reference {(r["name"],r["pc"])}'
        if n['dcs_frozen']:continue
        compared+=1
        # Every field, also while IRQ2 is pending and not yet taken (check_irqs at the ADSP's next timeslice that runs).
        for name,value,mask in zip(fields,n['dcs'],masks):
            if name=='totalcycles':continue   # the debugger's ADSP totalcycles needs an ADSP hook
            if value&mask!=r['dcs'][name]&mask:return f'sample at TMS {r["cycles"]} {name}: native {value&mask:x} reference {r["dcs"][name]&mask:x}'
    if len(by_cycle)!=len(nat):return 'duplicate native sample cycle'
    expected=len({r['cycles'] for r in ref if r['name'] or in_window(r['cycles'])})
    return None if expected==len(nat) and compared else f'sample count: native {len(nat)} reference {expected} compared {compared}'


def tms_difference(tms,ref):
    """First difference between the native TMS run and the Original, or None."""
    named={s['name']:s for s in tms['samples'] if s['name']}
    if list(named)!=list(POINTS):return f'checkpoints {list(named)}'
    for name,s in named.items():
        cpu=ref['cpu'][name]
        if cpu['cycles']<=RLE_FROM:   # registers, ST, cycles and every write/read before the checkpoint
            trace=dict(s,writes=tms['writes'][:s['writes']],reads=tms['reads'][:s['reads']])
            if (d:=test_reset.compare(trace,ref,name)):return d
        else:
            for key in ('pc','status','cycles','registers'):
                if s[key]!=cpu[key]:return f'{name} {key}: native {s[key]} reference {cpu[key]}'
    bus=[row for row in ref['bus'] if row[0]=='W']
    if [w[1:] for w in tms['writes']]!=[r[2:5] for r in bus]:return f'writes before TMS {RLE_FROM}: native {len(tms["writes"])} reference {len(bus)}'
    if tms['rle']!=ref['extra']['rle']:return f'run-length writes: native {tms["rle"]} reference {ref["extra"]["rle"]}'
    reads=[r[2:5] for r in ref['bus'] if r[0]=='R']+[r[:3] for r in ref['extra']['reads']]
    if [r[1:] for r in tms['reads']]!=reads:return f'device reads: native {len(tms["reads"])} reference {len(reads)}'
    if any(r[3]!=16 for r in ref['extra']['reads']):return 'non-word device read'
    host=[[HOST_KINDS[e[0]],e[3],e[1]] for e in tms['host_events']]
    expected=[[kind,value&0xff if kind=='dcs_w' else value,cycle] for kind,value,cycle in ref['extra']['host']]   # sound_w: low byte
    if host!=expected:return f'host events: native {host} reference {expected}'
    if (d:=interrupt_difference(tms['interrupts'],ref['extra']['irq'])):return d
    # The frontier instruction (not run by the Original, which stops at it) rejects before any effect.
    if tms['frontier_writes']:return f'frontier writes {tms["frontier_writes"]}'
    # The frontier branch executes alone after the run and must reject; the ADSP must still be inside its translation.
    if tms['frontier']!=FRONTIER or tms['dcs_frontier'] or tms['pc']!=ref['cpu']['frontier']['pc'] or tms['cycles']!=ref['cpu']['frontier']['cycles']:
        return f'frontier: {tms["frontier"]} / {tms["dcs_frontier"]} at {tms["pc"]:x} cycle {tms["cycles"]}'
    return None


def dma_states(dref,end):
    """Original (DMA_COMMAND & 0x8000) | (INTPEND & INT1) changes [boundary, state, pc] up to the boundary `end`."""
    out,state=[],0
    for s in dref['states']:
        if s['boundary']>end:break
        if s['state']!=state:out.append([s['boundary'],s['state'],s['pc']]);state=s['state']
    return out


def dma_difference(tms,dref,end=POINTS['frontier'][1]):
    """First difference between the native DMA observations and the Original's up to the frontier, or None."""
    trig=[t for t in dref['triggers'] if dref['writes'][t['write']]['cycle']<end]
    nat=tms['dma_triggers']
    if len(nat)!=len(trig) or not trig:return f'DMA triggers: native {len(nat)} reference {len(trig)}'
    vram=array.array('H',bytes(2*524288))
    for k,(n,t) in enumerate(zip(nat,trig)):
        w=dref['writes'][t['write']];cycle,regs,flat,digest=n
        if cycle!=w['cycle']:return f'DMA trigger {k}: native cycle {cycle} reference {w["cycle"]}'
        # Registers after the write; bit 15 of DMA_COMMAND (the done timer) is compared at the boundaries.
        expected=list(t['registers']);expected[1]=(expected[1]&~w['mask']|w['data']&w['mask'])&0xffff
        if [r&(0x7fff if i==1 else 0xffff) for i,r in enumerate(regs)]!=[r&(0x7fff if i==1 else 0xffff) for i,r in enumerate(expected)]:
            return f'DMA trigger {k} at {cycle}: native registers {[hex(x) for x in regs]} reference {[hex(x) for x in expected]}'
        old={i:vram[i] for i in (*t['pre'],*t['post'])}
        for i,v in t['pre'].items():vram[i]=v
        for i,v in t['post'].items():vram[i]=v
        delta={i:vram[i] for i in old if vram[i]!=old[i]}
        got=dict(zip(flat[::2],flat[1::2]))
        if got!=delta:
            diff=sorted(set(got.items())^set(delta.items()))[:3]
            return f'DMA trigger {k} ({w["data"]:#x} at {cycle}): video RAM change of {len(got)} words differs from the Original\'s {len(delta)}; first {[(hex(i),hex(v)) for i,v in diff]}'
        if digest!=int.from_bytes(vram.tobytes(),'little')%P:return f'DMA trigger {k}: native video RAM hash differs from the Original'
    want=dma_states(dref,end)
    if tms['dma_states']!=want:
        first=next((i for i,(a,b) in enumerate(zip(tms['dma_states'],want)) if a!=b),min(len(want),len(tms['dma_states'])))
        return f'DMA boundary change {first}: native {tms["dma_states"][first:first+1]} reference {want[first:first+1]} (native {len(tms["dma_states"])}, reference {len(want)})'
    return None


def interrupt_difference(nat,ref):
    """Handler entries: native [entry, vector, handler, pushed PC, pushed ST, SP] vs Original [entry, handler, pushed PC,
    pushed ST, SP, ST at entry]; every entry (interrupt or TRAP) leaves ST = 0x10."""
    got=[[n[0],n[2],n[3],n[4],n[5],0x10] for n in nat]
    return None if got==ref and ref else f'handler entries: native {[[hex(x) for x in r] for r in got]} reference {[[hex(x) for x in r] for r in ref]}'


def checkpoint_difference(tms,ref):
    """Checkpoint state only (for the samples-only scheduler controls)."""
    named={s['name']:s for s in tms['samples'] if s['name']}
    for name,cpu in ref['cpu'].items():
        s=named.get(name)
        if s is None or any(s[k]!=cpu[k] for k in ('pc','status','cycles','registers')):return name
    return interrupt_difference(tms['interrupts'],ref['extra']['irq'])


class Cosimulation(unittest.TestCase):
    def test_native_cosimulation_equals_original(self):
        from tools.mk3 import generate,reference_dcs,roms,test_adsp
        nat,build_s,run_s=native()
        ref=original()
        dcs=reference_dcs.capture()
        dref=reference_dma.capture(4)
        tms=nat['tms'];masks=test_adsp.masks(nat['fields'])
        self.assertEqual(nat['graphics_hash'],int.from_bytes(reference_dma.graphics_image(),'little')%P,'native graphics image')
        self.assertIsNone(tms_difference(tms,ref))
        self.assertIsNone(dma_difference(tms,dref))
        self.assertIsNone(sample_difference(tms['samples'],ref['extra']['samples'],nat['fields'],masks))
        # Host events: the Original's io[1] (0x0187ff90) and sound-port writes, in order, are the native events (here within
        # the 1 s ADSP capture; tms_difference compares all of them up to the frontier with the TMS capture's watchpoints).
        hosts=[h for h in dcs['host'] if h['kind']!='status']
        self.assertEqual([(e[0]==2,e[1],e[3]) for e in tms['host_events'] if e[1]<6250000],
                         [(h['kind']=='dcs_w',h['totalcycles'],h['value']&(0xff if h['kind']=='dcs_w' else 0xffff)) for h in hosts])
        # ADSP: test_adsp.py's comparison, with the latch the native TMS read at its three early status reads.
        latch=[[r[3],r[2]&0x0fff] for r in tms['reads'] if r[1]==0x0187ffc0 and r[3]<0x7b0]
        adsp=dict(fields=nat['fields'],window=nat['window'],extension=nat['extension'],latch_at=latch)
        self.assertEqual(len(latch),3)
        self.assertIsNone(test_adsp.compare(adsp,dcs))
        negatives={}
        def mutate(label,f,check=lambda t:tms_difference(t,ref)):
            changed=copy.deepcopy(tms);f(changed);negatives[label]=check(changed) is not None
        sample=lambda t,name:next(s for s in t['samples'] if s['name']==name)
        samples=lambda t:sample_difference(t['samples'],ref['extra']['samples'],nat['fields'],masks)
        cntr=nat['fields'].index('cntr')
        mutate('delay_register',lambda t:sample(t,'delay')['registers'].__setitem__(1,1))
        mutate('wait2_status',lambda t:sample(t,'sound_wait2').__setitem__('status',sample(t,'sound_wait2')['status']^0x20000000))
        mutate('delay_cycles',lambda t:sample(t,'delay').__setitem__('cycles',545108))
        mutate('wait3_register',lambda t:sample(t,'sound_wait3')['registers'].__setitem__(3,0x3e6))
        mutate('frontier_cycles',lambda t:t.__setitem__('cycles',t['cycles']+5))
        mutate('frontier_message',lambda t:t.__setitem__('frontier','none'))
        mutate('adsp_frontier',lambda t:t.__setitem__('dcs_frontier','MK3 ADSP DCS reset with the autobuffer timer running is not verified'))
        mutate('sound_write_value',lambda t:next(w for w in t['writes'] if w[1]==0x01680000).__setitem__(2,1))
        mutate('sound_write_cycle',lambda t:[w for w in t['writes'] if w[1]==0x01680000][1].__setitem__(3,545077))
        mutate('sound_write_missing',lambda t:t['writes'].remove(next(w for w in t['writes'] if w[1]==0x01680000)))
        early_read=lambda t:[r for r in t['reads'] if r[3]<RLE_FROM][-1]
        mutate('status_read_value',lambda t:early_read(t).__setitem__(2,0x0400))
        mutate('status_read_cycle',lambda t:early_read(t).__setitem__(3,545063))
        mutate('watchdog_count',lambda t:t['rle'].__setitem__('count',t['rle']['count']-1))
        mutate('watchdog_break',lambda t:t['rle']['breaks'].insert(0,[0x0187ffb0,0xff90,RLE_FROM+6]))
        mutate('delay_end_write',lambda t:t['rle']['breaks'][0].__setitem__(2,t['rle']['breaks'][0][2]+1))
        # A pending IRQ2 entered early (at the host event instead of the next ADSP timeslice): the sample sees the vector.
        pending=[r['cycles'] for r in ref['extra']['samples'] if r['dcs']['irq2'] and r['dcs']['imask']&0x20 and r['dcs']['pc']!=4]
        self.assertTrue(pending,'a sample with IRQ2 pending and not yet taken')
        mutate('sample_irq2_entered_early',lambda t:next(s for s in t['samples'] if s['cycles']==pending[0])['dcs'].__setitem__(0,4),samples)
        mutate('sample_adsp_cntr',lambda t:sample(t,'sound_wait2')['dcs'].__setitem__(cntr,sample(t,'sound_wait2')['dcs'][cntr]+1),samples)
        window=lambda t,k:[s for s in t['samples'] if SAMPLES[k][0]<=s['cycles']<=SAMPLES[k][1]]
        mutate('sample_adsp_pc',lambda t:window(t,0)[-20]['dcs'].__setitem__(0,0x46),samples)
        mutate('sample_missing',lambda t:t['samples'].pop(len(t['samples'])//2),samples)
        # Lot 8: command 03 E7, its reply read, CMOS checks, the DCS reset, the third init, commands 00 00 / 55 AA 64 9B, EINT.
        data_read=lambda t:next(r for r in t['reads'] if r[1]==0x01680000)
        event=lambda t,kind,value:next(e for e in t['host_events'] if e[0]==kind and e[3]==value)
        mutate('dcs_read_register',lambda t:sample(t,'dcs_read')['registers'].__setitem__(1,sample(t,'dcs_read')['registers'][1]^1))
        mutate('delay2_cycles',lambda t:sample(t,'delay2_mid').__setitem__('cycles',sample(t,'delay2_mid')['cycles']+1))
        mutate('reset_release_register',lambda t:sample(t,'reset_release')['registers'].__setitem__(0,0x30))
        mutate('eint_status',lambda t:sample(t,'eint').__setitem__('status',sample(t,'eint')['status']^0x20000000))
        mutate('data_read_value',lambda t:data_read(t).__setitem__(2,2))
        mutate('data_read_cycle',lambda t:data_read(t).__setitem__(3,data_read(t)[3]+1))
        mutate('intenb_read_value',lambda t:next(r for r in t['reads'] if r[1]==0xc0000110).__setitem__(2,0))
        mutate('late_read_missing',lambda t:t['reads'].pop())
        mutate('late_break_value',lambda t:next(b for b in t['rle']['breaks'] if b[0]==0x0187ff90).__setitem__(1,0x20))
        mutate('late_break_missing',lambda t:t['rle']['breaks'].pop(len(t['rle']['breaks'])//2))
        mutate('host_read_value',lambda t:event(t,3,1).__setitem__(3,2))
        mutate('host_read_missing',lambda t:t['host_events'].remove(event(t,3,1)))
        mutate('host_reset_cycle',lambda t:[e for e in t['host_events'] if e[0]==0][-1].__setitem__(1,19398913))
        mutate('host_command_order',lambda t:t['host_events'].__setitem__(slice(-4,-2),t['host_events'][-3:-5:-1]))
        mutate('sample_read_window',lambda t:window(t,2)[len(window(t,2))//2]['dcs'].__setitem__(0,0x46),samples)
        mutate('sample_reset_window',lambda t:window(t,4)[-1]['dcs'].__setitem__(cntr,window(t,4)[-1]['dcs'][cntr]+1),samples)
        mutate('sample_command_window',lambda t:window(t,6)[-1]['dcs'].__setitem__(0,0x46),samples)
        # Lot 9: interrupts. Acceptance one cycle later; pushed ST with IE flipped; pushed PC of the EINT acceptance;
        # handler checkpoints; a missing handler entry; DPYINT one line later / earlier inside the native run.
        timer=lambda t:t['interrupts'][1]
        mutate('accept_one_cycle_late',lambda t:timer(t).__setitem__(0,timer(t)[0]+1))
        mutate('pushed_status_ie',lambda t:timer(t).__setitem__(4,timer(t)[4]^IE))
        mutate('eint_pushed_pc',lambda t:t['interrupts'][0].__setitem__(3,t['interrupts'][0][3]+16))
        mutate('handler_ie_status',lambda t:sample(t,'timer_handler_ie').__setitem__('status',sample(t,'timer_handler_ie')['status']^IE))
        mutate('trap_entry_missing',lambda t:t['interrupts'].pop())
        mutate('handler_register',lambda t:sample(t,'first_ie')['registers'].__setitem__(15,sample(t,'first_ie')['registers'][15]+32))
        negatives['dpyint_one_line_late']=checkpoint_difference(nat['dpyint_late_tms'],ref) is not None
        negatives['dpyint_one_line_early']=checkpoint_difference(nat['dpyint_early_tms'],ref) is not None
        # Scheduler parameters changed inside the native run: a 600 ns boosted quantum; sound-port writes applied 100 ns late.
        negatives['boost_quantum_600ns']=sample_difference(nat['boost_tms']['samples'],ref['extra']['samples'],nat['fields'],masks) is not None
        negatives['sound_write_100ns_late']=test_adsp.compare(dict(adsp,extension=nat['skew_extension']),dcs) is not None
        # HSTCTLH / DMA_COMMAND writes without their TMS input-line synchronize() (third init, TMS 19411059-19411229).
        negatives['input_line_sync_missing']=(checkpoint_difference(nat['no_sync_tms'],ref) is not None or
            sample_difference(nat['no_sync_tms']['samples'],ref['extra']['samples'],nat['fields'],masks) is not None)
        # Lot 10: DMA. One pixel, one register, the VRAM hash, a missing trigger, a done boundary one cycle off (outputs);
        # every done time +-1 cycle and the first DMA clipped to its first row (native runs).
        dmutate=lambda label,f:mutate(label,f,lambda t:dma_difference(t,dref))
        dmutate('dma_pixel',lambda t:t['dma_triggers'][1][2].__setitem__(1,t['dma_triggers'][1][2][1]^1))
        dmutate('dma_register',lambda t:t['dma_triggers'][2][1].__setitem__(8,t['dma_triggers'][2][1][8]^0x100))
        dmutate('dma_vram_hash',lambda t:t['dma_triggers'][-1].__setitem__(3,t['dma_triggers'][-1][3]^1))
        dmutate('dma_trigger_missing',lambda t:t['dma_triggers'].pop(len(t['dma_triggers'])//2))
        dmutate('dma_done_boundary',lambda t:t['dma_states'][1].__setitem__(0,t['dma_states'][1][0]+1))
        late=lambda run:(dma_difference(dict(nat[run],dma_triggers=tms['dma_triggers']),dref) or checkpoint_difference(nat[run],ref))
        negatives['done_plus_1_cycle']=late('done_late_tms') is not None
        negatives['done_minus_1_cycle']=late('done_early_tms') is not None
        clipped=dma_difference(dict(nat['clip_tms']),dref)
        negatives['clip_register']=clipped is not None and 'video RAM' in clipped
        def mutate_adsp(label,f):
            changed=copy.deepcopy(adsp);f(changed);negatives[label]=test_adsp.compare(changed,dcs) is not None
        mutate_adsp('adsp_window_row',lambda n:n['window']['rows'][100].__setitem__(7,n['window']['rows'][100][7]^1))
        mutate_adsp('adsp_irq_entry',lambda n:n['extension']['rows'][next(i for i,r in enumerate(n['extension']['rows']) if r[1]==0x176)].__setitem__(2,1))
        mutate_adsp('adsp_access',lambda n:n['extension']['accesses'][-2].__setitem__(5,2))
        mutate_adsp('latch_at_read',lambda n:n['latch_at'][0].__setitem__(1,0x0400))
        self.assertTrue(all(negatives.values()),negatives)
        named={s['name']:s for s in tms['samples'] if s['name']}
        live=[s for s in tms['samples'] if not s['dcs_frozen']]
        RECEIPT.parent.mkdir(parents=True,exist_ok=True)
        RECEIPT.write_text(json.dumps(dict(passed=True,
            scope='TMS: reset 0xff8148b0 -> first unobserved branch 0xff9253c0 at TMS 21184789 (after the third frame that follows '
                  'the first DMA), through the first EINT (DI taken inside it), the DI at timeslice starts, the TRAP 1 display-list '
                  'handler and every DMA of the scope (mk3::Dma), with the DCS co-simulated '
                  'throughout (commands 00 00, 03 E7 + reply read, reset/reboot, 00 00, 55 AA 64 9B); ADSP observations '
                  'compared in full: power-on to its bank-1 entry (boot 3, PC 0); after that, the samples seen by the TMS',
            identities=dict(program_sha256=ref['program_sha256'],core_sha256=ref['core_sha256'],seed_sha256=ref['seed_sha256'],debugger=ref['debugger']),
            frontier=dict(tms=tms['frontier'],tms_pc=hex(tms['pc']),tms_cycle=tms['cycles'],adsp=tms['dcs_frontier']),
            compared=dict(tms_instructions=tms['instructions'],
                          checkpoints={n:dict(pc=hex(s['pc']),cycles=s['cycles'],instructions=s['instructions']) for n,s in named.items()},
                          checkpoint_fields='PC, ST, totalcycles, A0-A14, SP, B0-B14',
                          writes_in_full=len(tms['writes']),writes_run_length=tms['rle']['count'],run_length_breaks=len(tms['rle']['breaks']),
                          device_reads=len(tms['reads']),host_events=len(tms['host_events']),handler_entries=len(tms['interrupts']),
                          dma=dict(triggers=len(tms['dma_triggers']),commands={hex(c):sum(1 for d in tms['dma_triggers'] if d[1][1]&0x7fff==c&0x7fff) for c in (0xc002,0xc082,0x800c)},
                                   video_ram_words_changed=sum(len(d[2])//2 for d in tms['dma_triggers']),full_video_ram_hashes=len(tms['dma_triggers']),
                                   status_int1_boundary_changes=len(tms['dma_states']),graphics=dict(sha256=dref['graphics_sha256'],loaded_bytes=dref['graphics_loaded_bytes'])),
                          scheduler_samples=dict(total=len(tms['samples']),with_live_adsp=len(live),irq2_pending_not_taken=len(pending),adsp_fields_each=len(nat['fields'])-1,
                                                 every_tms_instruction=SAMPLES),
                          adsp=dict(window_instructions=len(dcs['trace']),fields_per_instruction=len(dcs['fields']),
                                    extension_instruction_rows=len(dcs['rows']),extension_accesses=len(nat['extension']['accesses']),
                                    pm_words=len(nat['extension']['pm']),dm_words=len(nat['extension']['dm']),core_resets=nat['extension']['core_resets'])),
            handler_entries=[dict(entry_cycle=i[0],vector=hex(i[1]),handler=hex(i[2]),pushed_pc=hex(i[3]),pushed_status=hex(i[4]),sp=hex(i[5])) for i in tms['interrupts']],
            host_events=[dict(kind=['assert','release','data','read'][e[0]],tms_write=e[1],tms_end=e[2],value=e[3],adsp_ns_when_applied=e[4]) for e in tms['host_events']],
            first_divergence=None,negative_controls=negatives,
            timings_seconds=dict(native_build=build_s,native_run=run_s,reference_tms=ref['wall_seconds'],reference_adsp=dcs['wall_seconds'],reference_dma=dref['wall_seconds']),
            assumptions='Timers: synchronize callbacks (DCS host writes, and the TMS input-line changes of HSTCTLH / DMA_COMMAND writes), TMS34010 scanline timer, screen VBLANK begin/end and scanline 0, 50 Hz sound update; '
                        'no other timer of the pinned sources is armed in this scope. The scanline and DMA-done timers are those of mk3::VideoTiming. '
                        'Interrupts are taken at TMS timeslice starts and inside EINT/POPST/PUTST/RETI; one inside an INTENB write rejects (none in scope). '
                        'The INT1 line drops at the DMA_COMMAND write (MAME applies it at the synchronize() that ends the timeslice: '
                        'no instruction in between); dma_done clears bit 15 and raises INT1 at the timer (INT1 is never taken in scope). '
                        'The DMA blitter (unscaled 0xc002/0xc082/0x800c) is mk3::Dma, verified in isolation by tools/mk3/test_dma.py. '
                        'A pending ADSP IRQ2 is taken by check_irqs at the next ADSP timeslice that runs (Dcs8k return_at_sync); samples compare every field. '
                        'PIXBLT B,XY runs to completion (no DCS access inside). ADSP debugger totalcycles is not sampled from the TMS side. '
                        'The data_r auto-ack is not observable in this scope (no status read before the DCS reset empties the latch). '
                        'The sound-port read happens with the output latch full (data_r eat_cycles on an empty latch rejects, not translated). '
                        'Between the samples, ADSP state after its bank-1 entry is compared only through the TMS-visible effects '
                        '(latch reads, the reply value, the TMS path).',
            cleanup=dict(tms=ref['cleanup'],adsp=dcs['cleanup'],dma=dref['cleanup'])),indent=1)+'\n',encoding='utf-8')


if __name__=='__main__':unittest.main()
