"""Read-only MK3 2.1 Original observation of the DCS 8K ADSP-2105 through the pinned MAME debugger.

The debugger is focused on :dcs:dcs (so trace/printf symbols are the ADSP's) and observes :maincpu.
- Window: `trace noloop` prints the full register set before every ADSP instruction from power-on until the
  boot-1 instruction at totalcycles WINDOW_END, where PM/DM images are saved.
- Extension: one breakpoint per translated PC prints the same fields (the delay NOP 0x45 only for
  totalcycles <= WINDOW_END+40 or a multiple of 1009); the bank-1 reboot (0x100) arms temp0 and the next PC-0
  entry saves the images and quits. ADSP data/program-data accesses are watched until then (cleared at that entry).
- Main CPU: io[1] writes, DCS port accesses and status reads before cycle 1968 (main symbols via symlist).
Only compact parsed values leave the scratch tree; the log, trace and images are removed with it.
"""
from pathlib import Path
import os,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import reference,roms

ROOT=Path(__file__).resolve().parents[2]
WINDOW_END=2763
PCS=(0x00,0x04,*range(0x22,0x4a),*range(0xf5,0x101),*range(0x176,0x17f))
NL='\\n'


def fields():
    # Same order as mk3::Dcs8k::FieldNames().
    core=['ax0','ax1','ay0','ay1','ar','af','mx0','mx1','my0','my1','mr0','mr1','mr2','mf','si','se','sb','sr0','sr1']
    return (['pc','totalcycles']+core+[c+'_sec' for c in core]+[f'{g}{k}' for g in 'ilm' for k in range(8)]+
            ['px','cntr','astat','sstat','mstat','pcsp','cntrsp','statsp','loopsp','imask','icntl','irq0','irq1','irq2','irq3',
             'flagin','flagout','fl0','fl1','fl2'])


def script():
    names=fields();fmt=' '.join(['%X']*len(names));args=','.join(names)
    images='save {0}_pm.bin,0:dcs:dcs,2000;saved {0}_dm.bin,0:dcs:dcs,4000'
    lines=['focus :dcs:dcs','observe :maincpu','temp0=0',
           f'trace dcs.tr,:dcs:dcs,noloop,{{tracelog "T {fmt}{NL}",{args}}}',
           # One action runs per hook: this breakpoint also prints the sampled 0x45 row.
           f'bpset 45:dcs:dcs,totalcycles=={WINDOW_END:x},{{bpdisable 1;trace off,:dcs:dcs;{images.format("win")};printf "B {fmt}{NL}",{args};g}}',
           f'bpset 0:dcs:dcs,temp0==1,{{bpclear;wpclear;printf "E {fmt}{NL}",{args};{images.format("end")};quit}}']
    for pc in PCS:
        cond='temp0==0'+(f'&&(totalcycles<={WINDOW_END+40:x}||totalcycles%3f1==0)' if pc==0x45 else '')
        arm=';temp0=1' if pc==0x100 else ''
        lines.append(f'bpset {pc:x}:dcs:dcs,{cond},{{printf "B {fmt}{NL}",{args}{arm};g}}')
    access='{{printf "A {0} %X %X %X %X'+NL+'",curpc,totalcycles,wpaddr,wpdata;g}}'
    lines+=[f'wpset 0:dcs:dcs:data,4000,r,1,'+access.format('r'),
            f'wpset 0:dcs:dcs:data,4000,w,1,'+access.format('w'),
            f'wpset 0:dcs:dcs:program,2000,w,1,'+access.format('p'),
            f'wpset 0:dcs:dcs:program,400,r,wpaddr!=curpc,'+access.format('q')]
    host='{{printf "H {0} %X %X'+NL+'",wpaddr,wpdata;symlist :maincpu;g}}'
    lines+=['wpset 187ff90:maincpu,10,w,1,'+host.format('io1'),
            'wpset 1680000:maincpu,20,w,1,'+host.format('dcs_w'),
            'wpset 1680000:maincpu,20,r,1,'+host.format('dcs_r'),
            'wpset 187ffc0:maincpu,10,r,totalcycles<7b0,'+host.format('status'),'go']
    return '\n'.join(lines)+'\n'


def words(path,size):
    data=path.read_bytes()
    if len(data)%size:raise ValueError('Truncated image '+path.name)
    return [int.from_bytes(data[i:i+size],'little') for i in range(0,len(data),size)]


