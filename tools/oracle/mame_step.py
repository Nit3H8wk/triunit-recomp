"""One TMS34010 instruction per vector in the pinned MAME 0.280, from a synthetic state written through its debugger.

Evidence class (one-day plan, decision D9): "tradução igual ao Original por instrução, estado sintético". Translator
evidence only, never route acceptance: nothing here marks a PC verified or touches the product.

    from tools.oracle import mame_step
    results = mame_step.run('mk3', [dict(id='v0', pc=0xff8003b0, st=0x10, regs={'b6': 5}, mem={}, watch=[])])

vector: id; pc (bit address of the instruction, executed from the authentic ROM loaded by MAME); st; regs (names a0-a14,
sp, b0-b14; missing = 0); mem {16-aligned bit address: word}; watch [bit addresses read back after the step]; io
{TMS34010 I/O register index 0-31: word} written before the step.
result: id, pc (after the step), st, regs (all 31), cycles (totalcycles delta), mem {watch address: word}, writes (count
of main-CPU write accesses MAME's watchpoint saw during the step), steps (debugger steps taken), error (None or text).

Transport and assumptions (each one checked or stated, nothing guessed):
- MAME runs `driver` with -debug and a -debugscript; the only output channel is -debuglog inside a q.scratch_tree
  (removed even on failure, the removal result is returned). Identity: core sha256 below; the caller's `verify`
  (default for mk3: tools/mk3/roms.verify) checks the ROM set. MK3 uses the factory CMOS seed as tools/mk3/reference.py;
  other drivers pass nvram=None (MAME default) or their own seed.
- The script focuses :maincpu (other CPUs are ignored by the debugger, not stopped); vector 0 is written in the first
  maincpu instruction hook after reset. Then a chain of registerpoints (script() docstring) runs the vectors without
  stopping: after each vector's single instruction the next hook prints its state and writes the next vector (A0-A14,
  SP, B0-B14, I/O registers, memory words, ST, PC) with debugger expressions; debugger accesses do not trigger the
  watchpoint. Long transitions are split by one execution of a ROM NOP (nop_pc, checked to read 0x0300), which changes
  only PC and the cycle count, both rewritten afterwards. Words a previous vector wrote and the current one neither
  seeds nor watches keep their value: a vector must seed every word its instruction can read (unseeded watched words
  are written 0); a read outside them reads what earlier vectors left, so a disagreement there is a test defect to
  reduce, not a translator verdict.
- Every I/O register any vector of the run names is written on every vector (0 when the vector does not name it).
- Interrupts: ST.IE is cleared by the caller's st or forced off here (IE_MASK) unless allow_ie=True for a vector
  (key 'allow_ie'); INTENB (I/O 0x11) is written 0 before every step, so a ST write by the instruction itself (EINT,
  POPST, PUTST, RETI) cannot take an interrupt either; INTPEND is left as is. NMI needs HSTCTLH bit 8, written 0.
- Restartable instructions (PIXBLT, FILL, LINE: 34010gfx.hxx eats m_gfxcycles against m_icount and leaves PC on the
  instruction with ST.P) are not guessed. A plain vector reports after one instruction hook; if PC is unchanged with
  ST.P (bit 25) set, the result carries an error (restarted). A vector with restart=True reports only when PC moved or
  ST.P cleared; each re-execution at the same PC with ST.P counts one more step in `steps`, cycles are the sum. ST.P
  is cleared in every vector's ST (a fresh instruction, not a continuation).
- Cycles are the maincpu totalcycles delta from the write of PC to the next instruction hook. A timeslice end after
  the instruction does not change the count (other CPUs run, then execute_run checks interrupts, off, and reaches the
  hook). `writes` counts write accesses seen by a never-stopping watchpoint over the whole space (16-bit accesses).
- Storage: a watchdog polls the debugger log and console output while MAME runs and kills the job above log_limit
  (256 MB) or the timeout; each chain registerpoint disables itself when it fires, and parse() rejects a result printed
  twice or for no vector ('looping chain').
- Every number in the generated debugger expressions carries 0x: a bare hex word such as b5 or a0 is a register name.
- Memory words are read and written as 16-bit words (w@) at 16-aligned bit addresses; the program space of the TMS34010
  is bit addressed in MAME (addrshift 3), so `w@` takes the bit address directly. This is validated by self_test().
"""
from pathlib import Path
import os,re,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.quality import run as q

