"""MK1 rev 5.0 in the local setup: every generated include of the product, written into generated/mk1/<program_sha256>/.

Sources of the includes (none of them is versioned):
  tools/mk1/generate.py         TMS34010 main CPU: power-on, task-body and main-loop graphs
  tools/mk1/generate_audio.py   6809 sound CPU graph and its suspension checkpoints, from the user's U3
include() returns the compiler flag; the folder is rebuilt when absent or when an input of the generators changed.
After the engine is compiled, make_seed() writes the CMOS seed (factory-default-control-input.bin) next to the includes:
the game's own factory restore from a blank CMOS, run by the engine's factory-cmos stage. No CMOS image is versioned.
"""
from pathlib import Path
import hashlib,json,os,time

from tools.setup import paths

ROOT=paths.ROOT
ROMS=ROOT/'roms/mk1'
GENERATOR_FILES=('tools/mk1/generate.py','tools/mk1/generate_audio.py','tools/mk1/m6809.py','tools/mk1/roms.py',
                 'tools/mk1/partitions.json','tools/mk1/audio_nodes.json','tools/mk1/roms-l1.json','tools/setup/mk1.py',
                 'tools/mk2/offline_decode.py')
NAMES=('mk5_main_loop_graph.inc','mk5_task_body_graph.inc','mk5_boot_graph.inc',
       'mk5_audio_graph.inc','mk5_audio_checkpoints.inc')


def stamp():
    """Digest of the versioned generator inputs (modules, address tables, manifest) and of the decoder sources."""
    from tools.quality import run as q
    from tools.setup import decoder
    text=json.dumps(dict(files={n:q.sha(ROOT/n) for n in GENERATOR_FILES},decoder=decoder.inputs()),sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def texts(roms=ROMS):
    """{include name: exact bytes} generated from the ROMs in `roms`."""
    from tools.mk1 import generate,generate_audio,roms as mk1_roms
    out,report=generate.texts(mk1_roms.program_image(roms))
    # Main-loop and task-body graphs: at most one untranslated label. Power-on graph: only the POST/diagnostic
    # forms below stay untranslated (they stop at their own label if ever reached; normal power-on never is).
    boot=report.pop('mk5_boot_graph.inc')
    if any(r['unsupported']>1 for r in report.values()) or boot['unsupported']>6 or set(boot['forms'])-{'PIXT','CVXYL','DRAV','EXGF'}:
        raise ValueError('MK1 TMS graph lost translated forms: '+json.dumps(dict(report,boot=boot)))
    out.update(generate_audio.texts(mk1_roms.u3(roms)))
    if set(out)!=set(NAMES):raise ValueError('MK1 generator produced an unexpected include set')
    return {n:t.encode() for n,t in out.items()}


def _locked(lock,work,timeout=1800):
    deadline=time.monotonic()+timeout
    while True:
        try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);break
        except FileExistsError:
            if time.monotonic()>deadline:raise RuntimeError('generated/mk1 is locked by another setup: '+str(lock))
            try:
                if time.time()-lock.stat().st_mtime>3600:lock.unlink(missing_ok=True)   # left by a killed process
            except FileNotFoundError:pass
            time.sleep(1)
    try:return work()
    finally:os.close(fd);lock.unlink(missing_ok=True)


def inc_dir(roms=ROMS):
    """generated/mk1/<sha>/ with every include, (re)written when absent or stale."""
    out=paths.output('mk1');out.mkdir(parents=True,exist_ok=True)
    if not paths.owned(out):raise RuntimeError('generated/mk1 is linked outside the project')
    marker=out/'includes.json';want=stamp()
    def fresh():return marker.is_file() and json.loads(marker.read_text('utf8')).get('stamp')==want and all((out/n).is_file() for n in NAMES)
    if fresh():return out
    def work():
        if fresh():return out
        files=texts(roms)
        for name,data in files.items():
            partial=out/(name+'.partial');partial.write_bytes(data);os.replace(partial,out/name)
        marker.write_text(json.dumps(dict(stamp=want,files={n:hashlib.sha256(d).hexdigest() for n,d in sorted(files.items())}),indent=1),encoding='utf8')
        return out
    return _locked(out/'.lock',work)


def include(roms=ROMS):
    return '-I'+inc_dir(roms).as_posix()   # forward slashes: compiler dependency output stays parseable


def files(roms=ROMS):
    """{native/src/<name>: sha256} of the generated includes (the names they had in the source tree)."""
    data=json.loads((inc_dir(roms)/'includes.json').read_text('utf8'))
    return {'native/src/'+n:d for n,d in data['files'].items()}


SEED='factory-default-control-input.bin'
# One cabinet snapshot, as every MK1 consumer passes it: IN0..IN2 released, DSW FEFFh (coinage from the switches),
# IRQ/raster epoch of the product. The setup acceptance pins the SHA-256 of the image (tools/acceptance/generated.json).
FACTORY_ARGS=('--stage','factory-cmos','--irq-pending','0x400','--raster-next-line','1','--raster-quanta','6325',
              '--dsw-word','65279','--boot-dsw-word','65279','--task-dsw-word','65279')


def seed_path():
    """CMOS seed written by the setup: the game's own factory restore from a blank CMOS (make_seed)."""
    path=paths.output('mk1')/SEED
    if not path.is_file():raise SystemExit('MK1 CMOS seed missing: run python tools/setup/setup.py --game mk1 --roms <folder>')
    return path


def make_seed(engine,roms_root=ROOT/'roms'):
    """Runs the compiled engine's factory-cmos stage (generated power-on from a blank CMOS, rebooted once to the first
    task unchanged) and writes generated/mk1/<sha>/factory-default-control-input.bin. Returns (path, sha256)."""
    import subprocess
    from tools.quality import run as q
    out=paths.output('mk1');partial=out/(SEED+'.partial');partial.unlink(missing_ok=True)
    run=subprocess.run([str(engine),'--roms',str(roms_root),*FACTORY_ARGS,'--cmos-output',str(partial)],capture_output=True,text=True,timeout=600)
    line=next((json.loads(l) for l in run.stdout.splitlines() if l.startswith('{')),None)
    if run.returncode or not line or line.get('stop')!='factory-cmos' or not partial.is_file():
        partial.unlink(missing_ok=True);raise SystemExit('MK1 factory CMOS failed: '+(run.stderr or run.stdout)[-2000:])
    digest=q.sha(partial)
    if digest!=line['cmos_sha256']:partial.unlink(missing_ok=True);raise SystemExit('MK1 factory CMOS digest mismatch')
    os.replace(partial,out/SEED);return out/SEED,digest


def source(relative):
    """Path of a source-tree name; a former native/src/mk5_*.inc of NAMES resolves to its generated file."""
    relative=Path(relative).as_posix()
    if relative.startswith('native/src/') and Path(relative).name in NAMES:return paths.output('mk1')/Path(relative).name
    return ROOT/relative
