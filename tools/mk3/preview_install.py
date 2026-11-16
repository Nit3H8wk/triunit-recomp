"""MK3 native package: dry-run plan, staging and install (the file keeps its J3 name; D2 of 14/11/2026).

    python tools/mk3/preview_install.py              # DRY-RUN: the files of the package (nothing written)
    python tools/mk3/preview_install.py --swap-plan  # DRY-RUN: what --install changes on this root, and the way back
    python tools/mk3/preview_install.py --install    # installs (needs the user's OK), receipt build/native/mk3-native/install.json

Package (the build/native/mk2-native-v1 pattern): build/native/mk3-native/product with mk3.exe, package.ini
(kind=mk3-native, readiness=product), hard-linked authenticated ROMs, roms.txt, gfx.txt, factory-seed.bin,
package-identity.json and profiles/player; the MK3 launcher profile in build/native/mk3-native/profile/launcher.ini; logs in
logs/mk3-native.

--install builds the product, then triunit.exe in scratch (MK3 card: the two native editions only; the temporary
core is no longer offered, D1 of 14/11/2026), keeps the previous launcher for rollback, and requires on the real root the
lifecycle of both editions through the C++ backend (native/tests/mk3_launcher_tests.cpp native) and the MK1 launcher smoke.
Any failure restores the previous launcher and the previous package. On a reinstall the player's CMOS of the previous package
is copied into the new one (carry). The MK1/MK2 profiles and packages (PRESERVED) are hashed before and after and are never
written, moved or deleted. The temporary core (tools/mk3_arcade, build/native/mk3-arcade-v1) and the package of 13/11/2026
(build/native/mk3-native-preview) were removed after F6 with the user's OK; their CMOS and launcher.ini had been migrated.
"""
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import preview,reference,reference_dma,roms
import runpy

ROOT=preview.ROOT
STAGE=Path('build/native/mk3-native')
PRODUCT=STAGE/'product'
PROFILE=STAGE/'profile/launcher.ini'
EXE='mk3.exe'
LABEL='MK3 nativo'
PLAYER_CMOS=Path('profiles/player/cmos.bin')
LAUNCHER=ROOT/'triunit.exe'
LIBS=['d3d12','dxgi','d3dcompiler','dxguid','windowscodecs','ole32','uuid','gdi32','user32','shell32','xinput9_1_0']
arguments=runpy.run_path(str(ROOT/'tools/launcher_backend_build.py'))['arguments']
# Hashed before and after --install: the MK1/MK2 profiles and packages.
PRESERVED=['build/native/manual-temporary-8-20261025/profile','build/native/mk2-arcade-v1/profile','build/native/mk2-native-v1/product/profiles',
           'build/native/mk2-native-v1/product/native-package.ini','build/native/mk2-native-v1/product/mk2-native.exe','build/native/mk2-arcade-v1/product/manifest.json']
KEPT=['triunit.exe','build/native/mk2-native-v1/product','build/native/mk2-arcade-v1/product','build/native/manual-temporary-8-20261025/profile']
IDENTITY='package-identity.json'


def linked(path):
    return any(p.is_symlink() or p.is_junction() for p in (path,*path.parents))


def unlinked(path):
    if linked(path):raise RuntimeError('Linked path rejected: '+str(path))


def tree(path):
    path=ROOT/path
    if path.is_file():return {str(path.relative_to(ROOT)):q.sha(path)}
    return {str(p.relative_to(ROOT)):q.sha(p) for p in sorted(path.rglob('*')) if p.is_file()} if path.is_dir() else {}


def snapshot():return {k:v for p in PRESERVED for k,v in tree(p).items()}