def parse(log,trace,count):
    out=dict(trace=[],rows=[],end=None,accesses=[],host=[])
    for line in trace.splitlines():
        if line.startswith('T '):
            row=[int(v,16) for v in line.split()[1:]]
            if len(row)!=count:raise ValueError('Truncated trace row')
            out['trace'].append(row)
    host=None
    for line in log.splitlines():
        line=line.strip()
        if line.startswith(('B ','E ')):
            row=[int(v,16) for v in line.split()[1:]]
            if len(row)!=count:raise ValueError('Truncated breakpoint row')
            if line[0]=='B':out['rows'].append(row)
            elif out['end'] is None:out['end']=row
            else:raise ValueError('Duplicate end row')
        elif line.startswith('A '):
            _,kind,*numbers=line.split()   # pc, totalcycles, address, value[, boot]
            out['accesses'].append([kind,*(int(x,16) for x in numbers)])
        elif line.startswith('H '):
            _,kind,address,data=line.split()
            host=dict(kind=kind,address=int(address,16),value=int(data,16));out['host'].append(host)
        elif host is not None and ' = ' in line:
            name,value=line.split(' = ',1)
            if name in ('pc','totalcycles'):host[name]=int(value.split()[0],16)
        elif line.startswith('>') or not line or line.startswith('****'):continue
        elif any(word in line.lower() for word in ('error','unknown','invalid','unbalanced')):raise ValueError('MAME diagnostic: '+line)
    if any(set(h)!={'kind','address','value','pc','totalcycles'} for h in out['host']):raise ValueError('Incomplete host event')
    return out


def capture(seconds=1):
    if q.sha(reference.CORE)!=reference.CORE_SHA:raise ValueError('Reference core identity changed')
    identity=roms.verify(ROOT/'roms/mk3')
    with q.scratch_tree() as (temp,cleanup):
        (temp/'nvram/mk3').mkdir(parents=True);(temp/'nvram/mk3/nvram').write_bytes(reference.SEED.read_bytes())
        (temp/'dcs.cmd').write_text(script(),encoding='ascii')
        run=q.command([reference.CORE,'mk3','-rompath',ROOT/'roms','-noreadconfig','-nowriteconfig','-skip_gameinfo','-noplugins',
                       '-video','none','-sound','none','-nothrottle','-debug','-debugger','windows','-debuglog','-debugscript','dcs.cmd',
                       '-nvram_directory','nvram','-cfg_directory','cfg','-homepath','home','-snapshot_directory','snap','-seconds_to_run',str(seconds)],
                      temp,cwd=temp,timeout=300)
        if not run['passed']:raise RuntimeError('Reference run failed: '+run.get('stdout','')[-1000:])
        log,trace=temp/'debug.log',temp/'dcs.tr'
        for path in (log,trace):
            if not path.is_file() or path.stat().st_size>64*1024*1024:raise ValueError('Missing or oversized '+path.name)
        text=log.read_text('utf-8');version=text.splitlines()[0]
        out=parse(text,trace.read_text('utf-8'),len(fields()))
        for name in ('win','end'):
            out[name+'_pm']=words(temp/f'{name}_pm.bin',4);out[name+'_dm']=words(temp/f'{name}_dm.bin',2)
    if cleanup['exists_after']:raise ValueError('Reference scratch retained')
    if out['end'] is None or len(out['win_pm'])!=0x2000 or len(out['win_dm'])!=0x4000:raise ValueError('Reference did not reach the bank-1 entry')
    out.update(core_sha256=reference.CORE_SHA,debugger=version,program_sha256=identity['program_sha256'],
               seed_sha256=q.sha(reference.SEED),wall_seconds=run['wall_seconds'],cleanup=cleanup,fields=fields())
    return out


BANK1_MARKER=0x131                                     # once per audio frame, before the LED/bank write at 0x132
BANK1_WAIT=(0x137,0x138,0x139,0x13d,0x13e,0x13f)       # the two loops that poll I7 for the autobuffer half
BANK1_BUFFER=(0x0c00,0x0de0)                           # autobuffer (I7 base, L7) read by dcs_irq


BANK1_BOOTS=(3,5)                                      # boots that run the bank-1 program (the others run bank 0)


