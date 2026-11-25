"""Build the native launcher and package the separately built CRT engine."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,shutil,subprocess,uuid
ROOT=Path(__file__).resolve().parents[3];HERE=Path(__file__).resolve().parent
import runpy
backend_arguments=runpy.run_path(ROOT/'tools/launcher_backend_build.py')['arguments']
STAGE=ROOT/'build/native/manual-temporary-8-20261025';PRODUCT=STAGE/'product'
OLD=ROOT/'build/native/manual-temporary-7-20261025/product'
CC=Path('C:/msys64/mingw64/bin/g++.exe')
def SEED():
 import sys;sys.path.insert(0,str(ROOT))
 from tools.setup import mk1;return mk1.seed_path()

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def unlinked(p):
 for part in (p.absolute(),*p.absolute().parents):
  if part.is_symlink() or part.is_junction():raise RuntimeError('Linked build path: '+str(part))
def write(p,v):
 unlinked(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def guard():
 s=importlib.util.spec_from_file_location('guard',ROOT/'tools/quality/temporary_tree.py');g=importlib.util.module_from_spec(s);s.loader.exec_module(g);return g
def inventory():
 paths=[]
 for v in range(1,8):
  paths.append(ROOT/f'MK1-TEMPORARIA-{v}.exe')
  name=f'manual-temporary-{v}-'+('20261024' if v<3 else '20261025')
  for folder in ('product','profile'):
   base=ROOT/'build/native'/name/folder
   for directory,dirs,files in os.walk(base,followlinks=False):
    for name2 in dirs+files:unlinked(Path(directory)/name2)
    paths.extend(Path(directory)/n for n in files)
 return {p.relative_to(ROOT).as_posix():sha(p) for p in paths if p.is_file()}
def main(action,engine=None):
 """action 'package': the engine built by build_runtime.py (build.json); 'setup': `engine`, the executable the local setup
 built (tools/setup/install.py), copied into the product first."""
 unlinked(STAGE);STAGE.mkdir(parents=True,exist_ok=True);PRODUCT.mkdir(exist_ok=True)
 before=inventory();temp=STAGE/('temporary-package-'+uuid.uuid4().hex);temp.mkdir();rec={'passed':False}
 try:
  env=dict(os.environ,PATH=str(CC.parent)+os.pathsep+os.environ['PATH'],TEMP=str(temp),TMP=str(temp))
  if action=='launcher':
   sources=[ROOT/'native/launcher'/n for n in ('launcher_main.cpp','launcher_renderer.cpp','launcher_backend.cpp')]
   exe=temp/'launcher.exe'
   args=[str(CC),'-std=c++17','-O2','-s','-Wall','-Wextra','-Werror','-static','-municode','-mwindows',*[str(p) for p in sources],*[f'-l{x}' for x in ('d3d12','dxgi','d3dcompiler','dxguid','windowscodecs','ole32','uuid','gdi32','user32','shell32','xinput9_1_0')],'-Wl,--no-insert-timestamp','-o',str(exe)]+backend_arguments(ROOT)
   run=subprocess.run(args,capture_output=True,text=True,env=env,timeout=180)
   assert run.returncode==0,run.stderr[-6000:]
   destination=ROOT/'triunit.exe';unlinked(destination);shutil.copy2(exe,destination)
   rec.update(launcher=destination.name,launcher_sha256=sha(destination),launcher_bytes=destination.stat().st_size)
  else:
   if action=='setup':
    built=Path(engine);target=PRODUCT/'mk5-native-audio';unlinked(built);unlinked(target)
    shutil.copy2(built,temp/target.name);os.replace(temp/target.name,target);engine=target
    assert sha(engine)==sha(built),'engine copy differs'
   else:
    build=json.loads((STAGE/'build.json').read_text());assert build['passed']
    engine=PRODUCT/'mk5-native-audio';assert sha(engine)==build['sha256']
   old=json.loads((OLD/'manifest.json').read_text()) if (OLD/'manifest.json').is_file() else json.loads((ROOT/'tools/mk1/runtime-inputs.json').read_text())
   for name,want in old.get('files',{}).items():
    assert Path(name).name==name and sha(OLD/name)==want,'Predecessor integrity: '+name
   for name in ('LICENSE-audio.txt','LICENSE-ymfm.txt','LICENSE-video.txt'):shutil.copy2(ROOT/'native/runtime'/name,PRODUCT/name)
   seed=SEED();shutil.copy2(seed,PRODUCT/'factory-default-control-input.bin')   # CMOS seed written by the setup
   template=(HERE/'session.ps1').read_text(encoding='utf-8-sig');assert template.count('@@ENGINE_SHA256@@')==1
   (PRODUCT/'session.ps1').write_text(template.replace('@@ENGINE_SHA256@@',sha(engine)),encoding='utf-8-sig')
   shutil.copy2(HERE/'LogStore.cs',PRODUCT/'LogStore.cs')
   ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
   # Precompile the bounded logger once, avoiding C# compilation on each game start.
   compile_script=temp/'compile.ps1'
   compile_script.write_text("$ErrorActionPreference='Stop'\nAdd-Type -Path '"+str(HERE/'LogStore.cs').replace("'","''")+"' -OutputAssembly '"+str(temp/'LogStore.dll').replace("'","''")+"' -OutputType Library\n",encoding='utf-8-sig')
   run=subprocess.run([str(ps),'-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(compile_script)],capture_output=True,text=True,env=env,timeout=60)
   assert run.returncode==0,run.stderr[-3000:]
   shutil.copy2(temp/'LogStore.dll',PRODUCT/'LogStore.dll')
   profile=STAGE/'profile';unlinked(profile);profile.mkdir(exist_ok=True)
   if not(profile/'cmos.bin').exists():
    source=OLD.parent/'profile/cmos.bin'
    if not source.is_file():source=seed
    assert source.stat().st_size==16384;shutil.copy2(source,profile/'cmos.bin')
   manifest={'version':'temporaria-8','renderer':'D3D12-DXGI-flip','video_profiles':1,'engine_sha256':sha(engine),'engine_rebuilt':True,'roms_included':False,'roms_required':old['roms_required'],'game_rules_changed':False,'full_fidelity_certified':False,'crt_presets':['off','bvm-1080','bvm-4k','bvm-soft','energy','pvm','phosphor'],'files':{p.name:sha(p) for p in sorted(PRODUCT.iterdir()) if p.is_file() and p.name!='manifest.json'}}
   write(PRODUCT/'manifest.json',manifest)
   source_paths=[p for directory in (ROOT/'native',HERE) for p in directory.rglob('*') if p.is_file() and '__pycache__' not in str(p)]
   write(STAGE/'source-manifest.json',{'files':{p.relative_to(ROOT).as_posix():sha(p) for p in sorted(source_paths)},'engine_source_changed':True,'game_rules_changed':False})
   rec.update(engine_sha256=sha(engine),engine_bytes=engine.stat().st_size,manifest_sha256=sha(PRODUCT/'manifest.json'))
  assert before==inventory(),'Previous products/profiles modified'
  rec.update(passed=True,predecessors_preserved=before)
 except BaseException as exc:rec['error']=str(exc)
 finally:
  rec['cleanup']=guard().remove_tree(temp,STAGE);write(STAGE/('build-launcher.json' if action=='launcher' else 'package.json'),rec)
 print(json.dumps({k:v for k,v in rec.items() if k!='predecessors_preserved'},indent=2));return rec['passed']
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['launcher','package']);a=p.parse_args();raise SystemExit(0 if main(a.action) else 1)