CORE=Path('D:/Emuladores/Mame/mame2080/mame.exe')
CORE_SHA='84b690dad588253139ea49ae5e3c9fcddf9df7bcd526fccd1724ec7e09120dec'
REGISTERS=[f'a{i}' for i in range(15)]+['sp']+[f'b{i}' for i in range(15)]
IE_MASK=0x00200000;P_BIT=0x02000000
INTENB,HSTCTLH=0x11,0x10

def _mk3():
    from tools.mk3 import roms, reference
    return dict(nvram=reference.SEED,verify=lambda:roms.verify(ROOT/'roms/mk3'),
                nop_pc=0xff801400)   # NOP in the MK3 2.1 program ROM
DRIVERS={'mk3':_mk3}

def _setup(v,io_keys):
    """Debugger commands that write vector v's state, and the commands that must run last (ST, PC, counters)."""
    mem={a:w&0xffff for a,w in v.get('mem',{}).items()};watch=set(v.get('watch',()))
    for a in list(mem)+list(watch):
        if a&15:raise ValueError(f'{v["id"]}: unaligned word address {a:x}')
    if not re.fullmatch(r'[\w.:-]+',v['id']):raise ValueError('vector id: '+v['id'])
    st=v['st']&0xffffffff&~P_BIT
    if not v.get('allow_ie'):st&=~IE_MASK
    regs={k.lower():x for k,x in v.get('regs',{}).items()}
    if set(regs)-set(REGISTERS):raise ValueError(f'{v["id"]}: unknown registers {sorted(set(regs)-set(REGISTERS))}')
    io={k:0 for k in io_keys};io.update(v.get('io',{}))
    cmds=[f'{r}=0x{regs.get(r,0)&0xffffffff:x}' for r in REGISTERS]
    cmds+=[f'w@0x{0xc0000000+16*k:x}=0x{x&0xffff:x}' for k,x in sorted(io.items())]
    cmds+=[f'w@0x{a:x}=0' for a in sorted(watch-set(mem))]
    cmds+=[f'w@0x{a:x}=0x{x:x}' for a,x in sorted(mem.items())]
    return cmds,[f'st=0x{st:x}',f'pc=0x{v["pc"]&0xffffffff:x}','temp0=totalcycles','temp9=0','temp8=1']

def _report(v):
    """Debugger commands that print the state after vector v's instruction; the first two must run before any NOP."""
    fmt='OR_R %s %X %X %d %d %d '.replace('%s',v['id'])+' '.join(['%X']*15)
    cmds=[f'printf "{fmt}\\n",pc,st,totalcycles-temp0,temp8,temp9,{",".join(REGISTERS[:15])}',   # printf: 32 parameters at most
          f'printf "OR_B {v["id"]} {" ".join(["%X"]*16)}\\n",{",".join(REGISTERS[15:])}']
    watch=list(v.get('watch',()))
    for i in range(0,len(watch),24):   # watched words in groups: index of the first, then the values
        part=watch[i:i+24]
        cmds.append(f'printf "OR_M {v["id"]} {i} {" ".join(["%X"]*len(part))}\\n",'+','.join(f'w@0x{a:x}' for a in part))
    return cmds+[f'printf "OR_E {v["id"]}\\n"']

LINE_LIMIT=2000   # chain lines stay well below MAME's 4096-character command limit

