"""Small local MK2 v1 package; external authenticated core, hard-linked ROMs, independent profile."""
from pathlib import Path
import argparse,json,os,sys,shutil
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q

ROOT=Path(__file__).resolve().parents[2]
import runpy
backend_arguments=runpy.run_path(ROOT/'tools/launcher_backend_build.py')['arguments']
HERE=Path(__file__).resolve().parent
CORE=Path('D:/Emuladores/Mame/mame2080/mame.exe')
CORE_SHA='84b690dad588253139ea49ae5e3c9fcddf9df7bcd526fccd1724ec7e09120dec'
STAGE=Path('build/native/mk2-arcade-v1')

def unlinked(path):
    for p in (path,*path.parents):
        if p.is_symlink() or p.is_junction():raise ValueError('Linked product path: '+str(p))

def prepare(root=ROOT):
    root=Path(root).absolute();unlinked(root);assert q.sha(CORE)==CORE_SHA,'Core SHA-256 differs'
    manifest=json.loads((ROOT/'tools/mk2/roms-l31.json').read_text('utf-8'))
    for rom in manifest['roms']:
        source=ROOT/'roms/mk2'/rom['path'];unlinked(source)
        assert source.stat().st_size==rom['size'] and q.sha(source)==rom['sha256'],rom['path']
    product=root/STAGE/'product';unlinked(product);product.mkdir(parents=True,exist_ok=True)
    rows=[]
    for rom in manifest['roms']:
        source=ROOT/'roms/mk2'/rom['path'];relative='mk2/'+rom['upstream_name'];target=product/'roms'/relative
        unlinked(target);target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():os.link(source,target)
        assert q.sha(target)==rom['sha256'],target
        rows.append(dict(path=relative,size=rom['size'],sha256=rom['sha256']))
    (product/'session.ps1').write_bytes((HERE/'session.ps1').read_bytes())
    from tools.setup import mk2 as setup_mk2
    seed=setup_mk2.seed_path()   # written by the local setup from the user's ROMs
    assert seed.stat().st_size==16384 and q.sha(seed)=='f401005e9be6b161ba3becb3cc20b8fd72359e3234652af3b5c2fbbce0d06e1f'
    shutil.copyfile(seed,product/'factory-default-cmos.bin')
    (product/'engine-path.txt').write_text(str(CORE)+'\n',encoding='utf-8')
    controls=product/'controls';controls.mkdir(exist_ok=True)
    entries=[]
    for player in (1,2):
        mappings={'BUTTON1':f'JOYCODE_{player}_BUTTON3','BUTTON2':f'JOYCODE_{player}_BUTTON5 OR JOYCODE_{player}_BUTTON6',
                  'BUTTON3':f'JOYCODE_{player}_BUTTON4','BUTTON4':f'JOYCODE_{player}_BUTTON1','BUTTON5':f'JOYCODE_{player}_BUTTON2'}
        keyboard=('LCONTROL','LALT','SPACE','LSHIFT','Z') if player==1 else ('A','S','Q','W','X')
        for button,key in zip(mappings,keyboard):
            entries.append(f'<port type="P{player}_{button}"><newseq type="standard">KEYCODE_{key} OR {mappings[button]}</newseq></port>')
        entries.append(f'<port type="COIN{player}"><newseq type="standard">KEYCODE_{4+player} OR JOYCODE_{player}_BUTTON7</newseq></port>')
        entries.append(f'<port type="START{player}"><newseq type="standard">KEYCODE_{player} OR JOYCODE_{player}_BUTTON8</newseq></port>')
    (controls/'mk2-default.cfg').write_text('<?xml version="1.0"?><mameconfig version="10"><system name="default"><input>'+''.join(entries)+'</input></system></mameconfig>',encoding='utf-8')
    art=product/'artwork/mk2';art.mkdir(parents=True,exist_ok=True)
    (art/'default.lay').write_text('''<?xml version="1.0"?><mamelayout version="2">
<element name="side"><rect><color red="0.05" green="0.035" blue="0.015" /></rect></element>
<view name="Original"><screen index="0"><bounds x="0" y="0" width="4" height="3" /></screen></view>
<view name="Moldura"><element ref="side"><bounds x="-0.16" y="-0.16" width="4.32" height="3.32" /></element><screen index="0"><bounds x="0" y="0" width="4" height="3" /></screen></view>
</mamelayout>''',encoding='utf-8')
    result=dict(version='MK2 Arcade Original v1',revision='L3.1',core='MAME 0.280',core_path=str(CORE),core_sha256=CORE_SHA,
                own_native_port=False,local_rom_aliases=True,rom_payload_copied=False,rom_storage='hard links to authenticated source ROMs',roms_required=rows,
                factory_cmos=dict(file='factory-default-cmos.bin',bytes=16384,sha256=q.sha(seed)),
                files={str(p.relative_to(product)).replace('\\','/'):q.sha(p) for p in (product/'session.ps1',product/'engine-path.txt',product/'factory-default-cmos.bin',controls/'mk2-default.cfg',art/'default.lay')})
    (product/'manifest.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result

def main():
    result={'passed':False};stage=ROOT/STAGE;stage.mkdir(parents=True,exist_ok=True)
    preserved=json.loads((ROOT/'build/native/mk2/first-fight-preparation-v8-source-freeze.json').read_text('utf-8'))['mk1']
    assert all(q.sha(ROOT/p)==h for p,h in preserved.items())
    try:
        prepare()
        with q.scratch_tree() as (temp,cleanup):
            result['cleanup']=cleanup;cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH'],'TEMP':str(temp),'TMP':str(temp)}
            for name,sources in [('MK2-V1-ARCADE-ORIGINAL.exe',['mk2_starter.cpp','launcher_backend.cpp']),('triunit.exe',['launcher_main.cpp','launcher_renderer.cpp','launcher_backend.cpp'])]:
                exe=temp/name;libs=['user32'] if name.startswith('MK2-') else ['d3d12','dxgi','d3dcompiler','dxguid','windowscodecs','ole32','uuid','gdi32','user32','shell32','xinput9_1_0']
                build=q.command([cc,'-std=c++17','-O2','-s','-Wall','-Wextra','-Werror','-static','-municode','-mwindows',*[ROOT/'native/launcher'/s for s in sources],*['-l'+lib for lib in libs],'-Wl,--no-insert-timestamp','-o',exe]+backend_arguments(ROOT),temp,cwd=ROOT,env=env,timeout=120)
                result[name]={'build':q.compact(build)};assert build['passed'],build.get('stdout','')[-3000:]
                destination=ROOT/name;unlinked(destination);shutil.copy2(exe,destination);result[name].update(sha256=q.sha(destination),bytes=destination.stat().st_size)
        assert all(q.sha(ROOT/p)==h for p,h in preserved.items()),'MK1 changed'
        result.update(passed=True,mk1_preserved=preserved)
    except Exception as error:result['error']=repr(error)
    finally:(stage/'build.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='mk1_preserved'},indent=2));return result['passed']

if __name__=='__main__':raise SystemExit(0 if main() else 1)