def schedule_script(schedule):
    """Bank-1 program observation driven by `schedule`: (boot, cycles, mode) switch points in order; cycles 0 is the
    boot's PC-0 entry, otherwise the first frame marker (PC 0x131) of that boot at totalcycles >= cycles. Modes:
    'F' full: a field row before every instruction (one registerpoint; the bank-1 I7 wait loops only every 1009 cycles
    or while IRQ1 is asserted, the bank-0 delay NOP 0x45 likewise) and every data / program-data access;
    'S' sparse: the frame-marker rows and the accesses to the autobuffer (the CPU's writes and the dcs_irq reads, which
    the watchpoint sees inside the timer callback with the PC and totalcycles of the last executed instruction), to DM
    0x3000-0x37ff (bank select, latches) and to the control registers; 'E' end: images saved, quit.
    Nothing is observed before the first switch; every switch prints its row. Always: the host's io[1] / sound-port
    accesses and, after the first switch, the first status read of each new value.
    temp9 counts the PC-0 entries (the boot number), temp2 the switches done, temp3 is the full flag.
    """
    names=fields();fmt=' '.join(['%X']*len(names));args=','.join(names)
    row=f'printf "B {fmt}{NL}",{args}'
    # Numbers carry 0x: a bare "af" is the AF register to the expression parser.
    many=lambda command,numbers:';'.join(f'{command} 0x{n:x}' for n in numbers)
    entries=[(n,boot) for n,(boot,cycles,_) in enumerate(schedule) if not cycles]
    markers=[(n,boot,cycles) for n,(boot,cycles,_) in enumerate(schedule) if cycles]
    def switch(n):
        mode=schedule[n][2]
        if mode=='E':return f'{row};printf "E {fmt}{NL}",{args};save end_pm.bin,0:dcs:dcs,2000;saved end_dm.bin,0:dcs:dcs,4000;quit'
        if mode=='F':return f'temp2=0x{n+1:x};temp3=1;wpenable;rpenable;{row};g'
        return f'temp2=0x{n+1:x};temp3=0;rpdisable;{many("wpdisable",range(1,9))};{many("wpenable",range(9,15))};{row};g'
    entry=lambda n,boot:f'temp9==0x{boot-1:x}&&temp2==0x{n:x}'
    at=lambda n,boot,cycles:f'temp2==0x{n:x}&&temp9==0x{boot:x}&&totalcycles>=0x{cycles:x}'
    lines=['focus :dcs:dcs','observe :maincpu','temp1=ffff','temp2=0','temp3=0','temp9=0']
    lines+=[f'bpset 0:dcs:dcs,{entry(n,boot)},{{temp9=0x{boot:x};{switch(n)}}}' for n,boot in entries]
    other='(('+'||'.join(f'({entry(n,boot)})' for n,boot in entries)+')==0)' if entries else '1'
    lines+=[f'bpset 0:dcs:dcs,{other}&&temp3==1,{{temp9=temp9+1;{row};g}}',f'bpset 0:dcs:dcs,{other}&&temp3==0,{{temp9=temp9+1;g}}']
    lines+=[f'bpset {BANK1_MARKER:x}:dcs:dcs,{at(n,boot,cycles)},{{{switch(n)}}}' for n,boot,cycles in markers]
    none='(('+'||'.join(f'({at(*m)})' for m in markers)+')==0)' if markers else '1'
    lines.append(f'bpset {BANK1_MARKER:x}:dcs:dcs,temp2>0&&{none},{{{row};g}}')
    bank1='('+'||'.join(f'temp9==0x{b:x}' for b in BANK1_BOOTS)+')'
    # PC 0 and the marker have their own breakpoints (one action runs per hook).
    waits='||'.join(f'pc==0x{pc:x}' for pc in BANK1_WAIT)
    lines+=[f'rpset pc!=0&&pc!=0x{BANK1_MARKER:x}&&(({waits})==0||({bank1}==0)||totalcycles%0x3f1==0||irq1)&&(pc!=0x45||{bank1}||totalcycles%0x3f1==0||irq1),{{{row};g}}',
            'rpdisable']
    access='{{printf "A {0} %X %X %X %X %X'+NL+'",curpc,totalcycles,wpaddr,wpdata,temp9;g}}'   # boot last
    data=lambda a,b:[f'wpset 0x{a:x}:dcs:dcs:data,0x{b-a:x},{k},1,'+access.format(k) for k in 'rw']
    lo,hi=BANK1_BUFFER
    lines+=[*data(0,lo),*data(hi,0x3000),*data(0x3800,0x3fe0),                                              # 1-8: full only
            'wpset 0:dcs:dcs:program,2000,w,1,'+access.format('p'),'wpset 0:dcs:dcs:program,2000,r,wpaddr!=curpc,'+access.format('q'),
            *data(lo,hi),*data(0x3000,0x3800),*data(0x3fe0,0x4000),                                         # 9-14: full and sparse
            *(f'wpdisable 0x{n:x}' for n in range(1,15))]
    host='{{printf "H {0} %X %X'+NL+'",wpaddr,wpdata;symlist :maincpu;g}}'
    lines+=['wpset 187ff90:maincpu,10,w,1,'+host.format('io1'),
            'wpset 1680000:maincpu,20,w,1,'+host.format('dcs_w'),
            'wpset 1680000:maincpu,20,r,1,'+host.format('dcs_r'),
            'wpset 187ffc0:maincpu,10,r,temp2>0&&wpdata!=temp1,{temp1=wpdata;printf "H status %X %X'+NL+'",wpaddr,wpdata;symlist :maincpu;g}','go']
    return '\n'.join(lines)+'\n'