def script(vectors,nop_pc):
    """Registerpoint chain (temp7 = stage number). The stage that follows vector i's instruction prints its result,
    then the stages write vector i+1 and resume at its PC. An action that resumes does not enter the debugger wait loop
    (a view refresh per stop, about 0.1 s with -debugger windows). A transition longer than one command line is split
    into stages separated by one execution of the NOP at nop_pc, which changes only PC and the cycle count; the last
    stage sets ST, PC and the counters."""
    io_keys={INTENB,HSTCTLH}|{k for v in vectors for k in v.get('io',{})}
    head=['focus :maincpu','wpset 0,ffffffff,w,(temp9=temp9+1)&0',   # counts main-CPU write accesses, never stops
          f'printf "OR_NOP %X\\n",w@0x{nop_pc:x}']
    out=[];stage=1;report_stage={};restarts=sum(1 for v in vectors if v.get('restart'))
    setups=[_setup(v,io_keys) for v in vectors]
    for i,v in enumerate(vectors):
        report_stage[i]=stage
        body=_report(v);final=[]
        if i+1<len(vectors):
            cmds,last=setups[i+1];body=body+cmds;final=last
        cur=body[:2];rest=body[2:];pc=v['pc']&0xffffffff
        # restart vectors: the first report stage waits until PC moved or ST.P cleared
        cond=[f'(temp7==0x{stage:x})&&((pc!=0x{pc:x})||((st&0x{P_BIT:x})==0))' if v.get('restart') else None]
        def close(tail=None):
            nonlocal cur,stage
            c=cond[0] or f'(temp7==0x{stage:x})';cond[0]=None
            # loop guard: a chain registerpoint fires once (registerpoints are numbered from 1 in creation order,
            # the restart counters first); a wrong number breaks the chain into missing results, never repeats one
            once=[f'rpdisable 0x{restarts+stage:x}']
            out.append(f'rpset {c},{{{";".join(once+cur+(tail if tail is not None else [f"pc=0x{nop_pc:x}",f"temp7=0x{stage+1:x}","g"]))}}}');stage+=1;cur=[]
        for c in rest:
            if len(';'.join(cur+[c]))+120>LINE_LIMIT:close()
            cur.append(c)
        if final and len(';'.join(cur+final))+100>LINE_LIMIT:close()
        close(final+[f'temp7=0x{stage+1:x}','g'] if final else [])
    for i,v in enumerate(vectors):   # restart counting (PIXBLT/FILL/LINE): a re-execution at the same PC with ST.P is one more step
        if v.get('restart'):
            pc=v['pc']&0xffffffff
            head.append(f'rpset (temp7==0x{report_stage[i]:x})&&(pc==0x{pc:x})&&((st&0x{P_BIT:x})!=0),{{temp8=temp8+1;g}}')
    tail=[]
    if vectors:   # vector 0: written by script lines while stopped; its report stage is stage 1
        cmds,last=setups[0];tail=cmds+last+['temp7=1','g']
    # MAME 0.280 crashes in text_buffer_print when the console buffer wraps while echoing long script lines
    # (ACCESS VIOLATION seen after ~1,400-1,900 rpset lines): `cls` every 200 lines keeps it from wrapping.
    body=head+out+tail
    lines=[x for i in range(0,len(body),200) for x in ['cls']+body[i:i+200]]+['quit']
    long=[l for l in lines if len(l)>LINE_LIMIT+200]
    if long:raise ValueError(f'debugger line of {len(long[0])} characters')
    return '\n'.join(lines)+'\n'

def parse(text,vectors):
    got={};ids={v['id']:v for v in vectors};nop=None
    for line in text.splitlines():
        line=line.strip()
        if line.startswith('OR_R '):
            _,vid,pc,st,cycles,steps,writes,*regs=line.split()
            if len(regs)!=15:raise ValueError('truncated result: '+line[:300])
            if vid in got or vid not in ids:raise ValueError('looping chain: result '+vid+(' printed twice' if vid in got else ' of no vector'))
            got[vid]=dict(id=vid,pc=int(pc,16),st=int(st,16),cycles=int(cycles),steps=int(steps),writes=int(writes),
                          regs=dict(zip(REGISTERS,(int(r,16) for r in regs))),mem={},error=None,_end=False)
        elif line.startswith('OR_B '):
            _,vid,*regs=line.split()
            if len(regs)!=16:raise ValueError('truncated result: '+line[:300])
            got[vid]['regs'].update(zip(REGISTERS[15:],(int(r,16) for r in regs)))
        elif line.startswith('OR_M '):
            _,vid,i,*xs=line.split();watch=list(ids[vid].get('watch',()));i=int(i)
            got[vid]['mem'].update(zip(watch[i:i+len(xs)],(int(x,16) for x in xs)))
        elif line.startswith('OR_E '):got[line.split()[1]]['_end']=True
        elif line.startswith('OR_NOP '):nop=int(line.split()[1],16)
        elif re.search(r'error|unknown|invalid',line,re.I) and not line.startswith('>'):raise ValueError('MAME diagnostic: '+line)
    if vectors and nop!=0x0300:raise ValueError(f'no NOP opcode at nop_pc (read {nop})')
    out=[]
    for v in vectors:
        r=got.get(v['id'])
        if r is None or not r.pop('_end'):out.append(dict(id=v['id'],error='no result'));continue
        if r['pc']==v['pc']&0xffffffff and r['st']&P_BIT:r['error']='restarted (PC unchanged, ST.P set): rerun with restart=True'
        out.append(r)
    return out

