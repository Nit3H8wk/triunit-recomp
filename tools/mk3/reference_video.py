"""Read-only MK3 2.1 Original observations of TMS34010 video timing and interrupts (pinned MAME debugger).

From reset, seeded CMOS, default DIPs, no inputs. Logged with PC and totalcycles (instruction-start cycle):
- every main-CPU read/write of its I/O registers (0xc0000000-0xc00001ff) and every DMA register write (both
  mirrors). Row: [kind, pc, address, data, instruction-start cycle, HCOUNT, VCOUNT, DPYADR, INTPEND, offset].
  The four samples are debugger reads through io_register_r with side effects disabled (write rows: before
  the write lands). offset = cycles the instruction had already counted at the access (icount at the
  instruction start, kept in temp4, minus icount now): machine().time() advances inside MMTM/MMFM;
- optional sample-only rows (kind 'S') at every instruction start inside given cycle windows (registerpoint 2);
- the first instruction boundary with ST.IE set (registerpoint 1);
- every entry into an interrupt handler (breakpoint on each distinct vector target read from the authenticated
  program): ST, SP, the two longwords the acceptance pushed (ST at SP, PC at SP+0x20) and, from registerpoint
  2 (evaluated before every instruction, after the breakpoints of the same PC), the PC and start cycle of
  the last instruction executed before it.
Optionally a loop-compressed instruction trace from TRACE_START on, reduced here to PCs in order of first
appearance per segment. The debugger log and the trace live only in the scratch tree, removed on success and
failure. temp0-temp4 are debugger variables; nothing is written to the machine.
"""
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import reference,roms

ROOT=Path(__file__).resolve().parents[2]
TRACE_START=0xffaa8990
IE=0x00200000
# tms34010.cpp check_interrupt (docs/investigation/sources/tms34010.cpp:630-691) and reset/trap vectors.
VECTORS={'NMI':0xfffffee0,'HI':0xfffffec0,'DI':0xfffffea0,'WV':0xfffffe80,'INT1':0xffffffc0,'INT2':0xffffffa0}

