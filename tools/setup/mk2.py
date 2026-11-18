"""MK2 L3.1 in the local setup: every generated include of the product, written into generated/mk2/<program_sha256>/.

Sources of the includes (none of them is versioned):
  tools/mk2/generate_architectural.py   whole static closure (mk2_first_fight.inc) and the feature units of partitions.json
  tools/mk2/generate_adsp.py            DCS ADSP-2105 boot blocks (mk2_adsp_boot.inc) from the user's U2
  tools/mk2/generate_{first_fight,selection,prestart_wait}.py   expected-only CPU boundaries (*_bounds.inc)
and the factory CMOS seed (factory_seed(): the generated executor's cold boot, checked by SHA-256).
include() returns the compiler flag; the folder is rebuilt when absent or when an input of the generators changed.
"""
from pathlib import Path
import hashlib,json,os,shutil,time

from tools.setup import paths

ROOT=paths.ROOT
ROMS=ROOT/'roms/mk2'


# tools/mk2 modules the generators import (python -c "import tools.mk2.generate_architectural, ...; print(sys.modules)").
GENERATOR_MODULES=('generate_adsp','generate_architectural','generate_coin_accounting','generate_coin_pair','generate_coin_queue',
                   'generate_first_fight','generate_next_wait','generate_prestart_wait','generate_selection','generate_start_input',
                   'generate_start_release','generate_start_wait','generate_static_cfg','generate_task_batch',
                   'generate_valid_host_edges','generate_video_irq','offline_decode')


def stamp():
    """Digest of the versioned generator inputs: the tools/mk2 modules the generators import, the fact tables
    (tools/mk2/*.json) and the shared decoder sources. Other tools/mk2 edits do not trigger a regeneration."""
    from tools.quality import run as q
    from tools.setup import decoder
    files=sorted([*(ROOT/'tools/mk2'/(n+'.py') for n in GENERATOR_MODULES),*(ROOT/'tools/mk2').glob('*.json'),ROOT/'tools/setup/mk2.py'])
    text=json.dumps(dict(files={p.name:q.sha(p) for p in files},decoder=decoder.inputs()),sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def texts(roms=ROMS):
    """{include name: exact bytes} generated from the ROMs in `roms`."""
    from tools.mk2 import generate_architectural,generate_adsp,generate_first_fight,generate_selection,generate_prestart_wait
    from tools.mk2 import generate_video_irq as emitter
    rom=emitter.load_program(Path(roms))
    outputs,report=generate_architectural.generate(rom)
    if report['static_PCs']<=0:raise ValueError('MK2 static closure is empty')
    texts={p.name:text for p,text in outputs.items()}
    texts.update(generate_architectural.layout(texts['mk2_first_fight.inc']))
    out={name:text.replace('\n','\r\n').encode() for name,text in texts.items()}
    out['mk2_adsp_boot.inc']=generate_adsp.generate((Path(roms)/'su2.l1').read_bytes()).encode()
    crlf=lambda t:t.replace('\n','\r\n').encode()
    out['mk2_first_fight_bounds.inc']=crlf(generate_first_fight.generate_bounds())
    out['mk2_first_fight_high_punch_bounds.inc']=crlf(generate_first_fight.generate_high_punch_bounds())
    out['mk2_selection_bounds.inc']=crlf(generate_selection.generate_bounds())
    out['mk2_prestart_wait_bounds.inc']=crlf(generate_prestart_wait.generate_bounds())
    return out


def _locked(lock,work,timeout=1800):
    deadline=time.monotonic()+timeout
    while True:
        try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);break
        except FileExistsError:
            if time.monotonic()>deadline:raise RuntimeError('generated/mk2 is locked by another setup: '+str(lock))
            try:
                if time.time()-lock.stat().st_mtime>3600:lock.unlink(missing_ok=True)   # left by a killed process
            except FileNotFoundError:pass
            time.sleep(1)
    try:return work()
    finally:os.close(fd);lock.unlink(missing_ok=True)


def inc_dir(roms=ROMS):
    """generated/mk2/<sha>/ with every include, (re)written when absent or stale."""
    out=paths.output('mk2');out.mkdir(parents=True,exist_ok=True)
    if not paths.owned(out):raise RuntimeError('generated/mk2 is linked outside the project')
    marker=out/'includes.json';want=stamp()
    def fresh():return marker.is_file() and json.loads(marker.read_text('utf8')).get('stamp')==want
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
    """{native/mk2/<name>: sha256} of the generated includes (the names they had in the source tree)."""
    data=json.loads((inc_dir(roms)/'includes.json').read_text('utf8'))
    return {'native/mk2/'+n:d for n,d in data['files'].items()}


