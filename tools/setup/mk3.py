"""MK3 rev 2.1 in the local setup: ROM authentication, the ADSP-2105 blocks, the whole-image TMS34010 units and the
factory CMOS seed.

The TMS34010 units are written by tools/mk3/generate.py into each build's own scratch tree (or generated/ by the setup);
the two DCS ADSP-2105 includes live in generated/mk3/<program_sha256>/ and are rebuilt from the user's U2 whenever they are
absent or their generator changed. Compile mk3_adsp.cpp with include() among the flags.

The factory CMOS seed (SEED) is the game's own work: the compiled executable runs the user's program from a power-on with
a cleared CMOS (MAME nvram DEFAULT_ALL_0, midwunit.cpp), where the program finds its CMOS invalid, restores the factory
settings and waits for a button; one P1 High Punch (IN0 bit 4, active low) is held over frames 600-608 and the NVRAM is
saved after frame 2400, in the attract. factory_seed() writes it; the setup compares its SHA-256 with the acceptance.
"""
from pathlib import Path
import hashlib,json,os,time

from tools.setup import paths

ROOT=paths.ROOT
ROMS=ROOT/'roms/mk3'
ADSP_INCS=('mk3_adsp_boot.inc','mk3_adsp_bank1.inc')
SEED=paths.output('mk3')/'factory-default-cmos.bin'
SEED_BYTES=0xc000                       # 48 KiB Wolf-Unit CMOS, 0x01400000-0x0145ffff (24576 little-endian words)
SEED_PRESS,SEED_RELEASE,SEED_FRAMES=600,608,2400
SEED_HIGH_PUNCH=0x10


def _stamp(u2):
    from tools.quality import run as q
    return dict(generator_sha256=q.sha(ROOT/'tools/mk3/generate_adsp.py'),u2_sha256=hashlib.sha256(u2).hexdigest())


def adsp_texts(roms=ROMS):
    from tools.mk3 import generate_adsp
    u2=(Path(roms)/generate_adsp.U2).read_bytes()
    if hashlib.sha256(u2).hexdigest()!=generate_adsp.U2_SHA256:raise ValueError('MK3 U2 differs from rev 2.1')
    return {'mk3_adsp_boot.inc':generate_adsp.generate(u2),'mk3_adsp_bank1.inc':generate_adsp.generate_bank1(u2)},u2


def adsp_dir(roms=ROMS):
    """generated/mk3/<sha>/ holding both ADSP includes, (re)written when absent or stale."""
    out=paths.output('mk3');stamp_path=out/'adsp.json'
    from tools.mk3 import generate_adsp
    u2=(Path(roms)/generate_adsp.U2).read_bytes()
    if all((out/n).is_file() for n in ADSP_INCS) and stamp_path.is_file():
        if json.loads(stamp_path.read_text('utf8'))==_stamp(u2):return out
    texts,u2=adsp_texts(roms)
    out.mkdir(parents=True,exist_ok=True)
    if not paths.owned(out):raise RuntimeError('generated/mk3 is linked outside the project')
    for name,text in texts.items():
        partial=out/(name+'.partial');partial.write_text(text,encoding='utf-8',newline='\n');os.replace(partial,out/name)
    stamp_path.write_text(json.dumps(_stamp(u2)),encoding='utf-8')
    return out


def include(roms=ROMS):
    """Compiler flag that makes `#include "mk3_adsp_boot.inc"` / `"mk3_adsp_bank1.inc"` resolve to the generated files."""
    return '-I'+adsp_dir(roms).as_posix()   # forward slashes: compiler dependency output stays parseable


def identity_files(roms=ROMS):
    """{logical path: sha256} of the generated includes under the names they had in the source tree (executor and
    package identities stay comparable with builds made before the includes left Git)."""
    from tools.quality import run as q
    out=adsp_dir(roms)
    return {f'native/mk3/{n}':q.sha(out/n) for n in ADSP_INCS}


def factory_seed(exe,roms=ROMS):
    """Runs the compiled MK3 executable `exe` from a cleared CMOS through the factory-settings restore (module docstring)
    and writes SEED. Returns a compact receipt; refuses a stop at the translation frontier or an image of another size."""
    from tools.mk3 import reference_dma
    from tools.quality import run as q
    frame=506*289/8e6*6250000             # TMS cycles per frame: 506 x 289 raster at 8 MHz, TMS34010 at 6.25 MHz
    started=time.perf_counter()
    with q.scratch_tree() as (temp,cleanup):
        (temp/'cleared.bin').write_bytes(bytes(SEED_BYTES))
        (temp/'gfx.txt').write_text(''.join(f'{o} {s} {p}\n' for p,o,s in reference_dma.graphics_rows()),encoding='utf-8')
        (temp/'press.tape').write_text(f'{round(SEED_PRESS*frame)} 0 {0xffff^SEED_HIGH_PUNCH}\n{round(SEED_RELEASE*frame)} 0 {0xffff}\n',
                                       encoding='ascii')
        (temp/'profile').mkdir()
        env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH']}
        run=q.command([exe,Path(roms),temp/'cleared.bin',temp/'gfx.txt','--frames',str(SEED_FRAMES),'--tape',temp/'press.tape',
                       '--cmos-profile',temp/'profile'],temp,cwd=ROOT,env=env,timeout=600)
        summary=next((json.loads(l) for l in reversed(run['stdout'].splitlines()) if l.startswith('{"preview"')),None)
        if not run['passed'] or not summary or summary.get('frontier')!='none' or summary.get('frames')!=SEED_FRAMES:
            raise RuntimeError('MK3 factory seed run failed: '+run['stdout'][-1500:])
        image=(temp/'profile/cmos.bin').read_bytes()
    if cleanup.get('exists_after'):raise RuntimeError('MK3 factory seed scratch retained')
    if len(image)!=SEED_BYTES:raise RuntimeError(f'MK3 factory seed has {len(image)} bytes')
    SEED.parent.mkdir(parents=True,exist_ok=True)
    if not paths.owned(SEED.parent):raise RuntimeError('generated/mk3 is linked outside the project')
    partial=SEED.with_name(SEED.name+'.partial');partial.write_bytes(image);os.replace(partial,SEED)
    return dict(file=str(SEED.relative_to(ROOT)).replace('\\','/'),bytes=len(image),sha256=hashlib.sha256(image).hexdigest(),
                frames=SEED_FRAMES,press=[SEED_PRESS,SEED_RELEASE],tape_applied=summary['tape']['applied'],cycles=summary['cycles'],
                seconds=round(time.perf_counter()-started,1))


def seed():
    """SEED, once the setup wrote it."""
    if not SEED.is_file():raise FileNotFoundError(f'{SEED} is absent: run python tools/setup/setup.py --game mk3 --roms <folder>')
    return SEED
