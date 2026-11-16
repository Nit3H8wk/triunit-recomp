"""MK3 route verification by input tape, checkpoints and bisection (port of tools/mk2/replay.py to the checkpoint model).

A route is the reset of the authenticated MK3 2.1 set with the CMOS seed and default DIPs plus a legal input tape
(rows "cycle port value": from the first TMS instruction boundary at or after `cycle`, io port `port` (0 IN0, 1 IN1,
2 DSW, 3 IN2) reads the 16-bit active-low `value`). The empty tape is reset -> attract with every input at rest.

1. Native run (native/tests/mk3_replay_main.cpp over mk3::Board) to its frontier or horizon: records every STEP cycles.
2. One Original capture for the same schedule (tools/mk3/replay_reference.py), END at the native end, whole regions at
   END; reused in memory by every comparison of the route (negative controls included).
3. First differing record -> k-ary bisection: native and Original sub-captures of K evenly spaced checkpoints inside
   the bracketing interval, until the two bracketing boundaries are consecutive instructions (cycle and PC of the
   differing instruction). Then the fine window: every bus write and device read in that interval and the whole
   differing region at both boundaries, compared directly.
Nothing is written to disk but compact receipts; the native and Original outputs travel through pipes and the
debugger log of a scratch tree removed at once.
"""
from pathlib import Path
import argparse,hashlib,json,math,os,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.setup import mk3 as setup_mk3
from tools.mk3 import reference,reference_dma,replay_reference,replay_state,test_adsp

ROOT=Path(__file__).resolve().parents[2]
STEP=1<<17          # route checkpoint spacing in TMS cycles (~21 ms at 6.25 MHz)
K=16                # sub-checkpoints per bisection round
NEVER=1<<40
SOURCES=('mk3_adsp.cpp','mk3_program.cpp','mk3_dcs.cpp','mk3_cmos_check.cpp','mk3_pic.cpp')