def _launch(args,temp,timeout,log_limit):
    """MAME in an owned job (q.ProcessJob: closing it kills the whole tree). Every 0.5 s the debugger log and the
    console output are measured; above log_limit bytes, or past `timeout` seconds, the job is terminated."""
    started=time.perf_counter();killed=None;job=q.ProcessJob();size=0
    out=temp/'stdout.txt'
    env=dict(os.environ,TEMP=str(temp),TMP=str(temp))
    with out.open('wb') as stream:
        process=subprocess.Popen(list(map(str,args)),cwd=temp,env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,creationflags=4)
        try:
            job.assign(process);job.resume(process)
            while process.poll() is None:
                log=temp/'debug.log'
                size=(log.stat().st_size if log.is_file() else 0)+out.stat().st_size
                if size>log_limit:killed='debugger log over limit';break
                if time.perf_counter()-started>timeout:killed='timeout';break
                try:process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:pass
        finally:
            job.close()
            if process.poll() is None:process.kill()
            process.wait(timeout=10)
            log=temp/'debug.log'
            for _ in range(200):   # a killed process can hold the log open a little longer: the scratch removal needs it closed
                try:
                    if log.is_file():os.rename(log,temp/'debug.probe');os.rename(temp/'debug.probe',log)
                    break
                except OSError:time.sleep(0.05)
    text=out.read_bytes()[-4096:].decode('utf-8','replace')
    return dict(passed=process.returncode==0 and not killed,killed=killed,log_bytes=size,stdout=text,
                wall_seconds=round(time.perf_counter()-started,3))

def run(driver,vectors,*,timeout=1800,rompath=None,nvram='default',verify='default',nop_pc='default',core=CORE,log_limit=256*1024*1024):
    """Results in vector order and the run receipt: (results, receipt). One MAME process for all vectors.
    nvram: a CMOS/NVRAM file written as nvram/<driver>/nvram, None for MAME's default, 'default' for the driver's.
    verify: callable checking the ROM set (returns a JSON-able identity), None to skip, 'default' for the driver's.
    nop_pc: bit address of a NOP (0x0300) in the driver's program ROM, checked through the debugger.
    log_limit: bytes of debugger log plus console output at which the watchdog kills MAME and run() raises."""
    if q.sha(core)!=CORE_SHA:raise ValueError('Reference core identity changed')
    if len({v['id'] for v in vectors})!=len(vectors):raise ValueError('duplicate vector ids')
    profile=DRIVERS[driver]() if driver in DRIVERS else {}
    if nvram=='default':nvram=profile.get('nvram')
    if verify=='default':verify=profile.get('verify')
    identity=verify() if verify else None
    if nop_pc=='default':nop_pc=profile['nop_pc']
    with q.scratch_tree() as (temp,cleanup):
        if nvram:(temp/'nvram'/driver).mkdir(parents=True);(temp/'nvram'/driver/'nvram').write_bytes(Path(nvram).read_bytes())
        (temp/'oracle.cmd').write_text(script(vectors,nop_pc),encoding='ascii')
        result=_launch([core,driver,'-rompath',rompath or ROOT/'roms','-noreadconfig','-nowriteconfig','-skip_gameinfo','-noplugins',
                        '-video','none','-sound','none','-nothrottle','-debug','-debugger','windows','-debuglog','-debugscript','oracle.cmd',
                        '-nvram_directory','nvram','-cfg_directory','cfg','-homepath','home','-snapshot_directory','snap','-seconds_to_run','600'],
                       temp,timeout,log_limit)
        log=temp/'debug.log'
        if result['killed']:raise RuntimeError(f"MAME stopped by the watchdog: {result['killed']} (log {result['log_bytes']} bytes)")
        if not log.is_file():raise RuntimeError('Missing debugger log: '+result['stdout'][-500:])
        text=log.read_text('utf-8',errors='replace')
        results=parse(text,vectors)
    if cleanup['exists_after']:raise RuntimeError('Oracle scratch retained')
    receipt=dict(core_sha256=CORE_SHA,driver=driver,identity=identity,debugger=text.splitlines()[0] if text else None,
                 vectors=len(vectors),wall_seconds=result.get('wall_seconds'),exit_passed=result['passed'],cleanup=cleanup,
                 missing=sum(1 for r in results if r['error']=='no result'))
    if receipt['missing']:receipt['log_tail']=text.splitlines()[-12:]+[result['stdout'][-400:]]
    return results,receipt

