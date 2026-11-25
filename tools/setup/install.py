"""Setup step 8 (install): the launcher package of each game, from the executable the setup has just built.

The launcher plays a game only from its package (MK1 build/native/manual-temporary-8-20261025/product, MK2
build/native/mk2-native-v1/product, MK3 build/native/mk3-native/product) and, for MK2 and MK3, only when the package
executable has the SHA-256 of generated/<game>/<sha>/setup.json. This step reuses the package writers of the project
(tools/mk1/product/build.py, the MK2 package fields of tools/mk2/package_native.py, tools/mk3/preview_install.py) and
keeps the player's profile (profiles/, profile/) untouched. Everything stays on this machine and is ignored by Git.
"""
from pathlib import Path
import os,shutil,uuid
from tools.setup import paths
from tools.quality import run as q

ROOT=paths.ROOT


def _unlinked(path):
    for p in (Path(path).absolute(),*Path(path).absolute().parents):
        if p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()):raise RuntimeError('Linked package path: '+str(p))


def _replace(source,target):
    """Copy `source` next to `target` and swap it in (no partially written executable is ever visible)."""
    _unlinked(target);partial=target.with_name(target.name+'.partial');shutil.copy2(source,partial);os.replace(partial,target)


def _retire(product):
    """Remove the red neon frame image of packages built by older releases; the games draw the TV frame in code."""
    old=Path(product)/'arcade-bezel.png';_unlinked(old)
    if old.is_file():old.unlink()


def mk1(out):
    from tools.mk1.product import build
    _retire(build.PRODUCT) # before the package manifest lists the product files
    if not build.main('setup',out/'mk5-native-audio'):raise RuntimeError('MK1 package failed (build/native/manual-temporary-8-20261025/package.json)')
    engine=build.PRODUCT/'mk5-native-audio'
    return dict(product=build.PRODUCT.relative_to(ROOT).as_posix(),executable_sha256=q.sha(engine))


def mk2(out):
    from tools.mk2 import run,profile,package_native
    product=ROOT/'build/native/mk2-native-v1/product';_unlinked(product);product.mkdir(parents=True,exist_ok=True)
    with q.scratch_tree() as (scratch,cleanup):
        env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH'],'TEMP':str(scratch),'TMP':str(scratch)}
        sources=package_native.identities(scratch,env)
    for rom in run.read_manifest()['roms']:
        target=product/'roms'/rom['path'];_unlinked(target);target.parent.mkdir(exist_ok=True)
        if not target.exists():os.link(ROOT/'roms/mk2'/rom['path'],target)
        if q.sha(target)!=rom['sha256']:raise RuntimeError('MK2 package ROM differs: '+rom['path'])
    _replace(ROOT/'native/runtime/LICENSE-video.txt',product/'LICENSE-video.txt')
    _replace(out/'mk2-native',product/'mk2-native');_retire(product)
    seed=product/'factory-seed.bin';_unlinked(seed)
    seed.with_name('factory-seed.partial').write_bytes(profile._read(profile.FACTORY_SEED,factory=True));os.replace(seed.with_name('factory-seed.partial'),seed)
    executable=q.sha(product/'mk2-native')
    if executable!=q.sha(out/'mk2-native'):raise RuntimeError('MK2 package executable differs from the setup build')
    # The fields of tools/mk2/package_native.py (native-playable package read by the launcher's nativeSpec).
    fields=dict(format='1',kind='mk2-native-static-cpp17',readiness='native-playable',source='native/mk2/mk2_native_check.cpp',
        **{k:sources[k] for k in ('source_sha256','runtime_sources_sha256','core_overlays_sha256')},
        rom_profile_sha256=q.sha(run.MANIFEST),first_fight_pcs='63906',chunk_request_cycles='2000000',cooperative_slack_cycles='2000000',
        chunk_wall_timeout_ms='10000',bounded_observations='true',executable='mk2-native',executable_sha256=executable,
        rom_directory='roms',profile_directory='profiles/player',factory_seed='factory-seed.bin')
    manifest=product/'native-package.ini';pending=product/'native-package.pending';_unlinked(manifest);_unlinked(pending)
    pending.write_text(''.join(f'{k}={v}\n' for k,v in fields.items()),encoding='utf8');os.replace(pending,manifest)
    return dict(product=product.relative_to(ROOT).as_posix(),executable_sha256=executable,manifest_sha256=q.sha(manifest))


def mk3(out):
    from tools.mk3 import preview_install as package
    from tools.quality import temporary_tree
    stage=ROOT/package.STAGE;product=ROOT/package.PRODUCT;exe=out/'mk3';units=sorted((out/'tms').glob('*.cpp'))
    _unlinked(stage);stage.mkdir(parents=True,exist_ok=True)
    if not product.exists():info=package.write_product(exe,ROOT,units)
    else:
        # Reinstall: write the whole package in a temporary root on the same volume (the ROMs are hard links), then swap
        # every file except the player's profiles/ into the installed product.
        temporary=stage/('temporary-install-'+uuid.uuid4().hex)
        try:
            info=package.write_product(exe,temporary,units)
            fresh=temporary/package.PRODUCT
            for file in sorted(p for p in fresh.rglob('*') if p.is_file()):
                relative=file.relative_to(fresh)
                if relative.parts[0]=='profiles':continue
                target=product/relative;_unlinked(target);target.parent.mkdir(parents=True,exist_ok=True);os.replace(file,target)
        finally:
            if temporary.exists():temporary_tree.remove_tree(temporary,stage)
    _retire(product)
    if q.sha(product/package.EXE)!=q.sha(exe):raise RuntimeError('MK3 package executable differs from the setup build')
    return dict(product=product.relative_to(ROOT).as_posix(),executable_sha256=info['executable_sha256'],files=info['files'])


INSTALL={'mk1':mk1,'mk2':mk2,'mk3':mk3}