def capture_bank1(schedule,seconds=3):
    if q.sha(reference.CORE)!=reference.CORE_SHA:raise ValueError('Reference core identity changed')
    identity=roms.verify(ROOT/'roms/mk3')
    with q.scratch_tree() as (temp,cleanup):
        (temp/'nvram/mk3').mkdir(parents=True);(temp/'nvram/mk3/nvram').write_bytes(reference.SEED.read_bytes())
        (temp/'dcs.cmd').write_text(schedule_script(schedule),encoding='ascii')
        run=q.command([reference.CORE,'mk3','-rompath',ROOT/'roms','-noreadconfig','-nowriteconfig','-skip_gameinfo','-noplugins',
                       '-video','none','-sound','none','-nothrottle','-debug','-debugger','windows','-debuglog','-debugscript','dcs.cmd',
                       '-nvram_directory','nvram','-cfg_directory','cfg','-homepath','home','-snapshot_directory','snap','-seconds_to_run',str(seconds)],
                      temp,cwd=temp,timeout=900)
        if not run['passed']:raise RuntimeError('Reference run failed: '+run.get('stdout','')[-1000:])
        log=temp/'debug.log'
        if not log.is_file() or log.stat().st_size>96*1024*1024:raise ValueError('Missing or oversized debug.log')
        size=log.stat().st_size;text=log.read_text('utf-8');out=parse(text,'',len(fields()));del out['trace']
        if out['end'] is None:raise ValueError('Reference did not reach the bank-1 end marker')
        out['end_pm']=words(temp/'end_pm.bin',4);out['end_dm']=words(temp/'end_dm.bin',2)
    if cleanup['exists_after']:raise ValueError('Reference scratch retained')
    out.update(core_sha256=reference.CORE_SHA,debugger=text.splitlines()[0],program_sha256=identity['program_sha256'],
               seed_sha256=q.sha(reference.SEED),wall_seconds=run['wall_seconds'],cleanup=cleanup,fields=fields(),log_bytes=size)
    return out


def pairs_script():
    """Every distinct (PC, opcode) the ADSP executes, per boot: one self-disabling breakpoint per PM address (number
    = address + 1), all re-enabled at each PC-0 entry (dcs_boot reloads the internal PM) and one re-enabled by every
    program write and every data write to the external-PM alias (DM 0x0800-0x1fff) outside the autobuffer.
    Also: the host's io[1] / sound-port accesses and the first non-zero sample the dcs_irq / CPU reads from the buffer."""
    lo,hi=BANK1_BUFFER
    entry='{temp9=temp9+1;printf "C %X %X %X %X'+NL+'",pc,pd@pc,temp9,totalcycles;bpenable;g}'
    lines=['focus :dcs:dcs','observe :maincpu','temp9=0',f'bpset 0:dcs:dcs,1,{entry}']
    lines+=[f'bpset 0x{a:x}:dcs:dcs,1,{{printf "C %X %X %X %X{NL}",pc,pd@pc,temp9,totalcycles;bpdisable 0x{a+1:x};g}}' for a in range(1,0x2000)]
    enable='{bpenable wpaddr+1;g}'
    lines+=['wpset 0:dcs:dcs:program,2000,w,1,'+enable,f'wpset 0x800:dcs:dcs:data,0x{lo-0x800:x},w,1,'+enable,
            f'wpset 0x{hi:x}:dcs:dcs:data,0x{0x2000-hi:x},w,1,'+enable,
            f'wpset 0x{lo:x}:dcs:dcs:data,0x{hi-lo:x},r,wpdata!=0,{{printf "Z %X %X %X %X %X'+NL+'",curpc,temp9,totalcycles,wpaddr,wpdata;wpdisable 4;g}']
    host='{{printf "H {0} %X %X'+NL+'",wpaddr,wpdata;symlist :maincpu;g}}'
    lines+=['wpset 187ff90:maincpu,10,w,1,'+host.format('io1'),'wpset 1680000:maincpu,20,w,1,'+host.format('dcs_w'),
            'wpset 1680000:maincpu,20,r,1,'+host.format('dcs_r'),'go']
    return '\n'.join(lines)+'\n'