def plan():
    manifest=json.loads(roms.MANIFEST.read_text('utf-8'));identity=roms.verify(ROOT/'roms/mk3',manifest)
    files=[]
    def add(target,source=None,how='copy',**extra):
        dest=ROOT/target
        files.append(dict(target=target.as_posix(),action=how,source=source and Path(source).relative_to(ROOT).as_posix(),
                          exists_now=dest.exists(),linked_path=linked(dest),**extra))
    add(PRODUCT/EXE,how='build (tools/mk3/preview.py Preview: whole-image TMS units + host sources, generate.FLAGS)',
        sources={s:q.sha(ROOT/s) for s in preview.SOURCES},sha256='computed at install from the built file')
    add(PRODUCT/'factory-seed.bin',reference.SEED,bytes=reference.SEED.stat().st_size,sha256=q.sha(reference.SEED))
    for rom in manifest['roms']:
        add(PRODUCT/'roms/mk3'/rom['path'],ROOT/'roms/mk3'/rom['path'],how='hard link (no payload copy)',bytes=rom['size'],sha256=rom['sha256'])
    add(PRODUCT/'roms.txt',how='write',content_lines=len(manifest['roms']))
    gfx=''.join(f'{o} {s} roms/mk3/{Path(p).name}\n' for p,o,s in reference_dma.graphics_rows())
    add(PRODUCT/'gfx.txt',how='write',content_lines=gfx.count('\n'),content_head=gfx.splitlines()[:2])
    add(PRODUCT/'package.ini',how='write',content=ini(identity,'<sha256 of the built file>'))
    add(PRODUCT/IDENTITY,how='write (sources, generated units, ROM and asset SHA-256; not read by the launcher)',sources=len(package_identity()['sources']))
    add(PRODUCT/'profiles/player',how='create empty directory (cmos.bin, 49152 bytes, written at the first exit from the seed)')
    add(PRODUCT/PLAYER_CMOS,how='reinstall only: copied from the previous package (moved to build/native/mk3-native/rollback)')
    add(Path('logs/mk3-native'),how='created by the launcher at the first launch (launcher-latest.log)')
    command=[EXE,'roms/mk3','factory-seed.bin','gfx.txt','--window','--audio','--edition','original|remastered',
             '--cmos-profile','profiles/player']
    return dict(dry_run=True,installed=False,label=LABEL,stage=STAGE.as_posix(),files=files,command=command,
        environment='MK1_* of the edition (launcher mk3Environment: Original without CRT and ScaleFX, Remastered from '
                    '[Video.Preview.Remastered]); window class Mk5TemporalScanout for the launcher window discovery',
        kept_unchanged={k:('present' if (ROOT/k).exists() else 'absent') for k in KEPT},
        not_done=['no file written','no launcher build or replacement','no hard link created'])


def ini(identity,exe_sha):
    return ['format=1','kind=mk3-native','readiness=product','label='+LABEL,'game=mk3','revision=2.1',
            'program_sha256='+identity['program_sha256'],'executable='+EXE,'executable_sha256='+exe_sha,
            'rom_directory=roms/mk3','rom_list=roms.txt','graphics_list=gfx.txt','factory_seed=factory-seed.bin',
            'profile_directory=profiles/player','editions=original,remastered','fidelity=compared routes only (docs/MK3_DEVELOPMENT.md)']


def package_identity(units=None):
    """Package identity (M5): SHA-256 of the build inputs (the executable's sources, the MK3 runtime and headers, the shared
    host headers it includes, the generator; with `units`, the generated TMS units as generate.py --check digests them), of
    the authenticated ROMs (manifest) and of the assets. The launcher does not read it; the engine contract checks it."""
    from tools.mk3 import generate
    files=sorted({*preview.SOURCES,*(f'native/mk3/{n}' for n in generate.RUNTIME),
                  *(p.relative_to(ROOT).as_posix() for d in ('native/mk3','native/include') for p in (ROOT/d).iterdir()
                    if p.suffix in ('.hpp','.h','.inc') and p.is_file()),'tools/mk3/generate.py','tools/mk3/preview.py'})
    manifest=json.loads(roms.MANIFEST.read_text('utf-8'))
    from tools.setup import mk3 as setup_mk3
    out=dict(schema='mk3-native-package-identity/1',sources={**{f:q.sha(ROOT/f) for f in files},**setup_mk3.identity_files()},
             roms={r['path']:dict(size=r['size'],sha256=r['sha256']) for r in manifest['roms']},
             assets={'factory-seed.bin':q.sha(reference.SEED)})
    if units:
        import hashlib
        text={Path(u).name:Path(u).read_text('utf-8') for u in units}
        out['units_sha256']=hashlib.sha256(''.join(f'{n}|{len(t)}|{t}' for n,t in sorted(text.items())).encode()).hexdigest()
    return out


