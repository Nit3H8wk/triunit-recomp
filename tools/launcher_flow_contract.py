"""Real isolated portable EXE -> UI -> game -> logger -> collection tests.

Test workspace uses immutable hardlinks to product/ROM/assets; mutable files
are isolated. Read CMOS and compact logger state only; no test dumps/video.
"""
from pathlib import Path
import ctypes as C
from ctypes import wintypes as W
import importlib.util,json,os,subprocess,time,uuid
import psutil
ROOT=Path(__file__).resolve().parents[1];STAGE=ROOT/'build/native/manual-temporary-5-20261025'
import runpy
backend_arguments=runpy.run_path(ROOT/'tools/launcher_backend_build.py')['arguments']

def main():
    temporary=STAGE/('temporary-flow-'+uuid.uuid4().hex);temporary.mkdir();root=temporary/'root';root.mkdir();rec={'passed':False};process=None;scope=None;hwnd=None
    spec=importlib.util.spec_from_file_location('guard',ROOT/'tools/quality/temporary_tree.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
    user=C.WinDLL('user32',use_last_error=True)
    user.FindWindowW.argtypes=[W.LPCWSTR,W.LPCWSTR];user.FindWindowW.restype=W.HWND
    user.PostMessageW.argtypes=[W.HWND,W.UINT,C.c_size_t,C.c_ssize_t];user.PostMessageW.restype=W.BOOL
    user.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)];user.GetWindowThreadProcessId.restype=W.DWORD
    user.IsIconic.argtypes=[W.HWND];user.IsIconic.restype=W.BOOL
    def key(k):user.PostMessageW(hwnd,0x100,k,0);user.PostMessageW(hwnd,0x101,k,0)
    def wait(predicate,seconds=25):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            v=predicate()
            if v:return v
            if process and process.poll() is not None:raise AssertionError(('early launcher exit',process.returncode))
            time.sleep(.1)
        raise AssertionError('flow condition timed out')
    def linked(path,relative):
        dest=root/relative;dest.parent.mkdir(parents=True,exist_ok=True);os.link(path,dest)
    try:
        linked(ROOT/'MK1-TEMPORARIA-5.exe','MK1-TEMPORARIA-5.exe')
        for p in (STAGE/'product').iterdir():
            if p.is_file():linked(p,p.relative_to(ROOT))
        manifest=json.loads((STAGE/'product/manifest.json').read_text())
        for rom in manifest['roms_required']:linked(ROOT/'roms'/rom['path'],Path('roms')/rom['path'])
        profile=root/'build/native/manual-temporary-5-20261025/profile';profile.mkdir()
        (profile/'cmos.bin').write_bytes((STAGE/'product/factory-default-control-input.bin').read_bytes())
        (profile/'launcher.ini').write_text('[Launcher]\nUIVolume=0\nReducedMotion=1\n[MK1]\nScanlines=1\nFilter=1\n')
        logroot=root/'logs/temporaria-5'
        def boot():
            nonlocal process,hwnd
            process=subprocess.Popen([str(root/'MK1-TEMPORARIA-5.exe')])
            def ownwindow():
                h=user.FindWindowW('MkArcadeCollection',None)
                if h:
                    pid=W.DWORD();user.GetWindowThreadProcessId(h,C.byref(pid))
                    if pid.value==process.pid:return h
            hwnd=wait(ownwindow);time.sleep(.35)
        boot();key(0x0d);time.sleep(.15);key(0x0d)
        wait(lambda: user.IsIconic(hwnd))
        def active():
            for live in logroot.glob('sessao-*/live.json'):
                try:
                    s=json.loads(live.read_text());
                    if s.get('scanout_frame',0)>=25:return s
                except (OSError,ValueError):pass
        live=wait(active);game=user.FindWindowW('Mk5TemporalScanout',None);assert game
        user.PostMessageW(game,0x10,0,0)
        def returned():
            try:return not user.IsIconic(hwnd) and (logroot/'latest.json').exists() and 'game-return exit=0' in (logroot/'ui-latest.log').read_text()
            except OSError:return False
        wait(returned)
        latest=json.loads((logroot/'latest.json').read_text(encoding='utf-8-sig'))
        summary=json.loads(Path(latest['summary']).read_text(encoding='utf-8-sig'))
        assert summary['exit_code']==0 and summary['cmos_committed'],summary
        assert summary['presentation_settings']['scanlines']==.25 and summary['presentation_settings']['filter']=='linear'
        assert 'game-return exit=0' in (logroot/'ui-latest.log').read_text()
        rec['ui_game_return']={'passed':True,'observed_frame':live['scanout_frame'],'stop':summary['game']['stop'],'cmos_committed':True,'presentation':summary['presentation_settings']}
        # Closing the collection while its game is active closes all owned work.
        key(0x0d);time.sleep(.15);key(0x0d);wait(lambda:user.IsIconic(hwnd));user.PostMessageW(hwnd,0x10,0,0)
        assert process.wait(timeout=30)==0
        summary=json.loads(Path(json.loads((logroot/'latest.json').read_text(encoding='utf-8-sig'))['summary']).read_text(encoding='utf-8-sig'))
        assert summary['exit_code']==0 and summary['cmos_committed']
        rec['close_during_game']={'passed':True,'stop':summary['game']['stop'],'cmos_committed':True}
        # Exercise exceptional unwinding in the actual App class.
        cc=Path('C:/msys64/mingw64/bin/g++.exe');env=dict(os.environ,PATH=str(cc.parent)+os.pathsep+os.environ['PATH'],TEMP=str(temporary),TMP=str(temporary));exe=temporary/'scope-test.exe'
        command=[str(cc),'-std=c++17','-O2','-Wall','-Wextra','-Werror','-static','tools/launcher_cleanup_contract.cpp','native/launcher/launcher_renderer.cpp','native/launcher/launcher_backend.cpp',*[f'-l{x}' for x in ['d3d12','dxgi','d3dcompiler','dxguid','windowscodecs','ole32','uuid','gdi32','user32','shell32','winmm','xinput9_1_0']],'-Wl,--no-insert-timestamp','-o',str(exe)]+backend_arguments(ROOT)
        c=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,timeout=90);assert c.returncode==0,c.stderr.decode(errors='replace')
        scope=subprocess.Popen([str(exe),str(root)],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        scope_stdout,scope_stderr=scope.communicate(timeout=35);assert scope.returncode==0,(scope.returncode,scope_stderr.decode(errors='replace'))
        final=json.loads(Path(json.loads((logroot/'latest.json').read_text(encoding='utf-8-sig'))['summary']).read_text(encoding='utf-8-sig'));assert final['exit_code']==0 and final['cmos_committed']
        rec['exception_cleanup']={**json.loads(scope_stdout),'cmos_committed':True,'session_exit_code':final['exit_code']}
        (root/'roms'/manifest['roms_required'][0]['path']).unlink()
        missing=subprocess.run([str(exe),str(root),'--missing'],cwd=ROOT,env=env,capture_output=True,timeout=15);assert missing.returncode==0,missing.stderr.decode(errors='replace')
        rec['missing_rom']=json.loads(missing.stdout)
        rec.update(passed=True,storage='product/ROM/assets immutable hardlinks; isolated mutable profile and logs',no_video_pcm_or_memory_dumps=True)
    except BaseException as e:rec['error']=repr(e);raise
    finally:
        # Track the scope executable too: communicate(timeout) must never leave
        # its unlimited native game/logger behind. Restrict fallback termination
        # to this test's unique, resolved temporary path and its own processes.
        prefix=str(temporary.absolute()).lower()+os.sep
        owned=[]
        for candidate in psutil.process_iter(['pid','exe','cmdline']):
            try:
                image=(candidate.info['exe'] or '').lower()
                command=candidate.info['cmdline'] or []
                is_ours=image.startswith(prefix) or any(str(arg).lower().startswith(prefix) for arg in command)
                if is_ours:owned.append(candidate)
            except (psutil.NoSuchProcess,psutil.AccessDenied):pass
        ids={p.pid for p in owned}
        callback_type=C.WINFUNCTYPE(W.BOOL,W.HWND,C.c_ssize_t)
        def close_owned(window,_):
            pid=W.DWORD();user.GetWindowThreadProcessId(window,C.byref(pid))
            if pid.value in ids:user.PostMessageW(window,0x10,0,0)
            return True
        callback=callback_type(close_owned);user.EnumWindows.argtypes=[callback_type,C.c_ssize_t];user.EnumWindows.restype=W.BOOL
        user.EnumWindows(callback,0)
        _,remaining=psutil.wait_procs(owned,timeout=15)
        if remaining:
            rec['passed']=False;rec['forced_test_cleanup_pids']=[p.pid for p in remaining]
            for p in remaining:
                try:p.terminate()
                except psutil.NoSuchProcess:pass
            _,remaining=psutil.wait_procs(remaining,timeout=8)
        if remaining:
            rec['cleanup']={'blocked':True,'target':str(temporary),'reason':'test-owned process still alive; preserve until released'}
        else:rec['cleanup']=g.remove_tree(temporary,STAGE)
        (STAGE/'flow-contract.json').write_text(json.dumps(rec,indent=2)+'\n');print(json.dumps(rec,indent=2))
if __name__=='__main__':main()
