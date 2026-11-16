"""Build only the offline decoder probe using an existing local compiler."""
from pathlib import Path
import hashlib,json,os,subprocess
root=Path(__file__).resolve().parent
compiler=Path(r'C:\msys64\mingw64\bin\g++.exe')
env=os.environ.copy()
env['PATH']=str(compiler.parent)+os.pathsep+env['PATH']
cmd=[str(compiler),'-std=c++17','-O2','-static','-I'+str(root/'shim'),'-I'+str(root/'upstream'),str(root/'disassemble.cpp'),str(root/'upstream/34010dsm.cpp'),'-o',str(root/'tms34010-decoder.exe')]
subprocess.run(cmd,check=True,env=env,cwd=root)
exe=root/'tms34010-decoder.exe'
info={'compiler':str(compiler),'compiler_version':subprocess.check_output([str(compiler),'--version'],env=env,text=True).splitlines()[0],'command':cmd,'executable_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'purpose':'Offline disassembly research only; no emulated CPU or game runtime.'}
repo=root.parents[2]
rel=lambda s:s.replace(str(repo)+chr(92),'').replace(chr(92),'/') if str(repo) in s else s
info['command']=[rel(c) for c in cmd]
info['note']='Paths are relative to the repository root. The setup builds its own decoder with tools/setup/decoder.py.'
(root/'build.json').write_text(json.dumps(info,indent=2)+'\n')
print(json.dumps(info,indent=2))