SEED_NAME='mk2-factory-default-cmos.bin'
SEED_LOGICAL='native/runtime/'+SEED_NAME   # name of the former versioned file in tools/acceptance/manifest.json
SEED_SOURCES=('tools/setup/mk2_factory_cmos.cpp','native/mk2/mk2_executor.cpp','native/mk2/mk2_task_batch.cpp',
              'native/mk2/mk2_program.cpp','native/mk2/mk2_dcs.cpp','native/mk2/mk2_adsp.cpp','native/src/mk5_program.cpp')
# The pinned seed is the NVRAM the pinned MAME wrote at the end of a 5-second run of the same cold boot (P1 High Punch
# at the factory message, no coin or start). It is the game's factory image, which the generated executor produces at
# its delivery boundary, plus one counter the game advances after the first draw: a 16-bit count at CMOS words
# 0xbc/0xbd (high, low byte) followed by its complement at 0xbe/0xbf. The executor's qualified cold route ends at the
# first draw (the counter is still 0 there); the count at the end of that run is a fact of the run, like a cycle count.
SEED_COUNTER_WORDS=(0xbc,0xbd,0xbe,0xbf)
SEED_RUN_COUNT=5


def seed_path():
    return paths.output('mk2')/SEED_NAME


def seed_sha256():
    return json.loads((ROOT/'tools/acceptance/manifest.json').read_text('utf-8'))['files'][SEED_LOGICAL]['sha256']


def seed_from_factory(image):
    """The pinned seed from the factory image of the cold boot (16384 bytes, the counter still cleared)."""
    image=bytearray(image)
    if len(image)!=16384:raise ValueError('MK2 factory CMOS image must hold 16384 bytes')
    words=[image[2*w]|image[2*w+1]<<8 for w in SEED_COUNTER_WORDS]
    if words!=[0,0,0xff,0xff]:raise ValueError('MK2 factory CMOS counter is not cleared at the delivery boundary')
    count=SEED_RUN_COUNT;complement=~count&0xffff
    for word,value in zip(SEED_COUNTER_WORDS,(count>>8,count&0xff,complement>>8,complement&0xff)):
        image[2*word]=value;image[2*word+1]=0
    return bytes(image)


def factory_seed(roms=ROMS):
    """generated/mk2/<sha>/mk2-factory-default-cmos.bin: the factory CMOS of the user's ROMs, produced by the generated
    executor (tools/setup/mk2_factory_cmos.cpp) and accepted only with the pinned SHA-256. Rebuilt when absent or different."""
    from tools.quality import run as q
    out=inc_dir(roms);target=out/SEED_NAME;want=seed_sha256()
    if target.is_file() and q.sha(target)==want:return target
    def work():
        if target.is_file() and q.sha(target)==want:return target
        scratch=out/'seed-build'
        if scratch.exists():shutil.rmtree(scratch)
        scratch.mkdir()
        if not paths.owned(scratch):raise RuntimeError('generated/mk2 is linked outside the project')
        try:
            env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH'],'TEMP':str(scratch),'TMP':str(scratch)}
            exe=scratch/'mk2_factory_cmos.exe'
            built=q.command([q.DEFAULT_CC,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-Inative/include','-I'+str(ROOT),
                             *[ROOT/p for p in SEED_SOURCES],'-lbcrypt','-o',exe],scratch,cwd=ROOT,env=env,timeout=1800)
            if not built['passed']:raise RuntimeError('MK2 factory CMOS tool build failed: '+json.dumps(q.compact(built))[:3000])
            ran=q.command([exe,Path(roms),scratch/'factory.bin'],scratch,cwd=ROOT,env=env,timeout=600)
            if not ran['passed']:raise RuntimeError('MK2 factory CMOS run failed: '+json.dumps(q.compact(ran))[:3000])
            data=seed_from_factory((scratch/'factory.bin').read_bytes())
            if hashlib.sha256(data).hexdigest()!=want:raise RuntimeError('MK2 factory CMOS differs from the pinned SHA-256')
            partial=out/(SEED_NAME+'.partial');partial.write_bytes(data);os.replace(partial,target)
        finally:shutil.rmtree(scratch,ignore_errors=True)
        return target
    return _locked(out/'.lock',work)


def units():
    """native/mk2/<name> of the generated first-fight page units (generate_architectural.layout), for source identities.
    No freshness check, as source(): builds regenerate through generated_flags; identities only need the names."""
    data=json.loads((paths.output('mk2')/'includes.json').read_text('utf8'))
    return ['native/mk2/'+n for n in sorted(data['files']) if n.endswith('.cpp')]


def source(relative):
    """Path of a source-tree name; a former native/mk2/*.inc, a generated page unit or the former versioned seed resolves
    to its generated file."""
    relative=Path(relative).as_posix()
    # No freshness check here (builds run inc_dir() through generated_flags); hashing only needs the location.
    generated=relative.endswith('.inc') or (Path(relative).name.startswith('mk2_first_fight_') and relative.endswith('.cpp'))
    if relative.startswith('native/mk2/') and generated:return paths.output('mk2')/Path(relative).name
    if relative==SEED_LOGICAL:return seed_path()
    return ROOT/relative
