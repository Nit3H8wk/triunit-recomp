"""Offline TMS34010 decoder compiled from the pinned MAME sources (BSD-3-Clause) on this machine.

Replaces the prebuilt executables that used to sit in docs/: the identity of the decoder is the SHA-256 of its inputs
(sources.json pins the upstream files) and of the compiler; the executable lives in generated/tools/ and is rebuilt
when either changes. Linking without a timestamp makes the build reproducible for one compiler.
"""
from pathlib import Path
import hashlib,json,os,subprocess

from tools.setup import paths
from tools.quality import run as quality

SOURCE=paths.ROOT/'docs/investigation/decoder-research'
INPUTS=('disassemble.cpp','shim/emu.h','upstream/34010dsm.cpp','upstream/34010dsm.h')


def inputs():
    """{relative name: sha256} of the decoder inputs, refused when an upstream file differs from sources.json."""
    pinned={'upstream/'+s['file']:s['sha256'] for s in json.loads((SOURCE/'sources.json').read_text('utf8'))['sources']}
    out={name:quality.sha(SOURCE/name) for name in INPUTS}
    for name,digest in out.items():
        if name in pinned and pinned[name]!=digest:raise ValueError('Pinned decoder source changed: '+name)
    return out


def identity(cc=None):
    cc=Path(cc or quality.DEFAULT_CC)
    text=json.dumps(dict(inputs=inputs(),compiler=quality.sha(cc)),sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def command(cc,exe):
    return [str(cc),'-std=c++17','-O2','-static','-I'+str(SOURCE/'shim'),'-I'+str(SOURCE/'upstream'),str(SOURCE/'disassemble.cpp'),
            str(SOURCE/'upstream/34010dsm.cpp'),'-Wl,--no-insert-timestamp','-o',str(exe)]


def tms34010(cc=None):
    """Path of the decoder for the current inputs and compiler, built once into generated/tools/."""
    cc=Path(cc or quality.DEFAULT_CC);key=identity(cc)
    exe=paths.TOOLS/f'tms34010-decoder-{key[:16]}.exe'
    if exe.is_file():return exe
    paths.TOOLS.mkdir(parents=True,exist_ok=True)
    if not paths.owned(paths.TOOLS):raise RuntimeError('generated/tools is linked outside the project')
    partial=exe.with_suffix('.partial.exe')
    env=dict(os.environ,PATH=str(cc.parent)+os.pathsep+os.environ['PATH'])
    built=subprocess.run(command(cc,partial),capture_output=True,text=True,env=env,timeout=180)
    if built.returncode:
        partial.unlink(missing_ok=True);raise RuntimeError('Decoder build failed: '+built.stderr[-2000:])
    os.replace(partial,exe)
    for old in paths.TOOLS.glob('tms34010-decoder-*.exe'):
        if old!=exe:old.unlink()
    return exe