def self_test():
    """Transport check on mk3: MOVE B6,A13 at 0xff8003b0 (route-verified site) must copy B6 to A13 with N/Z and
    V cleared (34010ops.hxx move_rr); a word written to RAM must read back unchanged; MOVE *A8(160h),A0,0 at 0xff801480
    must load the seeded field."""
    vs=[dict(id='mov',pc=0xff8003b0,st=0x10,regs={'b6':0x89abcdef,'a13':0x1234},mem={},watch=[]),
        dict(id='mem',pc=0xff8003b0,st=0x10,regs={'b6':0},mem={0x01000100:0xbeef},watch=[0x01000100]),
        dict(id='ld',pc=0xff801480,st=0x10,regs={'a8':0x01000200-0x160},mem={0x01000200:0x1357},watch=[])]
    results,receipt=run('mk3',vs)
    return results,receipt

# ---------------------------------------------------------------- DCS ADSP-2105 target (:dcs:dcs)
# Same evidence class (D9: synthetic state, one instruction per step, pinned MAME 0.280); translator evidence only.
# block: id; pc; regs {MAME ADSP state name: value} (missing = 0; MSTAT is written first, so the primary/secondary
# register banks are the ones the block names; L before I, so each I import sees its L); stack [return PCs, bottom
# first]; pm {PM word address: 24-bit word} (internal 0x0000-0x03ff, external 0x0800-0x0fff); dm {DM word address:
# word}; steps N; watch [DM addresses read back after every step]; after {k: {name: value}} (optional) written once
# the state after k steps is reported (e.g. {'IRQ2': 1}: MAME takes an unmasked IRQ2 on the write itself).
# MAME exposes PCSP but not the PC stack itself: each stack entry R is pushed by executing an encoded `CALL` (always
# condition) written at R-1, then PM[R-1] is written back to the block's word. Every other value is written through
# the debugger after the pushes, the IRQ lines and IMASK included, so the stack preamble leaves no other trace.
# result per block: rows[k] = the state after k steps (k=0: start) as {name: value, 'cycles': totalcycles delta},
# writes = [(step, pc, address, value)] seen by a data-space write watchpoint (debugger accesses do not trigger it),
# mem[k] = {watched address: word}.
DCS_REGISTERS=(['PC','AR','SI','PX','CNTR','ASTAT','SSTAT','MSTAT','IMASK','ICNTL','PCSP','CNTRSP','LOOPSP','STATSP','IRQ2']+
    [f'I{n}' for n in range(8)]+[f'M{n}' for n in range(8)]+[f'L{n}' for n in range(8)]+
    'AX0 AX1 AY0 AY1 AF MX0 MX1 MY0 MY1 MR0 MR1 MR2 MF SE SB SR0 SR1'.split()+
    [n+'_SEC' for n in 'AX0 AX1 AY0 AY1 AR AF MX0 MX1 MY0 MY1 MR0 MR1 MR2 MF SI SE SB SR0 SR1'.split()])
