"""Build/run real GPU blend/readback/resize checks; clean compiler outputs."""
from pathlib import Path
import importlib.util,subprocess,os,json,uuid
ROOT=Path(__file__).resolve().parents[3];STAGE=ROOT/'build/native/manual-temporary-8-20261025'
def main():
    STAGE.mkdir(exist_ok=True);t=STAGE/('temporary-renderer-'+uuid.uuid4().hex);t.mkdir();rec={'passed':False}
    spec=importlib.util.spec_from_file_location('guard',ROOT/'tools/quality/temporary_tree.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
    try:
        cc=Path('C:/msys64/mingw64/bin/g++.exe');env=dict(os.environ,PATH=str(cc.parent)+os.pathsep+os.environ['PATH'],TEMP=str(t),TMP=str(t));exe=t/'renderer.exe'
        command=[str(cc),'-std=c++17','-O2','-Wall','-Wextra','-Werror','-Wno-missing-field-initializers','-static','-Inative/launcher','native/launcher/renderer_contract.cpp','native/launcher/launcher_renderer.cpp','-ld3d12','-ldxgi','-ld3dcompiler','-ldxguid','-lwindowscodecs','-lole32','-luuid','-lgdi32','-luser32','-Wl,--no-insert-timestamp','-o',str(exe)]
        c=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,timeout=90)
        assert c.returncode==0,c.stderr.decode(errors='replace')
        r=subprocess.run([str(exe)],cwd=ROOT,env=env,capture_output=True,timeout=30)
        rec.update(exit_code=r.returncode,output=(r.stdout+r.stderr).decode(errors='replace'))
        assert r.returncode==0,rec
        rec.update(json.loads(r.stdout));assert rec['passed']
    finally:
        rec['cleanup']=g.remove_tree(t,STAGE);(STAGE/'renderer-contract.json').write_text(json.dumps(rec,indent=2)+'\n');print(json.dumps(rec,indent=2))
if __name__=='__main__':main()
