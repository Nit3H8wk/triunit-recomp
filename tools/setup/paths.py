"""Locations of the local, regenerable setup output.

generated/<game>/<program_sha256>/   translation units and .inc of one authenticated program image
generated/tools/                     decoders compiled from the pinned sources
Everything below generated/ is ignored by Git and rebuilt by `python tools/setup/setup.py`.
"""
from pathlib import Path
import importlib,json,re

ROOT=Path(__file__).resolve().parents[2]
GENERATED=ROOT/'generated'
TOOLS=GENERATED/'tools'


MANIFESTS={'mk1':'tools/mk1/roms-l1.json','mk2':'tools/mk2/roms-l31.json','mk3':'tools/mk3/roms-21.json'}


def manifest(game):
    """Versioned ROM manifest of the revision the project supports."""
    if game not in MANIFESTS:raise ValueError('Unknown game: '+game)
    return ROOT/MANIFESTS[game]


def program_sha256(game):
    """Program identity of the revision the project supports (from the versioned ROM manifest; no ROM read)."""
    return json.loads(manifest(game).read_text('utf-8'))['program_sha256']


def output(game):
    """generated/<game>/<program_sha256>/ (not created here)."""
    return GENERATED/game/program_sha256(game)


def owned(path):
    """True when `path` lies under generated/ without links on the way (cleanup guard)."""
    path=Path(path).absolute()
    for p in (path,*path.parents):
        if p==ROOT:break
        if p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()):return False
    return path.resolve().is_relative_to(GENERATED.resolve())


INCLUDE=re.compile(rb'^[ \t]*#[ \t]*include[ \t]+"(?:[./]*(?:mk2|mk3|src)/)?((?:mk2|mk3|mk5)_[A-Za-z0-9_]+\.inc)"',re.M)


def generated_names(game):
    if game=='mk1':
        from tools.setup import mk1
        return set(mk1.NAMES)
    if game=='mk3':return {'mk3_adsp_boot.inc','mk3_adsp_bank1.inc'}
    names=set(json.loads((ROOT/'tools/mk2/partitions.json').read_text('utf-8'))['units'])
    return names|{'mk2_first_fight.inc','mk2_first_fight_main.inc','mk2_adsp_boot.inc','mk2_first_fight_bounds.inc','mk2_first_fight_high_punch_bounds.inc',
                  'mk2_selection_bounds.inc','mk2_prestart_wait_bounds.inc'}


def generated_flags(args):
    """-I generated/<game>/<sha> for every game whose generated include one of the C++ sources in `args` names
    (`#include "mk2_first_fight.inc"`), minus the flags already in `args`. Empty when nothing generated is included.
    A source that includes a generated driver also gives -I of its own folder: the driver's units are compiled as if
    they sat next to it (DRIVERS, generated_sources)."""
    wanted=set();beside=[]
    for a in args:
        s=str(a)
        if not s.endswith(('.cpp','.cc','.cxx')):continue
        try:found=INCLUDE.findall(Path(s).read_bytes())
        except OSError:continue
        for name in found:
            wanted|={game for game in ('mk1','mk2','mk3') if name.decode() in generated_names(game)}
            here='-I'+Path(s).absolute().parent.as_posix()
            if name.decode() in DRIVERS and here not in beside:beside.append(here)
    present={str(a) for a in args}
    flags=[importlib.import_module('tools.setup.'+game).include() for game in sorted(wanted)]+beside
    return [f for f in flags if f not in present]


# Generated drivers whose graph is compiled as separate generated units (the shards of a large graph, so they compile in
# parallel): a source that includes the driver needs every .cpp of that game's generated folder.
DRIVERS={'mk5_main_loop_driver.inc':'mk1','mk2_first_fight_main.inc':'mk2'}


def generated_sources(args):
    """The generated units the C++ sources in `args` need besides themselves: the shards of the drivers they include.
    A unit whose file name is already in `args` is skipped (a scratch copy stands for the generated one)."""
    present={Path(str(a)).name for a in args};out=[]
    for a in args:
        s=str(a)
        if not s.endswith(('.cpp','.cc','.cxx')):continue
        try:found=INCLUDE.findall(Path(s).read_bytes())
        except OSError:continue
        for name in found:
            game=DRIVERS.get(name.decode())
            if not game:continue
            folder=importlib.import_module('tools.setup.'+game).inc_dir()
            units=[folder/n for n in sorted(json.loads((folder/'includes.json').read_text('utf8'))['files']) if n.endswith('.cpp')]
            out+=[u for u in units if u.name not in present and u not in out]
    return out


def with_generated(args):
    """`args` with generated_flags() inserted after the last -I flag (the include order of the source tree is kept) and
    generated_sources() after the last C++ source (before the libraries, so the link order is kept)."""
    out=list(args);extra=generated_flags(out)
    if extra:
        last=max((n for n,a in enumerate(out) if str(a).startswith('-I')),default=0)
        out[last+1:last+1]=extra
    # Only a command over the whole program (link, -MM) gets the units; a -c/-S/-E unit compile names its one source.
    units=[] if any(str(a) in ('-c','-S','-E') for a in out) else generated_sources(out)
    if units:
        last=max(n for n,a in enumerate(out) if str(a).endswith(('.cpp','.cc','.cxx')))
        out[last+1:last+1]=[u.as_posix() for u in units]   # forward slashes: dependency output stays parseable
    return out