DCS_CALL=0x1c000f   # CALL <address> with condition 15 (always): 0001 11 aaaaaaaaaaaaaa 1111 (adsp2100.cpp)

def _dcs_block(b):
    vid=b['id']
    if not re.fullmatch(r'[\w.:-]+',vid):raise ValueError('block id: '+vid)
    regs={k.upper():v for k,v in b.get('regs',{}).items()}
    if set(regs)-set(DCS_REGISTERS)-{'IRQ0','IRQ1'}:raise ValueError(f'{vid}: unknown registers {sorted(set(regs)-set(DCS_REGISTERS))}')
    # IMASK and the IRQ lines are cleared before the stack preamble and written last (lines, ICNTL, then IMASK): each
    # of them calls check_irqs() on import (adsp2100.cpp state_import), so no interrupt is taken while the block is set.
    cmds=['imask=0x0','irq0=0x0','irq1=0x0','irq2=0x0','pcsp=0']
    for r in b.get('stack',()):
        if not 1<=r<=0x3fff:raise ValueError(f'{vid}: stack entry {r:x}')
        cmds+=[f'pd@0x{r-1:x}=0x{DCS_CALL|(r&0x3fff)<<4:x}',f'pc=0x{r-1:x}','step']
    if len(b.get('stack',()))>16:raise ValueError(f'{vid}: PC stack holds 16 entries')
    cmds+=[f'pd@0x{a:x}=0x{w&0xffffff:x}' for a,w in sorted(b.get('pm',{}).items())]
    cmds+=[f'dw@0x{a:x}=0x{w&0xffff:x}' for a,w in sorted(b.get('dm',{}).items())]
    late=('IRQ0','IRQ1','IRQ2','ICNTL','IMASK')
    order=['MSTAT']+[f'L{n}' for n in range(8)]+[n for n in DCS_REGISTERS if n not in ('MSTAT','PC','PCSP',*late) and not n.startswith('L')]
    cmds+=[f'{n.lower()}=0x{regs.get(n,0)&0xffffffff:x}' for n in (*order,*late)]
    after={int(k):{n.upper():v for n,v in w.items()} for k,w in b.get('after',{}).items()}
    for k,w in after.items():
        if not 0<k<b['steps'] or set(w)-set(DCS_REGISTERS)-{'IRQ0','IRQ1'}:raise ValueError(f'{vid}: after-step write {k} {sorted(w)}')
    cmds+=[f'pc=0x{b["pc"]:x}','temp0=totalcycles','temp7=0',
           f'wpdset 0,4000,w,1,{{printf "OR_W {vid} %X %X %X %X\\n",temp7,curpc,wpaddr,wpdata}}']
    def report():
        out=[]
        for i in range(0,len(DCS_REGISTERS),28):
            part=DCS_REGISTERS[i:i+28]
            out.append(f'printf "OR_D {vid} %X {i} '+' '.join(['%X']*len(part))+'\\n",temp7,'+','.join(p.lower() for p in part))
        out.append(f'printf "OR_C {vid} %X %X\\n",temp7,totalcycles-temp0')
        watch=list(b.get('watch',()))
        for i in range(0,len(watch),24):
            part=watch[i:i+24]
            out.append(f'printf "OR_M {vid} %X {i} '+' '.join(['%X']*len(part))+'\\n",temp7,'+','.join(f'dw@0x{a:x}' for a in part))
        return out
    cmds+=report()
    for k in range(b['steps']):
        # after {k: {name: value}}: written once row k is reported, before step k+1 (an IRQ line write dispatches
        # through check_irqs() at once, so the next step runs the vector).
        cmds+=[f'{n.lower()}=0x{v&0xffffffff:x}' for n,v in after.get(k,{}).items()]
        cmds+=['temp7=temp7+1','step']+report()
    return cmds+['wpclear',f'printf "OR_E {vid}\\n"']

