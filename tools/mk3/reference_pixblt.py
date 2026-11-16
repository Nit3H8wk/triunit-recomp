"""Read-only MK3 2.1 Original observation of PIXBLT B,XY at 0xffae8690 (pinned MAME debugger, compact results).

Every execution of the PIXBLT (including restarts with ST.P set) before a cycle bound prints PC, ST,
totalcycles, the 31 registers, the 32 TMS34010 I/O registers, the Wolf-Unit video control latch and
DMA_PALETTE; every completion at 0xffae86a0 prints PC, ST, totalcycles and the registers. Watchpoints keep
the bus accesses made inside the instruction (MAME's PC is 0xffae86a0 there): VRAM reads/writes and ROM
reads (the opcode fetch at 0xffae8690 is reported separately). The debugger log is removed with the scratch tree.
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import reference,roms

PC=0xffae8690
INSIDE=PC+16  # MAME m_pc while the instruction runs (after ROPCODE).
IO=[f'w@{0xc0000000+16*i:x}' for i in range(32)]

def script(bound):
    cond=f'totalcycles<{bound:x}'
    access='printf "PX_{k} %X %X %X %d %d\\n",pc,wpaddr,wpdata,totalcycles,wpsize;g'
    regs=','.join(reference.REGISTERS)
    state='%08X %08X %d '+' '.join(['%08X']*31)
    return '\n'.join(['focus :maincpu',
        f'wpset 0,400000,w,pc=={INSIDE:x} && {cond},{{{access.format(k="W")}}}',
        f'wpset 0,400000,r,pc=={INSIDE:x} && {cond},{{{access.format(k="R")}}}',
        f'wpset ff800000,800000,r,pc=={INSIDE:x} && {cond},{{{access.format(k="R")}}}',
        f'bpset {PC:x},{cond},{{printf "PX_IN {state}\\n",pc,st,totalcycles,{regs};'
        f'printf "PX_IO '+' '.join(['%X']*34)+'\\n",'+','.join(IO)+',w@1b00000,w@1a00080;g}',
        f'bpset {INSIDE:x},{cond},{{printf "PX_OUT {state}\\n",pc,st,totalcycles,{regs};g}}','go'])+'\n'

def parse(text):
    """Executions: [{entry:{pc,status,cycles,registers}, io:[32], video_control, dma_palette, reads, writes}]; completions."""
    runs,done=[],[]
    for line in text.splitlines():
        kind,*f=line.strip().split() or ['']
        if kind in ('PX_IN','PX_OUT'):
            if len(f)!=34:raise ValueError('Truncated checkpoint '+line[:60])
            point=dict(pc=int(f[0],16),status=int(f[1],16),cycles=int(f[2]),registers=[int(r,16) for r in f[3:]])
            if kind=='PX_IN':runs.append(dict(entry=point,reads=[],writes=[]))
            else:done.append(point)
        elif kind=='PX_IO':
            if len(f)!=34 or 'io' in runs[-1]:raise ValueError('Bad I/O checkpoint')
            v=[int(x,16) for x in f];runs[-1].update(io=v[:32],video_control=v[32],dma_palette=v[33])
        elif kind in ('PX_R','PX_W'):
            (pc,address,data),cycles,size=(int(x,16) for x in f[:3]),int(f[3]),int(f[4])
            if pc!=INSIDE or size!=16:raise ValueError('Unexpected access '+line)
            if kind=='PX_R' and address==PC:continue  # opcode fetch of the PIXBLT itself
            runs[-1]['reads' if kind=='PX_R' else 'writes'].append([address,data,cycles])
        elif kind and not kind.startswith('>') and any(w in line.lower() for w in ('error','unknown','invalid')):
            raise ValueError('MAME diagnostic: '+line)
    return runs,done

def capture(bound=496628,seconds=1):
    if q.sha(reference.CORE)!=reference.CORE_SHA:raise ValueError('Reference core identity changed')
    identity=roms.verify(reference.ROOT/'roms/mk3')
    with q.scratch_tree() as (temp,cleanup):
        (temp/'nvram/mk3').mkdir(parents=True);(temp/'nvram/mk3/nvram').write_bytes(reference.SEED.read_bytes())
        (temp/'pixblt.cmd').write_text(script(bound),encoding='ascii')
        run=q.command([reference.CORE,'mk3','-rompath',reference.ROOT/'roms','-noreadconfig','-nowriteconfig','-skip_gameinfo','-noplugins',
                       '-video','none','-sound','none','-nothrottle','-debug','-debugger','windows','-debuglog','-debugscript','pixblt.cmd',
                       '-nvram_directory','nvram','-cfg_directory','cfg','-homepath','home','-snapshot_directory','snap','-seconds_to_run',str(seconds)],
                      temp,cwd=temp,timeout=900)
        if not run['passed']:raise RuntimeError('Reference run failed: '+run.get('stdout','')[-1000:])
        log=temp/'debug.log'
        if not log.is_file() or log.stat().st_size>64*1024*1024:raise ValueError('Missing or oversized debugger log')
        text=log.read_text('utf-8');version=text.splitlines()[0]
        runs,done=parse(text)
    if cleanup['exists_after']:raise ValueError('Reference scratch retained')
    if not runs or any('io' not in r for r in runs):raise ValueError('PIXBLT not observed')
    return dict(core_sha256=reference.CORE_SHA,debugger=version,program_sha256=identity['program_sha256'],seed_sha256=q.sha(reference.SEED),
                bound=bound,wall_seconds=run['wall_seconds'],executions=runs,completions=done,cleanup=cleanup)

if __name__=='__main__':
    import json
    ref=capture()
    print(json.dumps(dict(executions=[dict(entry=dict(r['entry'],registers=[hex(x) for x in r['entry']['registers']]),st=hex(r['entry']['status']),
        io=[hex(x) for x in r['io']],vc=hex(r['video_control']),pal=hex(r['dma_palette']),reads=len(r['reads']),writes=len(r['writes'])) for r in ref['executions']],
        completions=[dict(c,registers=[hex(x) for x in c['registers']]) for c in ref['completions']],wall=ref['wall_seconds'],cleanup=ref['cleanup'])))
