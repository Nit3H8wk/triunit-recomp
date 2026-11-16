"""Real backend lifecycle tests; hardlinks avoid copying immutable game/ROM binaries."""
from pathlib import Path
import importlib.util,json,os,subprocess,uuid,sys,time,ctypes as C
from ctypes import wintypes as W
import psutil
ROOT=Path(__file__).resolve().parents[3];HERE=Path(__file__).resolve().parent
import runpy
backend_arguments=runpy.run_path(ROOT/'tools/launcher_backend_build.py')['arguments']
STAGE=ROOT/'build/native/manual-temporary-8-20261025';PRODUCT=STAGE/'product'
def main():
 temp=STAGE/('temporary-process-'+uuid.uuid4().hex);temp.mkdir();result={'passed':False,'cases':[],'binary_storage':'temporary immutable hardlinks; no binary copies or dumps'}
 spec=importlib.util.spec_from_file_location('guard',ROOT/'tools/quality/temporary_tree.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
 try:
  cc=Path('C:/msys64/mingw64/bin/g++.exe');env=dict(os.environ,PATH=str(cc.parent)+os.pathsep+os.environ['PATH'],TEMP=str(temp),TMP=str(temp))
  build=subprocess.run([str(cc),'-std=c++17','-Wall','-Wextra','-Werror','-static','-municode','-I',str(ROOT/'native/launcher'),str(HERE/'backend_process_tests.cpp'),str(ROOT/'native/launcher/launcher_backend.cpp'),'-luser32','-o',str(temp/'process-tests.exe')]+backend_arguments(ROOT),capture_output=True,text=True,env=env,timeout=120)
  assert build.returncode==0,build.stderr[-4000:]
  root=temp/'root';product=root/'build/native/manual-temporary-8-20261025/product';product.mkdir(parents=True)
  for file in PRODUCT.iterdir():
   if file.is_file():os.link(file,product/file.name)
  manifest=json.loads((PRODUCT/'manifest.json').read_text())
  for rom in manifest['roms_required']:
   dest=root/'roms'/rom['path'];dest.parent.mkdir(parents=True,exist_ok=True);os.link(ROOT/'roms'/rom['path'],dest)
  profile=product.parent/'profile';profile.mkdir();(profile/'cmos.bin').write_bytes((STAGE/'profile/cmos.bin').read_bytes())
  for mode in (('timeout',) if '--timeout-probe' in sys.argv else ('short','close','race','video-original','video-remastered','failure')):
   video=mode.startswith('video-');remastered=mode=='video-remastered'
   if video:
    (profile/'launcher.ini').write_text(f'[MK1]\nRemastered={int(remastered)}\n'
        '[Video.Original]\nScanlines=9\nFilter=0\nScaleMode=2\nCAS=50\nBilateral=50\nSMAA=1\n'
        'ScaleFX=1\nScaleFXAmount=100\nFullscreen=0\nBezel=0\n'
        '[Video.Remastered]\nScanlines=9\nFilter=3\nScaleMode=5\nCAS=25\nBilateral=25\nSMAA=1\n'
        'ScaleFX=1\nScaleFXAmount=37\nFullscreen=0\nBezel=0\n')
   if remastered:
    (product/'music').mkdir()
    for file in (PRODUCT/'music').iterdir():
     if file.is_file():os.link(file,product/'music'/file.name)
   if mode=='failure':
    (product/'manifest.json').unlink()
    (product/'manifest.json').write_text(json.dumps({key:value for key,value in manifest.items() if key!='video_profiles'}))
    (product/'session.ps1').unlink()
    legacy=('ProjectRoot','WindowFrames','GameMode','VisualMode','Scanlines','Filter','CrtPreset','SyncMode',
            'ColorMode','Brightness','Bezel','HighRefresh','AudioLatency','ScaleFX','GameVolume','DswWord','CmosCoinage')
    (product/'session.ps1').write_text('[CmdletBinding()]\nparam('+','.join('[string]$'+name for name in legacy)+')\nexit 19\n')
   if mode=='timeout':
    harness=subprocess.Popen([str(temp/'process-tests.exe'),str(root),mode],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env)
    end=time.monotonic()+25
    while not(root/'timeout-ready.txt').is_file() and time.monotonic()<end and harness.poll() is None:time.sleep(.05)
    ready=(root/'timeout-ready.txt').is_file()
    # Killing this harness models subprocess.run's TimeoutExpired behavior;
    # the owned game/logger deliberately survive until the outer finally.
    if harness.poll() is None:harness.kill()
    harness.wait(timeout=10)
    assert ready,'owned game fixture did not become ready before bounded wait'
    result['cases'].append({'mode':'timeout','passed':True,'harness_was_killed':True,'owned_game_window_confirmed_before_timeout':True})
    result['passed']=True;break
   test_env=dict(env,MK1_GRAPHICS_VALIDATE='1') if video else env
   run=subprocess.run([str(temp/'process-tests.exe'),str(root),mode],capture_output=True,text=True,env=test_env,timeout=65)
   case={'mode':mode,'passed':run.returncode==0,'output':(run.stdout+run.stderr).strip()};result['cases'].append(case)
   if run.returncode:
    boot=root/'logs/temporaria-8/launcher-latest.log'
    case['boot_log']=boot.read_text(errors='replace')[-4000:] if boot.exists() else '<absent>'
    latest=root/'logs/temporaria-8/latest.json'
    if latest.exists():
     summary=json.loads(Path(json.loads(latest.read_text())['summary']).read_text())
     case['summary']={key:summary.get(key) for key in ('exit_code','child_exit_code','logger_failed','cmos_committed','error','finalization_errors')}
   assert run.returncode==0,case['output']
   if mode!='failure':
    latest=json.loads((root/'logs/temporaria-8/latest.json').read_text());summary=json.loads(Path(latest['summary']).read_text())
    assert summary['cmos_committed'] is True and summary['exit_code']==0
    assert summary['game']['stop']==('window-frame-limit' if mode=='short' or video else 'window-closed')
    if video:
     selected=summary['presentation_settings'];actual=summary['game']['window']['presentation']
     expected={'filter':'bicubic' if remastered else 'nearest','scale_mode':5 if remastered else 2,
               'crt_preset':'phosphor','scalefx_amount':37 if remastered else 100,
               'cas_amount':25 if remastered else 50,'bilateral_amount':25 if remastered else 50,
               'smaa':True,'fullscreen_start':False}
     assert selected['game_mode']==summary['audio']['music_mode']==mode.removeprefix('video-')
     assert {key:actual[key] for key in expected}==expected
     assert actual['gpu_validation_frames']==1 and actual['gpu_validation_mismatches']==0
     assert actual['gpu_validation_max_error']<=actual['gpu_validation_tolerance']
     case['video']=expected
     case['readback']={key:actual[key] for key in ('gpu_validation_frames','gpu_validation_mismatches',
                       'gpu_validation_max_error','gpu_validation_tolerance')}
    case.update(stop=summary['game']['stop'],cmos_committed=summary['cmos_committed'],child_exit_code=summary['child_exit_code'])
  result['passed']=True
 except Exception as exc:result['error']=str(exc)
 finally:
  # A timed-out harness may leave its logger/game alive. Reap only processes
  # whose executable or individual argument belongs to this unique test tree.
  prefix=str(temp.absolute()).lower()+os.sep;owned=[]
  for candidate in psutil.process_iter(['pid','exe','cmdline']):
   try:
    if candidate.pid!=os.getpid() and ((candidate.info['exe'] or '').lower().startswith(prefix) or any(str(arg).lower().startswith(prefix) for arg in candidate.info['cmdline'] or [])):owned.append(candidate)
   except (psutil.NoSuchProcess,psutil.AccessDenied):pass
  ids={item.pid for item in owned};user=C.WinDLL('user32',use_last_error=True)
  callback_type=C.WINFUNCTYPE(W.BOOL,W.HWND,C.c_ssize_t)
  user.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
  user.PostMessageW.argtypes=[W.HWND,W.UINT,C.c_size_t,C.c_ssize_t]
  def close(window,_):
   owner=W.DWORD();user.GetWindowThreadProcessId(window,C.byref(owner))
   if owner.value in ids:user.PostMessageW(window,0x10,0,0)
   return True
  callback=callback_type(close);user.EnumWindows.argtypes=[callback_type,C.c_ssize_t];user.EnumWindows(callback,0)
  _,remaining=psutil.wait_procs(owned,timeout=15)
  if remaining:
   result['passed']=False;result['forced_test_cleanup_pids']=[p.pid for p in remaining]
   for candidate in remaining:
    try:candidate.terminate()
    except psutil.NoSuchProcess:pass
   _,remaining=psutil.wait_procs(remaining,timeout=8)
  if remaining:result['cleanup']={'blocked':True,'target':str(temp),'reason':'test-owned process still alive; preserve until released'}
  else:result['cleanup']=g.remove_tree(temp,STAGE)
  (STAGE/('check-process-timeout.json' if '--timeout-probe' in sys.argv else 'check-process.json')).write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result,indent=2));return result['passed']
if __name__=='__main__':raise SystemExit(0 if main() else 1)