def dcs_script(blocks,settle_ms):
    body=['focus :dcs:dcs',f'gtime {settle_ms}']+[c for b in blocks for c in _dcs_block(b)]
    long=[l for l in body if len(l)>LINE_LIMIT]
    if long:raise ValueError(f'debugger line of {len(long[0])} characters')
    return '\n'.join(x for i in range(0,len(body),200) for x in ['cls']+body[i:i+200])+'\nquit\n'

def dcs_parse(text,blocks):
    got={b['id']:dict(id=b['id'],rows={},mem={},writes=[],error=None,_end=False) for b in blocks}
    watch={b['id']:list(b.get('watch',())) for b in blocks}
    for line in text.splitlines():
        line=line.strip();head=line.split()[:1]
        if head==['OR_D']:
            _,vid,k,i,*xs=line.split();k,i=int(k,16),int(i)
            got[vid]['rows'].setdefault(k,{}).update(zip(DCS_REGISTERS[i:i+len(xs)],(int(x,16) for x in xs)))
        elif head==['OR_C']:
            _,vid,k,c=line.split();got[vid]['rows'].setdefault(int(k,16),{})['cycles']=int(c,16)
        elif head==['OR_M']:
            _,vid,k,i,*xs=line.split();k,i=int(k,16),int(i)
            got[vid]['mem'].setdefault(k,{}).update(zip(watch[vid][i:i+len(xs)],(int(x,16) for x in xs)))
        elif head==['OR_W']:
            _,vid,k,pc,a,v=line.split();got[vid]['writes'].append(tuple(int(x,16) for x in (k,pc,a,v)))
        elif head==['OR_E']:got[line.split()[1]]['_end']=True
        elif re.search(r'error|unknown|invalid',line,re.I) and not line.startswith('>'):raise ValueError('MAME diagnostic: '+line)
    out=[]
    for b in blocks:
        r=got[b['id']]
        complete=r.pop('_end') and sorted(r['rows'])==list(range(b['steps']+1)) and all(
            len(row)==len(DCS_REGISTERS)+1 for row in r['rows'].values())
        if not complete:r['error']='incomplete result'
        out.append(r)
    return out

def run_dcs(blocks,*,rompath,verify,settle_ms=3000,timeout=600,core=CORE,log_limit=64*1024*1024):
    """Results in block order and the receipt, one MAME process (mk2 driver, MAME's default NVRAM)."""
    if q.sha(core)!=CORE_SHA:raise ValueError('Reference core identity changed')
    if len({b['id'] for b in blocks})!=len(blocks):raise ValueError('duplicate block ids')
    identity=verify()
    with q.scratch_tree() as (temp,cleanup):
        (temp/'oracle.cmd').write_text(dcs_script(blocks,settle_ms),encoding='ascii')
        result=_launch([core,'mk2','-rompath',rompath,'-noreadconfig','-nowriteconfig','-skip_gameinfo','-noplugins',
                        '-video','none','-sound','none','-nothrottle','-debug','-debugger','windows','-debuglog','-debugscript','oracle.cmd',
                        '-nvram_directory','nvram','-cfg_directory','cfg','-homepath','home','-snapshot_directory','snap','-seconds_to_run','600'],
                       temp,timeout,log_limit)
        log=temp/'debug.log'
        if result['killed']:raise RuntimeError(f"MAME stopped by the watchdog: {result['killed']} (log {result['log_bytes']} bytes)")
        if not log.is_file():raise RuntimeError('Missing debugger log: '+result['stdout'][-500:])
        text=log.read_text('utf-8',errors='replace')
        results=dcs_parse(text,blocks)
    if cleanup['exists_after']:raise RuntimeError('Oracle scratch retained')
    return results,dict(core_sha256=CORE_SHA,driver='mk2',cpu=':dcs:dcs',identity=identity,blocks=len(blocks),
                        wall_seconds=result.get('wall_seconds'),exit_passed=result['passed'],cleanup=cleanup,
                        errors=[r['id'] for r in results if r['error']])

if __name__=='__main__':
    import json
    r,rec=self_test();print(json.dumps(dict(results=r,receipt=rec),indent=1,default=str))