class Native:
    """Builds native/tests/mk3_replay_main.cpp once into a scratch tree (compiler cache of tools/quality) and runs it.
    revision None: the working tree; a git revision (e.g. 'HEAD'): the executor sources of that commit, extracted into
    the scratch tree, so a closed stretch is checked against a fixed executor while other fronts edit the tree.
    profile 'game': every run uses mk3::Profile::Game (spec line `profile game`); its summary carries the first-execution log.
    Each run writes its spec into a scratch tree of its own (removed at once), so runs of one build may go in parallel."""
    def __init__(self,revision=None,profile='strict'):self.revision,self.profile=revision,profile
    def __enter__(self):
        self._tree=q.scratch_tree();self.temp,self.cleanup=self._tree.__enter__()
        cc=q.DEFAULT_CC;self.env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
        self.exe=self.temp/'mk3-replay.exe';base=ROOT
        if self.revision:
            base=self.temp/'src';self.source_identity=snapshot(self.revision,base)
        source=base/'native/mk3'
        if self.revision:
            build=q.command([cc,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-static','-I'+str(base/'native/include'),'-I'+str(source),
                             '-I'+str(base/'native/mk2'),setup_mk3.include(),ROOT/'native/tests/mk3_replay_main.cpp',*(source/n for n in SOURCES),
                             base/'native/mk2/mk2_dcs.cpp',base/'native/src/mk5_program.cpp','-lbcrypt','-o',self.exe],self.temp,cwd=ROOT,env=self.env,timeout=600)
        else:   # working tree: the whole-image TMS units of tools/mk3/generate.py with the bounded object cache
            from tools.mk3 import generate
            before=executor_files()
            build=generate.build(self.temp,[ROOT/'native/tests/mk3_replay_main.cpp',ROOT/'native/mk3/mk3_adsp.cpp',
                                            *(ROOT/'native/mk3'/n for n in generate.RUNTIME),ROOT/'native/mk2/mk2_dcs.cpp',
                                            ROOT/'native/src/mk5_program.cpp'],self.exe,unicode=False)
            g=build.get('generation') or {}
            self.source_identity=dict(tree='working',candidate_pcs=g.get('candidate_pcs'),cases=g.get('cases'))
            if build['passed']:
                if executor_files()!=before:self.__exit__(None,None,None);raise RuntimeError('executor sources changed during the build')
                units={'generated/'+p.name:q.sha(p) for p in sorted(self.temp.glob('*.cpp'))}
                self.source_identity['executor_sha256']=hashlib.sha256(json.dumps(sorted({**before,**units}.items())).encode()).hexdigest()
                self.source_identity['executor_files']=len(before)+len(units)
        if not build['passed']:self.__exit__(None,None,None);raise RuntimeError('native build failed: '+json.dumps(q.compact(build))[:3000])
        self.build_seconds=build['wall_seconds']
        (self.temp/'gfx.txt').write_text(''.join(f'{o} {s} {p}\n' for p,o,s in reference_dma.graphics_rows()),encoding='utf-8')
        self.runs=[];return self

    def __exit__(self,*_):
        self._tree.__exit__(None,None,None)
        if self.cleanup.get('exists_after'):raise RuntimeError('native scratch retained')

    def run(self,first,step,last,horizon=None,tape=(),dumps=(),window=None,mutations=(),points=(),events=False,first_all=False,windows=(),timeout=900,raw=False):
        """events: per-record event-stream segments and the whole streams (replay_state.STREAMS); first_all: the whole
        first-execution log (summary first_set); windows: several (lo, hi) bus windows (window: one); raw: the stdout text."""
        spec=[f'every {first} {step} {last}'] if step else []
        spec+=['profile game'] if self.profile=='game' else ['profile strict-routes'] if self.profile=='strict-routes' else []
        spec+=[f'horizon {horizon}'] if horizon else []
        spec+=[f'point {c}' for c in points]
        spec+=[f'tape {c} {p} {v}' for c,p,v in tape]+[f'dump {r} {c}' for r,c in dumps]+[f'mutate {w} {m} {c}' for w,m,c in mutations]
        spec+=[f'window {lo} {hi}' for lo,hi in ([window] if window else [])+list(windows)]
        spec+=['events'] if events else []
        spec+=['first all'] if first_all else []
        with q.scratch_tree() as (temp,cleanup):
            (temp/'spec.txt').write_text('\n'.join(spec)+'\n',encoding='ascii')
            run=q.command([self.exe,ROOT/'roms/mk3',reference.SEED,self.temp/'gfx.txt',temp/'spec.txt'],temp,cwd=ROOT,env=self.env,timeout=timeout,output_limit=256<<20)   # K3: 6-min tower routes print > 64 MB of records
        if cleanup.get('exists_after'):raise RuntimeError('native run scratch retained')
        if not run['passed'] or run['discarded_output_bytes']:raise RuntimeError('native replay failed: '+run['stdout'][-1500:])
        if raw:return run['stdout']
        out=replay_state.parse_native(run['stdout']);out['wall_seconds']=run['wall_seconds'];out['stdout_bytes']=len(run['stdout'])
        out['metrics']=run.get('metrics',{})
        self.runs.append(run['wall_seconds'])
        return out


