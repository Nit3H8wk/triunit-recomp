"""Exercise the actual App selection handlers with an owned real MK2 child."""
import json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2_arcade.build import prepare,ROOT,STAGE
import runpy
backend_arguments=runpy.run_path(ROOT/'tools/launcher_backend_build.py')['arguments']
from tools.quality import run as q

def main():
    result={'passed':False}
    try:
        with q.scratch_tree() as (temp,cleanup):
            result['cleanup']=cleanup;cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH'],'TEMP':str(temp),'TMP':str(temp)}
            exe=temp/'ui-test.exe';libs=['d3d12','dxgi','d3dcompiler','dxguid','windowscodecs','ole32','uuid','gdi32','user32','shell32','xinput9_1_0']
            build=q.command([cc,'-std=c++17','-O1','-Wall','-Wextra','-Werror','-static','-municode',ROOT/'native/tests/mk2_launcher_ui_tests.cpp',ROOT/'native/launcher/launcher_renderer.cpp',ROOT/'native/launcher/launcher_backend.cpp',*['-l'+v for v in libs],'-o',exe]+backend_arguments(ROOT),temp,cwd=ROOT,env=env,timeout=120)
            result['build']=q.compact(build);assert build['passed'],result['build'];root=temp/'profile root';prepare(root)
            execution=q.command([exe,root],temp,cwd=ROOT,env=env,timeout=35);result['execution']=q.compact(execution);assert execution['passed'],result['execution'];result['passed']=True
    except Exception as error:result['error']=repr(error)
    p=ROOT/STAGE/'check-ui.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2));return result['passed']

if __name__=='__main__':raise SystemExit(0 if main() else 1)
