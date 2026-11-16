"""MK1 qualified routes: replays from reset with recorded legal input tapes, Original and Remastered presentation.

Each route boots the product objects (tools/mk1/runtime-inputs.json minus the window/CLI/audio-device units) with the
generated includes and the CMOS seed of the setup (tools/setup/mk1.make_seed), runs `end_frame` frames with the legal
input tape tools/mk1/tapes/<route>.json (events: frame, requested_frames, input_mask) twice (Original, Remastered
fighter projection), and prints one comparison object: terminal state, raw raster and PCM equality between the two runs
plus frame, cycle, mode and scene counts. The committed expectation is the SHA-256 of that object in canonical JSON
(route_expected.json); raw observed values are not versioned.

    python tools/mk1/routes.py [route ...] [--report <json>] [--workers 2] [--seed <cmos file>]

Routes: two sessions with rounds (versus-a, versus-b) and their aligned variants, the finish/continue/reselect route
(finishing move, continue, character reselect) and a one-player campaign prefix/projection; PCM is compared sample by
sample for routes up to 12,000 frames and by 250-frame chunk digests beyond.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse,hashlib,json,os,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q

ROOT=q.ROOT
HERE=Path(__file__).resolve().parent
EXPECTED=HERE/'route_expected.json'
EXCLUDE=('probe_audio_main','mk5_boot_flow_cli','mk5_window','mk5_audio_output')
FLAGS=['-std=c++17','-O2','-DUNICODE','-D_UNICODE','-municode','-I'+str(ROOT/'native/include'),'-I'+str(ROOT/'native/audio'),
       '-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-missing-field-initializers','-pthread']


def expected():
    return json.loads(EXPECTED.read_text('utf-8'))


def tap_source():
    """mk5_scanout.cpp with a read-only diagnostic copy of the raw raster (before the blood/presentation layer)."""
    cpp=(ROOT/'native/src/mk5_scanout.cpp').read_text()
    marker='Mk5Scanout::Mk5Scanout('
    if cpp.count(marker)!=1:raise ValueError('mk5_scanout.cpp constructor marker')
    cpp=cpp.replace(marker,'''struct DiagnosticRaster{std::vector<uint32_t> work,complete;};
static std::map<const Mk5Scanout*,DiagnosticRaster> raw_rasters;
const std::vector<uint32_t>& DiagnosticRawRaster(const Mk5Scanout& screen){return raw_rasters.at(&screen).complete;}
'''+marker)
    for marker,insertion in [
        ('work.resize(width_*height_);','raw_rasters[this]=DiagnosticRaster{std::vector<uint32_t>(work.size()),{}};'),
        ('void Mk5Scanout::line(const Mk5ScanlineEvent& edge,const std::array<uint16_t,32>& io){','\n    auto& raw=raw_rasters.at(this);'),
        ('complete=work;','raw.complete=raw.work;'),
        ('work.at(pixel)=blood?blood:expand_rgb(color);','raw.work.at(pixel)=expand_rgb(color);')]:
        if cpp.count(marker)!=1:raise ValueError('mk5_scanout.cpp marker: '+marker)
        cpp=cpp.replace(marker,marker+insertion)
    return cpp


def harness():
    """C++ of the route probe (tools/mk1/route_probe.cpp)."""
    return (HERE/'route_probe.cpp').read_text('ascii')


def sources(scratch,exclude=EXCLUDE):
    objects=json.loads((ROOT/'tools/mk1/runtime-inputs.json').read_text('utf-8'))['objects']
    (scratch/'route-probe.cpp').write_text(harness(),encoding='ascii');(scratch/'mk5_scanout.cpp').write_text(tap_source(),encoding='ascii')
    return [scratch/'route-probe.cpp',scratch/'mk5_scanout.cpp']+[ROOT/p for p in objects if Path(p).stem not in exclude and Path(p).stem!='mk5_scanout']


def build(scratch,srcs=None):
    from tools.quality import cpp_build
    exe=scratch/'route-probe.exe';t=time.perf_counter()
    b=cpp_build.build(q.DEFAULT_CC,FLAGS,srcs or sources(scratch),['-lbcrypt','-luser32','-lwinmm'],exe,scratch,
                      env=dict(PATH=str(q.DEFAULT_CC.parent)),timeout=3600,compile_from_scratch=True)
    if not b['passed']:raise RuntimeError('route probe build failed: '+b.get('stdout','')[-2000:])
    return exe,round(time.perf_counter()-t,3)


def digest(comparison):
    return hashlib.sha256(json.dumps(comparison,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def render_tape(path):
    """The text the probe reads (header, then one tab-separated event per line, LF) from a JSON tape."""
    data=json.loads(Path(path).read_text('utf-8'))
    if data.get('columns')!=['frame','requested_frames','input_mask']:raise ValueError('tape columns: '+str(path))
    rows=['\t'.join(data['columns'])]+['\t'.join(str(int(v)) for v in e) for e in data['events'] if len(e)==3]
    if len(rows)!=len(data['events'])+1:raise ValueError('tape events: '+str(path))
    return ('\n'.join(rows)+'\n').encode('ascii')


def run(exe,name,scratch,env,seed):
    want=expected()['routes'][name];text=render_tape(HERE/'tapes'/(name+'.json'))
    if hashlib.sha256(text).hexdigest()!=want['tape_sha256']:raise ValueError('tape differs from route_expected.json: '+name)
    tape=scratch/f'tape-{name}.tsv';tape.write_bytes(text)
    t=time.perf_counter()
    r=q.command([exe,ROOT,tape,scratch,want['end_frame'],seed],scratch,cwd=ROOT,env=env,timeout=max(600,want['end_frame']//10),output_limit=256*1024)
    comp=next((json.loads(l) for l in r['stdout'].splitlines() if l.startswith('{')),None)
    got=digest(comp) if comp is not None else None
    return dict(end_frame=want['end_frame'],passed=r['passed'] and got==want['comparison_sha256'],executed=r['passed'],
                comparison_sha256=got,expected_sha256=want['comparison_sha256'],seconds=round(time.perf_counter()-t,3),
                execution=None if r['passed'] else q.compact(r))


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('routes',nargs='*');ap.add_argument('--report',type=Path);ap.add_argument('--workers',type=int,default=2)
    ap.add_argument('--seed',type=Path,help='CMOS image instead of the setup seed (diagnostics; expectations are for the setup seed)')
    a=ap.parse_args(argv);names=a.routes or list(expected()['routes'])
    from tools.setup import mk1
    mk1.inc_dir();seed=(a.seed or mk1.seed_path()).resolve()
    receipt=dict(schema='mk1-routes/1',passed=False,generated=mk1.files(),seed_sha256=q.sha(seed),cases={})
    try:
        with q.scratch_tree() as (scratch,cleanup):
            receipt['cleanup']=cleanup
            env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH'],'TEMP':str(scratch),'TMP':str(scratch),
                 'MK1_MUSIC_MODE':'original','MK1_GAME_VOLUME':'0','MK1_AUDIO_LATENCY':'safe'}
            exe,seconds=build(scratch);receipt.update(executable_sha256=q.sha(exe),build_seconds=seconds)
            with ThreadPoolExecutor(max_workers=max(1,min(a.workers,3))) as pool:
                for name,row in zip(names,pool.map(lambda n:run(exe,n,scratch,env,seed),names)):
                    receipt['cases'][name]=row
                    print(name,'PASS' if row['passed'] else 'FAIL',row['seconds'],flush=True)
        receipt['passed']=all(r['passed'] for r in receipt['cases'].values()) and cleanup.get('exists_after') is False
    except Exception as e:
        receipt['error']=repr(e)
    if a.report:a.report.write_text(json.dumps(receipt,indent=1)+'\n',encoding='utf-8')
    print(json.dumps({k:receipt[k] for k in ('passed','executable_sha256') if k in receipt}),receipt.get('error',''))
    return 0 if receipt['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
