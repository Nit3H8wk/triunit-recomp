"""Real C++ backend and core lifecycle in an owned disposable profile; compact receipt only."""
import json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2_arcade.build import prepare,ROOT,STAGE
import runpy
backend_arguments=runpy.run_path(ROOT/'tools/launcher_backend_build.py')['arguments']
from tools.quality import run as q

def main():
    result={'passed':False,'cases':[]}
    try:
        with q.scratch_tree() as (temp,cleanup):
            result['cleanup']=cleanup;cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH'],'TEMP':str(temp),'TMP':str(temp)}
            exe=temp/'test.exe';build=q.command([cc,'-std=c++17','-Wall','-Wextra','-Werror','-static','-municode','-I'+str(ROOT/'native/launcher'),ROOT/'native/tests/mk2_launcher_tests.cpp',ROOT/'native/launcher/launcher_backend.cpp','-luser32','-o',exe]+backend_arguments(ROOT),temp,cwd=ROOT,env=env,timeout=120)
            result['build']=q.compact(build);assert build['passed'],result['build']
            for mode in ('isolated','short','close'):
                root=temp/('root with spaces '+mode)
                if mode!='isolated':prepare(root)
                run=q.command([exe,root,*([mode] if mode!='isolated' else [])],temp,cwd=ROOT,env=env,timeout=35)
                result['cases'].append({'mode':mode,**q.compact(run)})
                assert run['passed'],result['cases'][-1]
            result['passed']=True
    except Exception as error:result['error']=repr(error)
    target=ROOT/STAGE/'check.json';target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2));return result['passed']

if __name__=='__main__':raise SystemExit(0 if main() else 1)