def write_product(exe,root=ROOT,units=None):
    """The package in root/PRODUCT (absent before): exe, bezel, seed, hard-linked ROMs, roms.txt, gfx.txt, ini, identity, empty
    profile. A scratch root gives a staging package (tools/launcher_mk3_engine_contract.py); the ROMs are links, never copies."""
    import os,shutil
    product=root/PRODUCT
    if product.exists() or linked(product):raise RuntimeError('MK3 native product already present: '+str(product))
    manifest=json.loads(roms.MANIFEST.read_text('utf-8'));rom_identity=roms.verify(ROOT/'roms/mk3',manifest)
    (product/'roms/mk3').mkdir(parents=True);(product/'profiles/player').mkdir(parents=True)
    shutil.copy2(exe,product/EXE)
    shutil.copy2(reference.SEED,product/'factory-seed.bin')
    for rom in manifest['roms']:
        os.link(ROOT/'roms/mk3'/rom['path'],product/'roms/mk3'/rom['path'])
        if q.sha(product/'roms/mk3'/rom['path'])!=rom['sha256']:raise RuntimeError('ROM link differs: '+rom['path'])
    rom_list=''.join(f"{r['sha256']} {r['size']} {r['path']}\n" for r in manifest['roms'])
    (product/'roms.txt').write_bytes(rom_list.encode('ascii'))
    (product/'gfx.txt').write_bytes(''.join(f'{o} {s} roms/mk3/{Path(p).name}\n' for p,o,s in reference_dma.graphics_rows()).encode('ascii'))
    exe_sha=q.sha(product/EXE)
    (product/'package.ini').write_bytes(('\r\n'.join(ini(rom_identity,exe_sha))+'\r\n').encode('utf-8'))
    package=dict(package_identity(units),program_sha256=rom_identity['program_sha256'],executable_sha256=exe_sha,
                 rom_list_sha256=q.sha(product/'roms.txt'),graphics_list_sha256=q.sha(product/'gfx.txt'))
    (product/IDENTITY).write_text(json.dumps(package,indent=1)+'\n',encoding='utf-8')
    return dict(executable_sha256=exe_sha,program_sha256=rom_identity['program_sha256'],rom_list_sha256=package['rom_list_sha256'],
                roms=len(manifest['roms']),seed_sha256=q.sha(product/'factory-seed.bin'),identity_sha256=q.sha(product/IDENTITY),
                sources=len(package['sources']),units_sha256=package.get('units_sha256'),files=sum(1 for f in product.rglob('*') if f.is_file()))


def carry(previous_package):
    """Reinstall: the player's CMOS of the previous package into the new one (49152 bytes; the previous one is only read)."""
    import shutil
    if previous_package is None:return 'first install: the seed starts the player profile'
    src,dst=previous_package/PLAYER_CMOS,ROOT/PRODUCT/PLAYER_CMOS
    if linked(src) or linked(dst):raise RuntimeError('MK3 CMOS path is a link: '+str(src))
    if not src.is_file():return 'no CMOS in the previous package'
    if src.stat().st_size!=49152:raise RuntimeError('MK3 player CMOS is not 49152 bytes: '+str(src))
    shutil.copy2(src,dst)
    if q.sha(dst)!=q.sha(src):raise RuntimeError('MK3 CMOS copy differs: '+str(dst))
    return dict(source=src.relative_to(ROOT).as_posix(),sha256=q.sha(dst))


def swap_plan():
    """DRY-RUN ONLY: what --install changes on this root and the way back. Nothing is written, built or replaced; the
    install needs the user's OK."""
    sha=lambda p:q.sha(ROOT/p) if (ROOT/p).is_file() else None
    rollback=STAGE/'rollback/triunit.previous.exe'
    return dict(dry_run=True,executed=False,needs="the user's OK",
        now=dict(launcher_sha256=q.sha(LAUNCHER),package='present' if (ROOT/PRODUCT/'package.ini').is_file() else 'absent',
                 executable_sha256=sha(PRODUCT/EXE),player_cmos_sha256=sha(PRODUCT/PLAYER_CMOS),profile_sha256=sha(PROFILE),
                 rollback_copy_sha256=sha(rollback),kept_files=len(snapshot())),
        change=['triunit.exe from the current tree (MK3 card: 1 native Original, 2 native Remastered)',
                f'{PRODUCT.as_posix()} rebuilt (write_product); the installed one moves to {STAGE.as_posix()}/rollback/product-<time>',
                f'{(PRODUCT/PLAYER_CMOS).as_posix()} copied from the previous package (carry); {PROFILE.as_posix()} is not touched'],
        steps=['move the installed package to the rollback folder; build mk3.exe (tools/mk3/preview.py) and write the package',
               'build triunit.exe in scratch (LIBS, tools/launcher_backend_build.py arguments)',
               f'keep the current launcher as {rollback.as_posix()} (copy only if its SHA-256 differs)',
               'replace triunit.exe and compare its SHA-256 with the scratch build',
               'run native/tests/mk3_launcher_tests.cpp native on the real root (both editions) and the MK1 launcher smoke',
               'remove the CMOS the lifecycle check wrote in the new package, then carry the player CMOS',
               'hash PRESERVED before and after: equal; any failure restores the previous launcher and package'],
        rollback=[f'copy {rollback.as_posix()} over triunit.exe and move the rollback product back',
                  'automatic on any failure of --install'],
        not_done=['no file written','no launcher build or replacement','no package written','no profile copied'])