def handlers(rom):
    """Vector name -> handler PC, from the authenticated program image (base 0xff800000, bit addresses)."""
    return {name:int.from_bytes(rom[(v-0xff800000)//8:][:4],'little')&0xfffffff0 for name,v in VECTORS.items()}

def script(entries,trace,probes=()):
    row='printf "MK3_{} %X %X %X %d %d %X %X %X %X %d\\n",pc,wpaddr,wpdata,totalcycles,wpsize,w@c00001c0,w@c00001d0,w@c00001e0,w@c0000120,temp4-cycles;g'
    lines=['focus :maincpu',
           'wpset c0000000,200,w,1,{'+row.format('IOW')+'}','wpset c0000000,200,r,1,{'+row.format('IOR')+'}',
           'wpset 1a00000,100,w,1,{'+row.format('DMA')+'}','wpset 1a80000,100,w,1,{'+row.format('DMA')+'}']
    for pc in sorted(set(entries)):
        lines.append(f'bpset {pc:x},1,{{printf "MK3_IRQ %X %X %d %X %X %X %d %d %X %X\\n",pc,st,totalcycles,sp,d@sp,d@(sp+20),temp0,temp1,temp2,temp3;g}}')
    lines+=['rpset {(st&200000)!=0},{printf "MK3_IE %X %X %d\\n",pc,st,totalcycles;rpdisable 1;g}',
            'rpset {((temp1=temp0)+(temp0=totalcycles)+(temp3=temp2)+(temp2=pc)+(temp4=cycles))<0}']
    if probes:  # sample-only rows at every instruction start inside the cycle windows, from the same registerpoint
        # (a second registerpoint that fires would keep registerpoint 2 from running at that instruction)
        lines[-1]=lines[-1][:-1]+'||'+'||'.join(f'(totalcycles>={a:x}&&totalcycles<={b:x})' for a,b in probes)+'},{'+row.format('PROBE').replace('wpaddr,wpdata','0,0').replace('wpsize','10').replace('temp4-cycles','0')+'}'
    if trace:
        lines.append(f'bpset {TRACE_START:x},1,{{bpdisable {len(set(entries))+1:x};trace pcs.log,maincpu,,{{tracelog "T %X %d\\n",st,totalcycles}};g}}')
    return '\n'.join(lines+['go'])+'\n'

def parse(text):
    io,dma,irq,ie=[],[],[],None
    for line in text.splitlines():
        f=line.split()
        if not f or not f[0].startswith('MK3_'):
            if 'rror' in line and not line.startswith('>'):raise ValueError('MAME diagnostic: '+line)
            continue
        if f[0]=='MK3_PROBE':f[0]='MK3_IOS'
        if f[0] in ('MK3_IOW','MK3_IOR','MK3_IOS','MK3_DMA'):
            if f[5]!='16':raise ValueError('non-16-bit access: '+line)
            (dma if f[0]=='MK3_DMA' else io).append([f[0][-1],int(f[1],16),int(f[2],16),int(f[3],16),int(f[4])]+[int(x,16) for x in f[6:10]]+[int(f[10])])
            if not 0<=int(f[10])<256:raise ValueError('implausible in-instruction cycle offset: '+line)
        elif f[0]=='MK3_IE':ie=dict(pc=int(f[1],16),status=int(f[2],16),cycles=int(f[3]))
        elif f[0]=='MK3_IRQ':
            irq.append(dict(handler=int(f[1],16),status=int(f[2],16),cycles=int(f[3]),sp=int(f[4],16),
                            pushed_status=int(f[5],16),pushed_pc=int(f[6],16),temps=[int(f[7]),int(f[8]),int(f[9],16),int(f[10],16)]))
    return io,dma,irq,ie

def segments(lines,stops):
    """Trace -> per segment: PCs in order of first appearance and the number of traced (non-loop-skipped) lines.
    A segment ends before the first traced instruction whose start cycle is >= the next stop."""
    out=[[] for _ in range(len(stops)+1)];seen=[set() for _ in out];counts=[0]*len(out);loops=[0]*len(out);k=0;cycles=None
    for line in lines:
        line=line.strip()
        if line.startswith('T '):
            cycles=int(line.split()[2])
            while k<len(stops) and cycles>=stops[k]:k+=1
        elif line.startswith('(loops for'):loops[k]+=int(line.split()[2])
        elif ':' in line and cycles is not None:
            pc=int(line.split(':')[0],16);counts[k]+=1
            if pc not in seen[k]:seen[k].add(pc);out[k].append(pc)
    return out,counts,loops

def capture(seconds=1,trace=False,stops=(),probes=()):
    """stops: cycle bounds splitting the trace (use a first pass to learn them). probes: inclusive cycle windows
    in which every instruction start adds a sample-only io row (kind 'S')."""
    if q.sha(reference.CORE)!=reference.CORE_SHA:raise ValueError('Reference core identity changed')
    identity=roms.verify(ROOT/'roms/mk3')
    entry=handlers(roms.program_image(ROOT/'roms/mk3',roms.definition()))
    with q.scratch_tree() as (temp,cleanup):
        (temp/'nvram/mk3').mkdir(parents=True);(temp/'nvram/mk3/nvram').write_bytes(reference.SEED.read_bytes())
        (temp/'video.cmd').write_text(script(entry.values(),trace,probes),encoding='ascii')
        run=q.command([reference.CORE,'mk3','-rompath',ROOT/'roms','-noreadconfig','-nowriteconfig','-skip_gameinfo','-noplugins',
                       '-video','none','-sound','none','-nothrottle','-debug','-debugger','windows','-debuglog','-debugscript','video.cmd',
                       '-nvram_directory','nvram','-cfg_directory','cfg','-homepath','home','-snapshot_directory','snap','-seconds_to_run',str(seconds)],
                      temp,cwd=temp,timeout=900)
        if not run['passed']:raise RuntimeError('Reference run failed: '+run.get('stdout','')[-1000:])
        log=temp/'debug.log'
        if not log.is_file() or log.stat().st_size>256*1024*1024:raise ValueError('Missing or oversized debugger log')
        io,dma,irq,ie=parse(log.read_text('utf-8'))
        pcs=counts=loops=None;trace_bytes=0
        if trace:
            trace_bytes=(temp/'pcs.log').stat().st_size
            if trace_bytes>512*1024*1024:raise ValueError('Oversized trace')
            with (temp/'pcs.log').open(encoding='utf-8') as stream:pcs,counts,loops=segments(stream,stops)
    if cleanup['exists_after']:raise ValueError('Reference scratch retained')
    return dict(core_sha256=reference.CORE_SHA,program_sha256=identity['program_sha256'],seed_sha256=q.sha(reference.SEED),
                seconds=seconds,wall_seconds=run['wall_seconds'],handlers=entry,io=io,dma=dma,irq=irq,first_ie=ie,
                pcs=pcs,traced=counts,loop_skipped=loops,trace_bytes=trace_bytes,cleanup=cleanup)

if __name__=='__main__':
    r=capture(float(sys.argv[1]) if len(sys.argv)>1 else 1,trace='--trace' in sys.argv)
    print(json.dumps(dict(r,io=r['io'][:80],io_rows=len(r['io']),dma=r['dma'][:40],dma_rows=len(r['dma']),irq=r['irq'][:12],irq_rows=len(r['irq']),
                          pcs=r['pcs'] and [len(p) for p in r['pcs']],handlers={k:hex(v) for k,v in r['handlers'].items()})))
