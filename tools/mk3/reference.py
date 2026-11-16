"""Read-only MK3 2.1 Original observations through the pinned MAME debugger; compact results only.

Breakpoints print PC, ST, totalcycles and the 31 general registers (SP counted once); watchpoints print
ordered main-CPU writes and device reads up to a cycle bound. The debugger log is the only transport and is
removed with the scratch tree. Nothing is imported into the native executor.
"""
from pathlib import Path
import json,os,re,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import roms
from tools.setup import mk3 as setup_mk3

ROOT=Path(__file__).resolve().parents[2]
CORE=Path('D:/Emuladores/Mame/mame2080/mame.exe')
CORE_SHA='84b690dad588253139ea49ae5e3c9fcddf9df7bcd526fccd1724ec7e09120dec'
SEED=setup_mk3.SEED   # written by the setup (tools/setup/mk3.py factory_seed), not versioned
REGISTERS=[f'a{i}' for i in range(15)]+['sp']+[f'b{i}' for i in range(15)]
DEVICES=((0x01400000,0x100000),(0x01600000,0x20),(0x01680000,0x20),(0x01800000,0x80000),(0x01a00000,0x100),(0x01b00000,0x20))

def script(points,bus_cycles,pm_words=0,extra=()):
    """points: (name, pc, condition[, more breakpoint commands...]); extra: further script lines before `go`."""
    lines=['focus :maincpu',
           f'wpset 0,ffffffff,w,totalcycles<{bus_cycles:x},{{printf "MK3_W %X %X %X %d %d\\n",pc,wpaddr,wpdata,totalcycles,wpsize;g}}']
    for base,size in DEVICES:
        lines.append(f'wpset {base:x},{size:x},r,totalcycles<{bus_cycles:x},{{printf "MK3_R %X %X %X %d %d\\n",pc,wpaddr,wpdata,totalcycles,wpsize;g}}')
    fmt='MK3_CPU NAME %08X %08X %d '+' '.join(['%08X']*31)+'\\n'
    for index,(name,pc,condition,*more) in enumerate(points,start=1):
        save=(f';save dcs_pm.bin,0:dcs:dcs,{pm_words:x}' if pm_words and index==1 else '')+''.join(';'+m for m in more)
        lines.append(f'bpset {pc:x},{condition},{{bpdisable {index:x};printf "{fmt.replace("NAME",name)}",pc,st,totalcycles,{",".join(REGISTERS)}{save};g}}')
    return '\n'.join(lines+list(extra)+['go'])+'\n'

def parse(text):
    cpu,bus={},[]
    for line in text.splitlines():
        line=line.strip()
        if line.startswith('MK3_CPU '):
            _,name,pc,st,cycles,*regs=line.split()
            if name in cpu or len(regs)!=31:raise ValueError('Duplicate or truncated checkpoint '+name)
            cpu[name]=dict(pc=int(pc,16),status=int(st,16),cycles=int(cycles),registers=[int(r,16) for r in regs])
        elif line.startswith(('MK3_W ','MK3_R ')):
            kind,pc,address,data,cycles,size=line.split()
            bus.append([kind[-1],int(pc,16),int(address,16),int(data,16),int(cycles),int(size)])
        elif re.search(r'error|unknown|invalid',line,re.I) and not line.startswith('>'):raise ValueError('MAME diagnostic: '+line)
    return cpu,bus

def capture(points,bus_cycles,seconds=1,pm_words=0,extra=(),extra_parse=None):
    """points: [(name, pc_bits, debugger condition, ...)]. Seeded CMOS, default DIPs, no inputs.
    pm_words: also save that many ADSP internal PM words (4 bytes each) at the first checkpoint.
    extra/extra_parse: further script lines and a parser of the log text for what they print (result in 'extra')."""
    if q.sha(CORE)!=CORE_SHA:raise ValueError('Reference core identity changed')
    identity=roms.verify(ROOT/'roms/mk3')
    with q.scratch_tree() as (temp,cleanup):
        (temp/'nvram/mk3').mkdir(parents=True);(temp/'nvram/mk3/nvram').write_bytes(SEED.read_bytes())
        (temp/'reset.cmd').write_text(script(points,bus_cycles,pm_words,extra),encoding='ascii')
        run=q.command([CORE,'mk3','-rompath',ROOT/'roms','-noreadconfig','-nowriteconfig','-skip_gameinfo','-noplugins',
                       '-video','none','-sound','none','-nothrottle','-debug','-debugger','windows','-debuglog','-debugscript','reset.cmd',
                       '-nvram_directory','nvram','-cfg_directory','cfg','-homepath','home','-snapshot_directory','snap','-seconds_to_run',str(seconds)],
                      temp,cwd=temp,timeout=900)
        if not run['passed']:raise RuntimeError('Reference run failed: '+run.get('stdout','')[-1000:])
        log=temp/'debug.log'
        if not log.is_file() or log.stat().st_size>256*1024*1024:raise ValueError('Missing or oversized debugger log')
        text=log.read_text('utf-8');version=text.splitlines()[0]
        cpu,bus=parse(text)
        observed=extra_parse(text) if extra_parse else None
        pm=[]
        if pm_words:
            data=(temp/'dcs_pm.bin').read_bytes()
            if len(data)!=pm_words*4:raise ValueError('Incomplete ADSP PM observation')
            pm=[int.from_bytes(data[i:i+4],'little') for i in range(0,len(data),4)]
    if cleanup['exists_after']:raise ValueError('Reference scratch retained')
    missing=[point[0] for point in points if point[0] not in cpu]
    if missing:raise ValueError('Checkpoints not reached: '+', '.join(missing))
    return dict(core_sha256=CORE_SHA,debugger=version,program_sha256=identity['program_sha256'],seed_sha256=q.sha(SEED),
                wall_seconds=run['wall_seconds'],cpu=cpu,bus=bus,dsp_pm=pm,extra=observed,cleanup=cleanup)

if __name__=='__main__':
    print(json.dumps(capture([('frontier',0xff814aa0,'1')],235),indent=1))