def install():
    import os,shutil,time
    stage=ROOT/STAGE;rollback=stage/'rollback/triunit.previous.exe'
    r={'passed':False,'label':LABEL};before=snapshot();r['preserved_files']=len(before)
    previous=q.sha(LAUNCHER);r['previous_launcher_sha256']=previous;installed=False
    # Reinstall: the installed package moves (one rename of its own directory entry, no link followed) to a new rollback
    # folder and comes back if anything fails; a failed new package is moved aside, never deleted.
    product=ROOT/PRODUCT;previous_package=None
    if product.exists() or product.is_symlink():
        if linked(product):raise RuntimeError('MK3 native product is a link: '+str(product))
        previous_package=stage/'rollback'/('product-'+time.strftime('%Y%m%d-%H%M%S'))
        if previous_package.exists() or linked(previous_package):raise RuntimeError('rollback folder exists: '+str(previous_package))
        previous_package.parent.mkdir(parents=True,exist_ok=True);os.rename(product,previous_package)
        r['previous_package']=previous_package.relative_to(ROOT).as_posix()
    try:
        with preview.Preview() as built:
            r['build']=q.compact(built.build);r['package']=write_product(built.exe,units=built.units)
        with q.scratch_tree() as (scratch,cleanup):
            r['cleanup']=cleanup;env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH'],'TEMP':str(scratch),'TMP':str(scratch)}
            exe=scratch/'triunit.exe'
            build=q.command([q.DEFAULT_CC,'-std=c++17','-O2','-s','-Wall','-Wextra','-Werror','-static','-municode','-mwindows',
                *[ROOT/'native/launcher'/n for n in ('launcher_main.cpp','launcher_renderer.cpp','launcher_backend.cpp')],
                *['-l'+n for n in LIBS],*arguments(ROOT),'-Wl,--no-insert-timestamp','-o',exe],scratch,cwd=ROOT,env=env,timeout=180)
            r['launcher_build']=q.compact(build);assert build['passed'],build.get('stdout','')[-3000:]
            test=scratch/'mk3-launcher-tests.exe'
            built=q.command([q.DEFAULT_CC,'-std=c++17','-Wall','-Wextra','-Werror','-static','-municode','-I'+str(ROOT/'native/launcher'),
                ROOT/'native/tests/mk3_launcher_tests.cpp',ROOT/'native/launcher/launcher_backend.cpp','-luser32','-o',test]+arguments(ROOT),scratch,cwd=ROOT,env=env,timeout=180)
            assert built['passed'],q.compact(built)
            unlinked(rollback);rollback.parent.mkdir(parents=True,exist_ok=True)
            if not rollback.exists() or q.sha(rollback)!=previous:shutil.copy2(LAUNCHER,rollback)
            unlinked(LAUNCHER);shutil.copy2(exe,LAUNCHER);installed=True
            r['launcher_sha256']=q.sha(LAUNCHER);assert r['launcher_sha256']==q.sha(exe)
            live=q.command([test,ROOT,'native'],scratch,cwd=ROOT,env=env,timeout=180);r['native_live']=q.compact(live)
            assert live['passed'],r['native_live']
            smoke,_=q.smoke(scratch);r['mk1_smoke']=smoke;assert smoke and all(row.get('passed') for row in smoke),smoke
        # The lifecycle check booted both editions; the player's session continues from the previous package's CMOS (else the seed).
        cmos=ROOT/PRODUCT/PLAYER_CMOS
        if cmos.is_file() and not linked(cmos):cmos.unlink()
        r['carried']=carry(previous_package)
        assert snapshot()==before,'MK1/MK2 profile or package changed'
        r['passed']=True
    except Exception as error:
        r['error']=repr(error)
        if installed:shutil.copy2(rollback,LAUNCHER);r['rolled_back']=q.sha(LAUNCHER)==previous
        if previous_package:
            if product.exists() and not linked(product):
                failed=stage/'rollback'/('product-failed-'+time.strftime('%Y%m%d-%H%M%S'));os.rename(product,failed)
                r['failed_package']=failed.relative_to(ROOT).as_posix()
            if not product.exists():os.rename(previous_package,product);r['previous_package_restored']=True
    r['rollback_copy']=rollback.relative_to(ROOT).as_posix()
    stage.mkdir(parents=True,exist_ok=True);(stage/'install.json').write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in r.items() if k!='mk1_smoke'},indent=1,ensure_ascii=False)[:5000]);return r['passed']


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    if sys.argv[1:]==['--install']:raise SystemExit(0 if install() else 1)
    print(json.dumps(swap_plan() if sys.argv[1:]==['--swap-plan'] else plan(),indent=1,ensure_ascii=False))
