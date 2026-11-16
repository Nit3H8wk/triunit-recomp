"""Compile/run the real backend in a disposable tree; retain only a receipt."""
from pathlib import Path
import importlib.util,json,os,subprocess,uuid
ROOT=Path(__file__).resolve().parents[3]
import runpy
backend_arguments=runpy.run_path(ROOT/'tools/launcher_backend_build.py')['arguments']
HERE=Path(__file__).resolve().parent
STAGE=ROOT/'build/native/manual-temporary-8-20261025'
def main():
 STAGE.mkdir(parents=True,exist_ok=True)
 temp=STAGE/('temporary-backend-'+uuid.uuid4().hex);temp.mkdir()
 spec=importlib.util.spec_from_file_location('guard',ROOT/'tools/quality/temporary_tree.py');guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
 result={'passed':False,'test':'backend public contract'};junction=None
 try:
  cc=Path('C:/msys64/mingw64/bin/g++.exe');env=dict(os.environ,PATH=str(cc.parent)+os.pathsep+os.environ['PATH'],TEMP=str(temp),TMP=str(temp))
  command=[str(cc),'-std=c++17','-Wall','-Wextra','-Werror','-static','-municode','-I',str(ROOT/'native/launcher'),str(HERE/'backend_tests.cpp'),str(ROOT/'native/launcher/launcher_backend.cpp'),'-luser32','-o',str(temp/'backend-tests.exe')]+backend_arguments(ROOT)
  build=subprocess.run(command,capture_output=True,text=True,env=env,timeout=120)
  result['compile_exit']=build.returncode
  if build.returncode:result['compile_error']=build.stderr[-4000:];return result
  run=subprocess.run([str(temp/'backend-tests.exe'),str(temp/'root')],capture_output=True,text=True,env=env,timeout=30)
  result.update(passed=run.returncode==0,exit_code=run.returncode,output=(run.stdout+run.stderr).strip())
  if run.returncode==0:
   outside=temp/'outside';outside.mkdir();sentinel=b'[Launcher]\nFPS=30\n';(outside/'launcher.ini').write_bytes(sentinel)
   linkedroot=temp/'linkedroot';junction=linkedroot/'build/native/manual-temporary-8-20261025/profile';junction.parent.mkdir(parents=True)
   link=subprocess.run(['cmd','/c','mklink','/J',str(junction),str(outside)],capture_output=True,text=True,timeout=10)
   assert link.returncode==0,link.stderr
   linked=subprocess.run([str(temp/'backend-tests.exe'),str(linkedroot),'linked'],capture_output=True,text=True,env=env,timeout=30)
   result['junction_test']={'passed':linked.returncode==0,'output':(linked.stdout+linked.stderr).strip(),'external_config_unchanged':(outside/'launcher.ini').read_bytes()==sentinel}
   result['passed']=linked.returncode==0 and result['junction_test']['external_config_unchanged']
  return result
 finally:
  if junction and junction.is_junction():
   assert junction.absolute().is_relative_to(temp.absolute()) and junction.name=='profile'
   junction.rmdir();result['junction_removed_without_traversal']=not junction.exists()
  result['cleanup']=guard.remove_tree(temp,STAGE)
  (STAGE/'check-backend.json').write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':
 result=main();print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)
