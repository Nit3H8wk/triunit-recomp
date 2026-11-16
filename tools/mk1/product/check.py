"""Small native contracts, isolated scratch and verified cleanup on all exits."""
from pathlib import Path
import os,sys,json,subprocess,importlib.util,uuid
ROOT=Path(__file__).resolve().parents[3]; HERE=Path(__file__).parent
STAGE=ROOT/'build/native/manual-temporary-8-20261025'
def main():
 STAGE.mkdir(parents=True,exist_ok=True);scratch=STAGE/('temporary-contract-'+uuid.uuid4().hex);scratch.mkdir()
 spec=importlib.util.spec_from_file_location('guard',ROOT/'tools/quality/temporary_tree.py');guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
 rec={'passed':False,'cases':[]}
 try:
  cc=Path('C:/msys64/mingw64/bin/g++.exe');env=dict(os.environ,PATH=str(cc.parent)+os.pathsep+os.environ['PATH'],TEMP=str(scratch),TMP=str(scratch))
  for source in ['presentation_contract.cpp','controls_contract.cpp','audio_contract.cpp']:
   if '--controls-only' in sys.argv and source!='controls_contract.cpp':continue
   if not (HERE/source).exists():continue
   exe=scratch/(Path(source).stem+'.exe')
   command=[str(cc),'-std=c++17','-O2','-Wall','-Wextra','-Werror','-DUNICODE','-D_UNICODE','-I'+str(ROOT/'native/include'),str(HERE/source)]
   if source=='presentation_contract.cpp':command += [str(ROOT/'native/src/mk5_window.cpp'),'-ld3d12','-ldxgi','-ld3dcompiler','-ldxguid','-lgdi32','-lwindowscodecs','-lole32','-luuid']
   build=subprocess.run(command+['-o',str(exe)],env=env,capture_output=True,text=True,timeout=90)
   case={'name':source,'compile':build.returncode}
   if build.returncode:case['output']=build.stderr[-5000:]
   else:
    run=subprocess.run([str(exe)],env=env,capture_output=True,text=True,timeout=35);case.update(exit=run.returncode,output=run.stdout+run.stderr)
   rec['cases'].append(case)
  rec['passed']=all(x.get('exit')==0 for x in rec['cases'])
 finally:
  rec['cleanup']=guard.remove_tree(scratch,STAGE);(STAGE/('baseline-red.json' if '--baseline' in sys.argv else 'contracts.json')).write_text(json.dumps(rec,indent=2)+'\n')
 print(json.dumps(rec,indent=2));return rec['passed']
if __name__=='__main__':raise SystemExit(0 if main() else 1)