class Explorer:
    """Exploration snapshot (K4 decision 3: search only, never an acceptance or a count). One mk3_replay_main process
    runs `tape` from reset to the first boundary >= `at` (spec `fork`), copies the Board and the harness there and serves
    branches (`serve`): each branch of run(...) continues its own copy of the snapshot, in parallel, with rows >= the
    snapshot cycle; its lines equal those of a run from reset of the whole tape (tools/mk3/test_snapshot.py).
    adopt(k) makes the copy that branch k kept before its horizon boundary the snapshot. lines: more base spec lines."""
    def __init__(self,native,tape,at,events=True,lines=()):
        self.native,self.tape,self.at,self.events,self.lines=native,tuple(map(tuple,tape)),at,events,list(lines)

    def __enter__(self):
        import subprocess
        self._tree=q.scratch_tree();temp,self.cleanup=self._tree.__enter__()
        spec=(['profile game'] if self.native.profile=='game' else ['profile strict-routes'] if self.native.profile=='strict-routes' else [])
        spec+=(['events'] if self.events else [])+self.lines+[f'tape {c} {p} {v}' for c,p,v in self.tape]+[f'fork {self.at}','serve']
        (temp/'spec.txt').write_text('\n'.join(spec)+'\n',encoding='ascii')
        self.p=subprocess.Popen([str(self.native.exe),str(ROOT/'roms/mk3'),str(reference.SEED),str(self.native.temp/'gfx.txt'),str(temp/'spec.txt')],
                                cwd=ROOT,env={**os.environ,**self.native.env},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
        self.header=self._line();self.base=[]
        while not (line:=self._line()).startswith('{"snapshot"'):self.base.append(line)
        self.snapshot=json.loads(line);self.last=self.tape[-1][0] if self.tape else 0
        return self

    def _line(self):
        line=self.p.stdout.readline()
        if not line:raise RuntimeError('explorer ended: '+self.p.stderr.read()[-1500:])
        return line.rstrip('\n')

    def run(self,branches):
        """branches: dicts of tape (rows at cycles >= the snapshot's `at` and >= every row so far), horizon, dumps
        [(region, cycle)], points, keep (a copy before the horizon boundary, for adopt), drop (negative control: 'latches').
        Returns per branch the replay_state.parse_native output (records from the snapshot on); self.raw: its lines."""
        lines=[]
        for b in branches:
            rows=tuple(map(tuple,b.get('tape',())))
            if rows and (rows[0][0]<max(self.at,self.last) or list(rows)!=sorted(rows,key=lambda r:r[0])):raise ValueError('branch rows before the snapshot')
            lines+=['branch']+[f'tape {c} {p} {v}' for c,p,v in rows]+[f'horizon {b["horizon"]}']+[f'point {c}' for c in b.get('points',())]
            lines+=[f'dump {r} {c}' for r,c in b.get('dumps',())]+(['keep'] if b.get('keep') else [])+([f'drop {b["drop"]}'] if b.get('drop') else [])
        self.rows=[tuple(map(tuple,b.get('tape',()))) for b in branches]
        t0=time.perf_counter();self.p.stdin.write('\n'.join(lines+['run'])+'\n');self.p.stdin.flush()
        outs=[]
        while not (line:=self._line()).startswith('{"ran"'):
            if line.startswith('{"branch"'):outs.append([])
            else:outs[-1].append(line)
        self.seconds=time.perf_counter()-t0;self.raw=outs
        return [replay_state.parse_native('\n'.join([self.header]+o)) for o in outs]

    def adopt(self,k):
        self.p.stdin.write(f'adopt {k}\n');self.p.stdin.flush()
        self.snapshot=json.loads(self._line());self.at=self.snapshot['at']
        if self.rows[k]:self.last=max(self.last,self.rows[k][-1][0])
        return self.snapshot

    def __exit__(self,*_):
        try:
            if self.p.poll() is None:self.p.stdin.write('quit\n');self.p.stdin.close()
            self.p.wait(timeout=60)
        except Exception:self.p.kill();self.p.wait()
        finally:
            for f in (self.p.stdout,self.p.stderr):f.close()
            self._tree.__exit__(None,None,None)
        if self.cleanup.get('exists_after'):raise RuntimeError('explorer scratch retained')


def executor_files():
    """sha256 of every hand source the working-tree executor compiles or includes (native/mk3, native/include, native/mk2
    headers and mk2_dcs.cpp, mk5_program.cpp, this runner) and the compiler binary; Native adds the generated units."""
    files=[p for d in ('native/mk3','native/include') for p in (ROOT/d).rglob('*') if p.is_file()]
    files+=[p for p in (ROOT/'native/mk2').glob('*') if p.suffix in ('.hpp','.h') or p.name=='mk2_dcs.cpp']
    files+=[ROOT/'native/src/mk5_program.cpp',ROOT/'native/tests/mk3_replay_main.cpp']
    out={p.relative_to(ROOT).as_posix():q.sha(p) for p in files}
    out.update(setup_mk3.identity_files())   # generated ADSP includes, under their former source-tree names
    out['compiler:'+q.DEFAULT_CC.name]=q.sha(q.DEFAULT_CC)
    return out


def snapshot(revision,target):
    """Executor sources of a git revision (native/mk3, native/mk2 headers + mk2_dcs.cpp, native/include, mk5_program.cpp)."""
    import io,subprocess,tarfile
    commit=subprocess.run(['git','rev-parse',revision],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
    data=subprocess.run(['git','archive','--format=tar',commit,'native/mk3','native/mk2','native/include','native/src/mk5_program.cpp'],
                        cwd=ROOT,capture_output=True,check=True).stdout
    keep=lambda n:n.startswith(('native/mk3/','native/include/','native/src/')) or n.endswith(('.hpp','.h','/mk2_dcs.cpp'))
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        members=[m for m in tar.getmembers() if m.isfile() and keep(m.name)]
        tar.extractall(target,members=members,filter='data')
    return dict(commit=commit,files=len(members),bytes=sum(m.size for m in members))


class Original:
    """Original captures keyed by their arguments: each distinct observation runs once per process."""
    def __init__(self):self.cache,self.runs={},[]
    def capture(self,*args,**kw):
        key=json.dumps([args,kw],sort_keys=True,default=list)
        if key not in self.cache:
            self.cache[key]=replay_reference.capture(*args,**kw);self.runs.append(self.cache[key]['wall_seconds'])
        return self.cache[key]


def masks(fields):return test_adsp.masks(fields)


def compare_records(nat,ref,ignore=()):
    fields=nat['fields'];m=masks(fields)
    return replay_state.first_difference(nat,ref,fields,m,ignore)


def route(native,original,tape=(),mutations=(),horizon=None,reference_tape=None,ignore=(),events=False):
    """Route replay: native records every STEP to its end, compared with the Original's; bisection on a difference.
    reference_tape (negative controls): the Original's tape when it differs from the native one.
    events: the event streams too (per-record segments; whole dcs/input/cmos streams compared directly at the end)."""
    reference_tape=tuple(map(tuple,tape if reference_tape is None else reference_tape))
    t0=time.perf_counter()
    dumps=[(r,0) for r in replay_state.REGIONS]
    nat=native.run(STEP,STEP,NEVER,horizon,tape,dumps,None,mutations,events=events,first_all=events)
    end=nat['records'][-1]['cycle']
    t1=time.perf_counter()
    ref=original.capture(STEP,STEP,end,end,reference_tape,tuple(dumps),**(dict(events=True) if events else {}))
    t2=time.perf_counter()
    diff=compare_records(nat,ref,ignore)
    streams=replay_state.stream_difference(nat,ref) if events else None
    integral=None
    if diff is None:
        integral={name:replay_state.byte_difference(nat['dumps'][(name,0)],data) for name,(dname,data) in zip(replay_state.REGIONS,ref['dumps'])}
        if any(dname!=name for name,(dname,_) in zip(replay_state.REGIONS,ref['dumps'])):raise ValueError('END dump order')
    t3=time.perf_counter()
    result=dict(records=len(nat['records']),end=dict(cycle=end,pc=nat['records'][-1]['pc'],instructions=nat['records'][-1]['instructions']),
                summary=nat['summary'],first_record_difference=None,end_integral=integral,streams=streams,
                compared_bytes={n:replay_state.REGION_BYTES[n]*len(nat['records']) for n in replay_state.REGIONS},
                timings=dict(native=nat['wall_seconds'],original=ref['wall_seconds'],compare=t3-t2),
                original_io=dict(stdout_bytes=ref['stdout_bytes'],log_bytes=ref['log_bytes'],cleanup=ref['cleanup']),
                native_stdout_bytes=nat['stdout_bytes'],identities=dict(core_sha256=ref['core_sha256'],program_sha256=ref['program_sha256'],
                seed_sha256=ref['seed_sha256'],debugger=ref['debugger']))
    if diff is not None:
        k,region,detail=diff
        result['first_record_difference']=dict(index=k,region=region,detail=detail,spec=nat['records'][k]['spec'] if k<len(nat['records']) else None)
        lo=nat['records'][k-1] if k else None
        hi_spec=nat['records'][k]['spec'] if k<len(nat['records']) else end
        if hi_spec=='end':hi_spec=end
        tb=time.perf_counter()
        result['bisection']=bisect(native,original,lo,hi_spec,tape,mutations,reference_tape,ignore,events)
        result['timings']['bisection']=time.perf_counter()-tb
    result['timings']['total']=time.perf_counter()-t0
    return result,nat,ref


def bisect(native,original,lo,hi,tape,mutations,reference_tape,ignore=(),events=False):
    """k-ary bisection between the equal native record `lo` (None: reset) and spec cycle `hi` (differing)."""
    lo_spec=lo['spec'] if lo else 1000
    rounds=[]
    tape=tuple(map(tuple,tape))
    while True:
        s=max(1,math.ceil((hi-lo_spec)/K))
        nat=native.run(lo_spec+s,s,hi,hi,tape,(),None,mutations,events=events)
        ref=original.capture(lo_spec+s,s,hi,hi,reference_tape,**(dict(events=True) if events else {}))
        diff=compare_records(nat,ref,ignore)
        if diff is None:raise ValueError(f'bisection round lost the difference in ({lo_spec}, {hi}]')
        k,region,detail=diff
        first=nat['records'][k]
        prev=nat['records'][k-1] if k else lo
        rounds.append(dict(lo=lo_spec,hi=hi,step=s,records=len(nat['records']),first=k,region=region,native_seconds=nat['wall_seconds'],
                           original_seconds=ref['wall_seconds']))
        new_hi=hi if first['spec']=='end' else first['spec']
        if prev is not None and first['instructions']-prev['instructions']<=1 or s==1:
            return dict(rounds=rounds,first_difference=dict(region=region,detail=detail,boundary_cycle=first['cycle'],boundary_pc=first['pc'],
                        boundary_instructions=first['instructions'],reference_cycle=ref['records'][k]['cycle'] if k<len(ref['records']) else None,
                        reference_pc=ref['records'][k]['pc'] if k<len(ref['records']) else None),
                        instruction=dict(cycle=prev['cycle'],pc=prev['pc'],instructions=prev['instructions']) if prev else None,
                        window=window(native,original,prev,first,region,tape,mutations,reference_tape) if prev else None)
        lo,lo_spec,hi=prev,(prev['spec'] if prev else lo_spec),new_hi
        if lo_spec=='end':raise ValueError('bisection reached END as an equal record')


def window(native,original,lo,hi,region,tape,mutations,reference_tape):
    """Fine window [lo, hi] boundary cycles: every bus write and device read, and the whole differing region at hi."""
    span=(lo['cycle'],hi['cycle'])
    dumps=((region,hi['cycle']),) if region in replay_state.REGIONS else ()
    nat=native.run(0,0,0,hi['cycle'],tape,dumps,span,mutations)
    ref=original.capture(1000,0,0,hi['cycle'],reference_tape,dumps,span)
    nw=nat['window'];rw=ref['window']
    # The Original exits some instructions after END: both sides keep the accesses of instructions starting before hi.
    inside=lambda rows:[r for r in rows if r[3]<span[1]]
    nw=dict(window=inside(nw['window']),reads=inside(nw['reads']));rw=dict(writes=inside(rw['writes']),reads=inside(rw['reads']))
    out=dict(cycles=list(span),native_writes=nw['window'][:32],reference_writes=rw['writes'][:32],native_reads=nw['reads'][:32],reference_reads=rw['reads'][:32],
             writes_equal=[w[1:] for w in nw['window']]==[w[1:] for w in rw['writes']],
             reads_equal=[r[1:] for r in nw['reads']]==[r[1:] for r in rw['reads']])
    if dumps:out['region_bytes']=replay_state.byte_difference(nat['dumps'][dumps[0]],ref['dumps'][0][1])
    return out


MAX_TAPE=8192   # R2 towers and R3 sessions (K3); the J1-K2 tapes stay within 512


def read_tape(path):
    rows=[]
    for line in Path(path).read_text('ascii').splitlines():
        if not line.strip() or line.startswith('#'):continue
        c,p,v=map(int,line.split())
        if c<1000 or not 0<=p<4 or not 0<=v<=0xffff or (rows and c<rows[-1][0]):raise ValueError('Invalid tape row '+line)
        rows.append((c,p,v))
    if len(rows)>MAX_TAPE:raise ValueError(f'Tape longer than {MAX_TAPE} events')
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tape',type=Path,help='input tape (empty: reset -> attract with inputs at rest)')
    parser.add_argument('--horizon',type=int,help='stop at the first boundary >= this TMS cycle')
    parser.add_argument('--revision',help="executor sources of this git revision (e.g. HEAD) instead of the working tree")
    parser.add_argument('--profile',choices=('strict','game','strict-routes'),default='strict',
                        help='execution profile of the native run (mk3_profile.hpp; strict-routes: Strict with the route-verified keys)')
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.report.exists():parser.error('Preserve the existing receipt; choose another --report')
    tape=read_tape(args.tape) if args.tape else []
    with Native(args.revision,args.profile) as native:
        result,_,_=route(native,Original(),tape,(),args.horizon)
        result['native_build_seconds']=native.build_seconds
    result['native_cleanup']=native.cleanup
    args.report.write_text(json.dumps(result,indent=1)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('end','first_record_difference','timings')}|dict(summary={k:v for k,v in result['summary'].items() if k!='dac_ns'}),indent=1))
    return 0 if result['first_record_difference'] is None and all(v is None for v in (result['end_integral'] or {}).values()) else 1


if __name__=='__main__':raise SystemExit(main())
