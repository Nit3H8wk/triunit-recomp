"""M2 video/IRQ lot: isolated TMS34010 video timing model (native/mk3/mk3_video.hpp) vs the pinned Original.

Declared stimulus (from the Original, reset to SECONDS emulated seconds, tools/mk3/reference_video.py): every
main-CPU write to its I/O registers and every DMA_COMMAND write with the DMA size registers at that write,
each at its instruction-start cycle plus the cycles that instruction had already counted (MMTM/MMFM). Compared against the Original: every I/O register value the game read;
the debugger samples of HCOUNT, VCOUNT, DPYADR and INTPEND taken at every logged access; and every interrupt
acceptance: the vector, and the boundary. For an acceptance at a timeslice start the model's timer event must
fall in (start of the last instruction before it, its end]; an acceptance inside EINT/POPST/PUTST/RETI or an
INTENB write must already be selectable with the state at that instruction. Handler entries made by a TRAP
instruction (TRAP 1 shares the INT1 vector) are recognised by opcode and timing and are not interrupts. The interrupted PC and the pushed
ST are Original data (the model has no CPU). Negative controls must each be detected.
"""
import json,os,subprocess,sys,unittest
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import reference_video,roms

ROOT=Path(__file__).resolve().parents[2]
RECEIPT=ROOT/'build/native/mk3-m2/video-irq.json'
SECONDS=4
IO=0xc0000000
NAMES='HESYNC HEBLNK HSBLNK HTOTAL VESYNC VEBLNK VSBLNK VTOTAL DPYCTL DPYSTRT DPYINT CONTROL HSTDATA HSTADRL HSTADRH HSTCTLL HSTCTLH INTENB INTPEND CONVSP CONVDP PSIZE PMASK R23 R24 R25 R26 DPYTAP HCOUNT VCOUNT DPYADR REFCNT'.split()
# midtunit_v.cpp:701-705 register_map and midtunit_v.h:89-106 register numbers.
DMA_MAP=((0,1,2,3,4,5,6,7,8,9,10,11,16,17,14,15),(0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15))
# Read-only sample windows around the DPYINT line timer (T = k frames, 18,279,250 ns each) of eight frames:
# the INTPEND read reports DI early when the timer is less than from_hz(40000000/8/3) away (tms34010.cpp:1582).
PROBES=[(k*18279250//160-8,k*18279250//160+2) for k in range(175,183)]
CHECKPOINTS={0x0d60:'EINT',0x01c0:'POPST',0x0940:'RETI'}  # plus PUTST 0x01a0-0x01bf; SET_ST -> check_interrupt

def events(ref):
    """-> (event lines, expectations in output order). Rows keep the debugger log order within a cycle."""
    rows=sorted([(r[4],0,i,'io',r) for i,r in enumerate(ref['io'])]+[(r[4],0,i,'dma',r) for i,r in enumerate(ref['dma'])]+
                [(r['temps'][0],1,i,'irq',r) for i,r in enumerate(ref['irq'])],key=lambda r:r[:3])
    # The log interleaves I/O and DMA rows of one instruction; both lists are in log order and one instruction
    # never touches both devices, so ordering by (cycle, list order) is the log order.
    lines,expect,dma=[],[],[0]*18
    for cycle,_,_,kind,r in rows:
        if kind=='irq':
            lines.append(f"I {cycle} {r['cycles']-16} {r['pushed_status']}");expect.append(('irq',r));continue
        lines.append(f'S {cycle} {r[9]}');expect.append(('sample',r))
        if r[0]=='S':continue
        if kind=='io':
            reg=(r[2]-IO)>>4
            if r[0]=='W':lines.append(f'W {cycle} {reg} {r[3]}')
            else:lines.append(f'R {cycle} {r[9]} {reg}');expect.append(('read',r))
        else:
            number=DMA_MAP[dma[15]>>5&1][r[2]>>4&15];dma[number]=r[3]
            if number==1:
                offset=0 if r[3]&15==12 else dma[2]|dma[3]<<16  # midtunit_v.cpp:750-767, m_gfx_rom_large (l.74)
                if offset>=0xf8000000:offset-=0xf8000000
                lines.append(f'D {cycle} {r[9]} {r[3]} {dma[6]} {dma[7]} {dma[10]} {dma[11]} {int(offset<0x10000000)}')
    return lines,expect

def native(build,runs):
    """runs: [(event lines, pixel_hz)] -> output lines per run."""
    cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']};out=[]
    with q.scratch_tree() as (temp,cleanup):
        exe=temp/'mk3-video.exe'
        made=q.command([cc,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-static','-I'+str(ROOT/'native/mk3'),
                        ROOT/'native/tests/mk3_video_tests.cpp','-o',exe],temp,cwd=ROOT,env=env,timeout=180)
        assert made['passed'],q.compact(made);build['seconds']=made['wall_seconds']
        for i,(lines,hz) in enumerate(runs):
            (temp/f'e{i}.txt').write_text('\n'.join(lines)+'\n',encoding='ascii')
            with (temp/f'o{i}.txt').open('wb') as sink:  # stdout exceeds the shared capture limit
                code=subprocess.run([str(exe),str(temp/f'e{i}.txt'),str(hz)],stdout=sink,env=dict(os.environ,**env),timeout=120).returncode
            assert code==0,f'native replay exit {code}'
            out.append((temp/f'o{i}.txt').read_text('ascii').splitlines())
    assert not cleanup['exists_after']
    return out

def compare(ref,expect,out,rom):
    """-> (first difference or None, statistics)."""
    stats=dict(reads=Counter(),samples=0,irq=Counter(),model_di_events=0,model_int1_events=0,early_di_samples=0,line_273_samples_without_di=0)
    vector={ref['handlers'][name]:reference_video.VECTORS[name] for name in ('INT2','INT1','DI')}
    writes={(r[4],(r[2]-IO)>>4) for r in ref['io'] if r[0]=='W'}
    if len(out)!=len(expect):return f'{len(out)} native lines for {len(expect)} expectations; last: {out[-1] if out else None}',stats
    for (kind,r),line in zip(expect,out):
        if line.startswith('REJECT'):return line,stats
        got=[int(x) for x in line.split()]
        if kind=='sample':
            if r[6]==273:stats['early_di_samples' if r[8]&0x400 else 'line_273_samples_without_di']+=1
            if got!=r[5:9]:return f'sample at cycle {r[4]} pc {r[1]:x}: native HCOUNT/VCOUNT/DPYADR/INTPEND {got} reference {r[5:9]}',stats
            stats['samples']+=1
        elif kind=='read':
            name=NAMES[(r[2]-IO)>>4]
            if got!=[r[3]]:return f'{name} read at cycle {r[4]} pc {r[1]:x}: native {got[0]:#x} reference {r[3]:#x}',stats
            stats['reads'][name]+=1
        else:
            before,after,di_n,di_c,int1_n,int1_c=got;start,_,pc,_=r['temps'];boundary=r['cycles']-16
            want=vector.get(r['handler']);name='DI' if want==reference_video.VECTORS['DI'] else 'INT1' if want==reference_video.VECTORS['INT1'] else hex(r['handler'])
            stats['model_di_events'],stats['model_int1_events']=di_n,int1_n
            word=int.from_bytes(rom[(pc-0xff800000)//8:][:2],'little')
            if word&0xffe0==0x0900 and start==boundary:  # TRAP n: 16 cycles, vector 0xffffffe0 - 0x20*n (34010ops.hxx:1895-1906); not an interrupt
                target=int.from_bytes(rom[(0xffffffe0-0x20*(word&31)-0xff800000)//8:][:4],'little')&0xfffffff0
                if target!=r['handler']:return f"TRAP {word&31} at {pc:x} entered {r['handler']:x}, vector holds {target:x}",stats
                stats['irq'][f'software TRAP {word&31} (not an interrupt)']+=1;continue
            where=f"{name} accepted at boundary {boundary} (handler entry {r['cycles']}, interrupted pc {r['pushed_pc']:x})"
            if before==0:
                event=di_c if name=='DI' else int1_c
                if after!=want:return f'{where}: native vector {after:#x} reference {want and hex(want)}',stats
                if not start<event<=boundary:return f'{where}: native timer event at cycle {event}, outside ({start}, {boundary}]',stats
                stats['irq'][name+' at timer boundary']+=1
            else:
                point=CHECKPOINTS.get(word) or ('PUTST' if word&0xffe0==0x01a0 else 'INTENB write' if (start,17) in writes else None)
                if not point:return f'{where}: native had vector {before:#x} selectable before instruction {pc:x} (word {word:04x}), which is not a check point',stats
                if before!=want:return f'{where}: native vector {before:#x} inside {point}, reference {want and hex(want)}',stats
                stats['irq'][f'{name} inside {point}']+=1
    return None,stats

def mutate(ref,**change):
    """Deep copy with one field changed: io=(index, column, value) or irq=(index, key, value) or temps=(index, slot, value)."""
    new=json.loads(json.dumps(ref))
    for key,(i,field,value) in change.items():
        if key=='temps':new['irq'][i]['temps'][field]=value
        else:new[key][i][field]=value
    return new

class VideoTiming(unittest.TestCase):
    def test_native_video_timing_equals_original(self):
        ref=reference_video.capture(SECONDS,probes=PROBES)
        rom=roms.program_image(ROOT/'roms/mk3',roms.definition())
        io,irq=ref['io'],ref['irq']
        first=lambda cond:next(i for i,r in enumerate(io) if cond(r))
        reg=lambda r:NAMES[(r[2]-IO)>>4]
        timer_di=next(i for i,r in enumerate(irq) if r['handler']==ref['handlers']['DI'] and r['cycles']-16-r['temps'][0]<8 and i)
        hcount=first(lambda r:r[0]=='R' and reg(r)=='HCOUNT');intpend=first(lambda r:r[0]=='R' and reg(r)=='INTPEND')
        last_table=max(i for i,r in enumerate(io) if r[0]=='W' and reg(r)=='VTOTAL')
        mutants={  # reference-side: one observed value changed, same native output
            'hcount_read_value':(mutate(ref,io=(hcount,3,io[hcount][3]^1)),None),
            'intpend_read_value':(mutate(ref,io=(intpend,3,io[intpend][3]^0x400)),None),
            'vcount_sample':(mutate(ref,io=(hcount,6,io[hcount][6]+1)),None),
            'irq_boundary_cycle':(mutate(ref,irq=(timer_di,'cycles',irq[timer_di]['cycles']+irq[timer_di]['cycles']-16-irq[timer_di]['temps'][0]),
                                         temps=(timer_di,0,irq[timer_di]['cycles']-16)),None),
            'irq_vector':(mutate(ref,irq=(timer_di,'handler',ref['handlers']['INT1'])),None),
            # stimulus-side: one written value or the pixel clock changed, same reference
            'dpyint_parameter':(mutate(ref,io=(last_table+3,3,273)),8000000),
            'vtotal_parameter':(mutate(ref,io=(last_table,3,287)),8000000),
            'pixel_clock':(ref,8008000)}
        self.assertEqual(reg(io[last_table+3]),'DPYINT')
        dma_command=next(i for i,r in enumerate(ref['dma']) if r[2]>>4&15==1 and r[3]&0x8000 and r[4]>irq[0]['cycles'])
        width=max(i for i,r in enumerate(ref['dma'][:dma_command]) if r[2]>>4&15==6)
        mutants['dma_width']=(mutate(ref,dma=(width,3,ref['dma'][width][3]+64)),8000000)
        lines,expect=events(ref);build={}
        stimulus={name:events(m) for name,(m,hz) in mutants.items() if hz}
        out,*bad=native(build,[(lines,8000000)]+[(stimulus[name][0],mutants[name][1]) for name in stimulus])
        difference,stats=compare(ref,expect,out,rom)
        self.assertIsNone(difference)
        self.assertTrue(stats['early_di_samples'] and stats['line_273_samples_without_di'],'both sides of the early-DI threshold sampled')
        negatives={}
        for name,(m,hz) in mutants.items():
            negatives[name]=compare(ref,expect,bad[list(stimulus).index(name)],rom)[0] if hz else compare(m,events(m)[1],out,rom)[0]
        self.assertTrue(all(negatives.values()),negatives)
        di=[r for r in irq if r['handler']==ref['handlers']['DI']]
        table={reg(r):r[3] for r in io[last_table-7:last_table+4]}
        RECEIPT.parent.mkdir(parents=True,exist_ok=True)
        RECEIPT.write_text(json.dumps(dict(passed=True,
            scope='isolated TMS34010 video timing/interrupt-source model; stimulus = Original I/O and DMA_COMMAND writes; no CPU translation',
            program_sha256=ref['program_sha256'],core_sha256=ref['core_sha256'],seed_sha256=ref['seed_sha256'],emulated_seconds=SECONDS,
            first_interrupt_enable=dict(instruction='EINT',pc=hex(irq[0]['temps'][2]),cycle=irq[0]['temps'][0],
                first_boundary_with_ie=ref['first_ie'] and dict(pc=hex(ref['first_ie']['pc']),cycle=ref['first_ie']['cycles'],status=hex(ref['first_ie']['status']))),
            first_interrupt=dict(vector=hex(reference_video.VECTORS['DI']),handler=hex(irq[0]['handler']),handler_entry_cycle=irq[0]['cycles'],
                pushed_status=hex(irq[0]['pushed_status']),pushed_pc=hex(irq[0]['pushed_pc']),sp_after=hex(irq[0]['sp']),status_after=hex(irq[0]['status'])),
            first_timer_boundary_interrupt=dict(handler_entry_cycle=irq[timer_di]['cycles'],boundary=irq[timer_di]['cycles']-16,
                interrupted_pc=hex(irq[timer_di]['pushed_pc']),pushed_status=hex(irq[timer_di]['pushed_status'])),
            handlers={k:hex(v) for k,v in ref['handlers'].items()},video_registers=table,
            timing=dict(pixel_ns=125,line_ns=63250,frame_ns=18279250,cycle_ns=160,line_cycles=63250/160,frame_cycles=18279250/160),
            compared=dict(io_rows=len(io),dma_rows=len(ref['dma']),game_reads=dict(stats['reads']),debugger_samples=stats['samples'],sample_fields=4,
                interrupts=dict(stats['irq']),interrupt_total=len(irq),di_accepted=len(di),model_di_events=stats['model_di_events'],
                model_int1_events=stats['model_int1_events'],game_vcount_reads=sum(1 for r in io if r[0]=='R' and reg(r)=='VCOUNT'),
                early_di_samples=stats['early_di_samples'],line_273_samples_without_di=stats['line_273_samples_without_di'],
                mid_instruction_accesses=sum(1 for r in io+ref['dma'] if r[9]),dma_triggers=sum(1 for r in ref['dma'] if r[2]>>4&15==1 and r[3]&0x8000)),
            negative_controls=negatives,
            timings_seconds=dict(native_build=build['seconds'],reference=ref['wall_seconds']),cleanup=ref['cleanup']['exists_after']),indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':unittest.main()