def capture_pairs(seconds):
    """Runs pairs_script for `seconds`; returns compact executed pairs {(boot, pc, opcode): first totalcycles}, host events, first non-zero read."""
    if q.sha(reference.CORE)!=reference.CORE_SHA:raise ValueError('Reference core identity changed')
    roms.verify(ROOT/'roms/mk3')
    with q.scratch_tree() as (temp,cleanup):
        (temp/'nvram/mk3').mkdir(parents=True);(temp/'nvram/mk3/nvram').write_bytes(reference.SEED.read_bytes())
        (temp/'dcs.cmd').write_text(pairs_script(),encoding='ascii')
        run=q.command([reference.CORE,'mk3','-rompath',ROOT/'roms','-noreadconfig','-nowriteconfig','-skip_gameinfo','-noplugins',
                       '-video','none','-sound','none','-nothrottle','-debug','-debugger','windows','-debuglog','-debugscript','dcs.cmd',
                       '-nvram_directory','nvram','-cfg_directory','cfg','-homepath','home','-snapshot_directory','snap','-seconds_to_run',str(seconds)],
                      temp,cwd=temp,timeout=1800)
        if not run['passed']:raise RuntimeError('Reference run failed: '+run.get('stdout','')[-1000:])
        log=temp/'debug.log'
        if not log.is_file() or log.stat().st_size>96*1024*1024:raise ValueError('Missing or oversized debug.log')
        text=log.read_text('utf-8')
    if cleanup['exists_after']:raise ValueError('Reference scratch retained')
    pairs={};zero=[];host=parse(text,'',len(fields()))['host']
    for line in text.splitlines():
        v=line.strip().split()
        if v[:1]==['C']:pc,op,boot,cycle=(int(x,16) for x in v[1:]);pairs.setdefault((boot,pc,op&0xffffff),cycle)
        elif v[:1]==['Z']:zero.append([int(x,16) for x in v[1:]])
    return dict(pairs=pairs,host=host,nonzero=zero,wall_seconds=run['wall_seconds'],log_bytes=len(text),cleanup=cleanup)


