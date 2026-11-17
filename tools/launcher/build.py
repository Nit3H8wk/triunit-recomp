"""Build the TriUnit Recomp launcher (triunit.exe) at the project root from the current sources.

    python tools/launcher/build.py            # writes triunit.exe (ignored by Git) and prints its SHA-256

The launcher holds no game code: it reads the setup records in generated/<game>/<sha>/ and starts the games built there.
"""
from pathlib import Path
import os,shutil,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import runpy
from tools.quality import run as q

ROOT=q.ROOT
arguments=runpy.run_path(str(ROOT/'tools/launcher_backend_build.py'))['arguments']
NAME='triunit.exe'
SOURCES=('launcher_main.cpp','launcher_renderer.cpp','launcher_backend.cpp')
LIBRARIES=('d3d12','dxgi','d3dcompiler','dxguid','windowscodecs','ole32','uuid','gdi32','user32','shell32','xinput9_1_0')


def command(cc,output):
    return [cc,'-std=c++17','-O2','-s','-Wall','-Wextra','-Werror','-static','-municode','-mwindows',
            *[ROOT/'native/launcher'/p for p in SOURCES],*['-l'+n for n in LIBRARIES],*arguments(ROOT),
            '-Wl,--no-insert-timestamp','-o',output]


def build(destination=ROOT/NAME,cc=q.DEFAULT_CC):
    env={'PATH':str(Path(cc).parent)+os.pathsep+os.environ.get('PATH','')}
    with q.scratch_tree() as (scratch,cleanup):
        exe=scratch/NAME
        result=q.command(command(cc,exe),scratch,cwd=ROOT,env=env,timeout=240)
        if not result['passed']:raise RuntimeError(result['stdout'][-4000:])
        if destination.is_symlink():raise RuntimeError('linked launcher destination')
        shutil.copy2(exe,destination)
    return q.sha(destination)


def stale(destination=ROOT/NAME):
    """True when the launcher is missing or older than a source it is built from (the native tree or these scripts)."""
    if not destination.is_file():return True
    built=destination.stat().st_mtime
    sources=[p for p in (ROOT/'native').rglob('*') if p.suffix in ('.cpp','.hpp','.h','.inc')]
    return any(p.stat().st_mtime>built for p in [*sources,Path(__file__),ROOT/'tools/launcher_backend_build.py'])


if __name__=='__main__':
    if '--if-stale' in sys.argv[1:] and not stale():print(NAME,'up to date')
    else:print(NAME,build())
