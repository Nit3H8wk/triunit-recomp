"""MK3 card engine contract on a staged native package: one scratch root per run, ROMs hard-linked, nothing installed.

    python tools/launcher_mk3_engine_contract.py          # UI toggle (2 native states), saved/restored choice, Engine=0 and
                                                          # old-profile migration, refusal without fallback, per-edition
                                                          # [Video.Original]/[Video.Remastered] profiles and the
                                                          # [Video.Preview.Remastered] migration, every native MK1_* value
                                                          # (video, GameVolume, AudioLatency), MK3 Settings controls, the D7
                                                          # Settings text, package-identity.json against the staged files
    python tools/launcher_mk3_engine_contract.py --live   # also both native editions through the backend (native mk3, windows)
    python tools/launcher_mk3_engine_contract.py --live --exe build/native/mk3-native/product/mk3
                                                          # stages a copy of an existing mk3 instead of building

The UI run (native/tests/mk3_launcher_ui_tests.cpp) stages its own binary as mk3, so the launcher's real MK3 launch
path runs and the probe records the edition and every MK1_* value it received. --live stages the real mk3
(tools/mk3/preview.py) and runs native/tests/mk3_launcher_tests.cpp native against the staged root.
"""
from pathlib import Path
import argparse,json,os,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.quality import run as q
from tools.launcher_backend_build import arguments
from tools.mk3 import preview,preview_install

# D7 (14/11/2026): the MK3 Settings say that the Remastered edition keeps the arcade audio.
D7='L"AUDIO DO MK3",L"Remasterizada: video remasterizado, audio original do arcade."'
LIBS=('d3d12','dxgi','d3dcompiler','dxguid','windowscodecs','ole32','uuid','gdi32','user32','shell32','xinput9_1_0')


def build(source,exe,scratch,env,extra=()):
    return q.command([q.DEFAULT_CC,'-std=c++17','-O1','-static','-municode','-Wall','-Wextra','-Werror','-I'+str(q.ROOT/'native/launcher'),
                      q.ROOT/source,*extra,q.ROOT/'native/launcher/launcher_backend.cpp',*['-l'+x for x in LIBS],*arguments(q.ROOT),'-o',exe],
                     scratch,cwd=q.ROOT,env=env,timeout=180)


def identity_holds(root):
    """package-identity.json of a staged package against its files and the current tree (M5 package identity)."""
    product=root/preview_install.PRODUCT;ident=json.loads((product/preview_install.IDENTITY).read_text('utf-8'))
    files={preview_install.EXE:ident['executable_sha256'],'roms.txt':ident['rom_list_sha256'],'gfx.txt':ident['graphics_list_sha256'],
           **ident['assets'],**{'roms/mk3/'+p:v['sha256'] for p,v in ident['roms'].items()}}
    wrong=[f for f,h in files.items() if q.sha(product/f)!=h]+[f for f,h in ident['sources'].items() if q.sha(q.ROOT/f)!=h]
    return dict(passed=not wrong,files=len(files),sources=len(ident['sources']),units_sha256=ident.get('units_sha256'),differs=wrong[:10])


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--live',action='store_true');parser.add_argument('--exe',type=Path);a=parser.parse_args()
    out={'d7_text':D7 in (q.ROOT/'native/launcher/launcher_main.cpp').read_text('utf-8')}
    with q.scratch_tree() as (s,cleanup):
        env=dict(os.environ,PATH=str(q.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH'],TEMP=str(s),TMP=str(s))
        exe=s/'mk3-engine-ui.exe'
        r=build('native/tests/mk3_launcher_ui_tests.cpp',exe,s,env,[q.ROOT/'native/launcher/launcher_renderer.cpp']);out['ui_build']=q.compact(r)
        if r['passed']:
            out['ui_package']=preview_install.write_product(exe,s/'ui');out['ui_identity']=identity_holds(s/'ui')
            r=q.command([exe,s/'ui'],s,env=env,timeout=180);out['ui']=q.compact(r)
            if not out['ui_identity']['passed']:r=dict(r,passed=False)
        if r['passed'] and a.live:
            if a.exe:out['exe_sha256']=q.sha(a.exe);out['live_package']=preview_install.write_product(a.exe,s/'live')
            else:
                with preview.Preview() as built:
                    out['build']=q.compact(built.build);out['live_package']=preview_install.write_product(built.exe,s/'live',units=built.units)
            out['live_identity']=identity_holds(s/'live')
            test=s/'mk3-launcher.exe';r=build('native/tests/mk3_launcher_tests.cpp',test,s,env);out['live_build']=q.compact(r)
            if r['passed']:r=q.command([test,s/'live','native'],s,cwd=q.ROOT,env=env,timeout=180);out['live']=q.compact(r)
            if not out['live_identity']['passed']:r=dict(r,passed=False)
    out['cleanup']=cleanup;out['passed']=bool(r['passed']) and out['d7_text'] and not cleanup.get('exists_after')
    print(json.dumps(out,indent=1,default=str));return 0 if out['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