def capture_interleave(windows,seconds):
    """Instruction-hook order of :maincpu and :dcs:dcs while the main CPU's totalcycles is in one of `windows`
    ([start, end) pairs), so the scheduler's timeslices show as runs: ('M', pc, totalcycles) before each main-CPU
    instruction, ('D', pc, boot-relative totalcycles) before each ADSP instruction, ('W', value, main-CPU totalcycles)
    per sound-port write, in execution order. printf arguments are evaluated in the visible CPU (:dcs:dcs): the main
    CPU's pc / totalcycles pass through temp7 / temp6, assigned in its registerpoint condition."""
    if q.sha(reference.CORE)!=reference.CORE_SHA:raise ValueError('Reference core identity changed')
    roms.verify(ROOT/'roms/mk3')
    inside='('+'||'.join(f'(totalcycles>=0x{a:x}&&totalcycles<0x{b:x})' for a,b in windows)+')'
    lines=['focus :maincpu','temp5=0',
           f'rpset ((temp6=totalcycles)|(temp7=pc)|1)&&{inside},{{temp5=1;printf "M %X %X{NL}",temp7,temp6;g}}',
           f'rpset temp5==1&&{inside}==0,{{temp5=0;g}}',
           'wpset 1680000,20,w,1,{printf "W %X %X'+NL+'",wpdata,temp6;g}',
           'focus :dcs:dcs',f'rpset temp5==1,{{printf "D %X %X{NL}",pc,totalcycles;g}}','observe :maincpu','go']
    with q.scratch_tree() as (temp,cleanup):
        (temp/'nvram/mk3').mkdir(parents=True);(temp/'nvram/mk3/nvram').write_bytes(reference.SEED.read_bytes())
        (temp/'order.cmd').write_text('\n'.join(lines)+'\n',encoding='ascii')
        run=q.command([reference.CORE,'mk3','-rompath',ROOT/'roms','-noreadconfig','-nowriteconfig','-skip_gameinfo','-noplugins',
                       '-video','none','-sound','none','-nothrottle','-debug','-debugger','windows','-debuglog','-debugscript','order.cmd',
                       '-nvram_directory','nvram','-cfg_directory','cfg','-homepath','home','-snapshot_directory','snap','-seconds_to_run',str(seconds)],
                      temp,cwd=temp,timeout=900)
        if not run['passed']:raise RuntimeError('Reference run failed: '+run.get('stdout','')[-1000:])
        text=(temp/'debug.log').read_text('utf-8')
    if cleanup['exists_after']:raise ValueError('Reference scratch retained')
    rows=[]
    for line in text.splitlines():
        v=line.strip().split()
        if v[:1] in (['M'],['D'],['W']):rows.append((v[0],int(v[1],16),int(v[2],16)))
        elif any(word in line.lower() for word in ('error','unknown','invalid','unbalanced')):raise ValueError('MAME diagnostic: '+line)
    return dict(rows=rows,wall_seconds=run['wall_seconds'],log_bytes=len(text),cleanup=cleanup)


def capture_tms_after_write(value,milliseconds=1,after=0):
    """Main-CPU instruction starts (totalcycles) for `milliseconds` after its first sound-port write of `value` at
    totalcycles >= `after`.

    The watchpoint stops the debugger at the hook of the instruction after the writing one; the trace starts with
    the instruction after that. Only the cycle list leaves the scratch tree.
    """
    if q.sha(reference.CORE)!=reference.CORE_SHA:raise ValueError('Reference core identity changed')
    with q.scratch_tree() as (temp,cleanup):
        (temp/'nvram/mk3').mkdir(parents=True);(temp/'nvram/mk3/nvram').write_bytes(reference.SEED.read_bytes())
        (temp/'tms.cmd').write_text('\n'.join(['focus :maincpu',f'wpset 1680000,20,w,wpdata==0x{value:x}&&totalcycles>=0x{after:x},{{printf "W %X'+NL+'",totalcycles;wpdisable}','go',
                                               'trace tms.tr,:maincpu,noloop,{tracelog "M %X'+NL+'",totalcycles}',f'gtime #{milliseconds}','quit'])+'\n',encoding='ascii')
        run=q.command([reference.CORE,'mk3','-rompath',ROOT/'roms','-noreadconfig','-nowriteconfig','-skip_gameinfo','-noplugins',
                       '-video','none','-sound','none','-nothrottle','-debug','-debugger','windows','-debuglog','-debugscript','tms.cmd',
                       '-nvram_directory','nvram','-cfg_directory','cfg','-homepath','home','-snapshot_directory','snap','-seconds_to_run','30'],
                      temp,cwd=temp,timeout=300)
        if not run['passed']:raise RuntimeError('Reference run failed: '+run.get('stdout','')[-1000:])
        write=[int(l.split()[1],16) for l in (temp/'debug.log').read_text('utf-8').splitlines() if l.startswith('W ')]
        starts=[int(l.split()[1],16) for l in (temp/'tms.tr').read_text('utf-8',errors='replace').splitlines() if l.startswith('M ')]
    if cleanup['exists_after']:raise ValueError('Reference scratch retained')
    if len(write)!=1 or not starts or starts!=sorted(starts):raise ValueError('Incomplete main-CPU boundary capture')
    return dict(write=write[0],starts=starts,wall_seconds=run['wall_seconds'])


if __name__=='__main__':
    import json
    data=capture()
    print(json.dumps({k:(len(v) if isinstance(v,list) else v) for k,v in data.items() if k!='fields'},indent=1))
    print(json.dumps(data['host']))
