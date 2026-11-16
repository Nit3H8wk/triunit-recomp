"""Actual core gameplay via legal input requests in a disposable profile; one small PNG proof."""
import json,os,subprocess,sys,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2_arcade.build import prepare,ROOT,CORE,STAGE,unlinked
from tools.quality import run as q

def main():
    result={'passed':False,'scope':'Legal Coin/Start/HP requests, actual reset and authenticated factory CMOS only; no game RAM/save-state import or product autoplay','physical_gamepad_tested':False}
    try:
        with q.scratch_tree() as (temp,cleanup):
            result['cleanup']=cleanup;prepare(temp)
            ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
            inspected=subprocess.run([str(ps),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(ROOT/'tools/mk2_arcade/session.ps1'),'-ProjectRoot',str(temp),'-InspectOnly','-Headless'],capture_output=True,text=True,timeout=30)
            assert inspected.returncode==0,inspected.stderr
            args=json.loads(inspected.stdout)['arguments']
            args[args.index('-video')+1]='d3d'
            args+=['-seconds_to_run','40','-autoboot_delay','0','-snapname','fight','-snapsize','400x254','-autoboot_script',str(temp/'play.lua')]
            for key in ['-homepath','-cfg_directory','-nvram_directory','-state_directory','-snapshot_directory','-input_directory','-diff_directory']:Path(args[args.index(key)+1]).mkdir(parents=True,exist_ok=True)
            initialized=subprocess.run([str(ps),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(ROOT/'tools/mk2_arcade/session.ps1'),'-ProjectRoot',str(temp),'-InitializeOnly'],capture_output=True,text=True,timeout=30)
            assert initialized.returncode==0,initialized.stderr
            (temp/'play.lua').write_text('''local m=manager.machine
local coin=assert(m.ioport.ports[":IN1"].fields["Coin 1"])
local start=assert(m.ioport.ports[":IN1"].fields["1 Player Start"])
local hp=assert(m.ioport.ports[":IN0"].fields["P1 High Punch"])
for name,f in pairs({coin=coin,start=start,hp=hp}) do print("MAPPING",name,m.input:seq_to_tokens(f:input_seq("standard"))) end
local frame=0
proof_sub=emu.add_machine_frame_notifier(function()
 frame=frame+1
 if frame==1200 or frame==1220 or frame==1300 or frame==1320 then coin:set_value((frame==1200 or frame==1300) and 1 or 0);print("REQUEST","coin",frame) end
 if frame==1400 or frame==1410 then start:set_value(frame==1400 and 1 or 0);print("REQUEST","start",frame) end
 if frame==1500 or frame==1510 then hp:set_value(frame==1500 and 1 or 0);print("REQUEST","hp",frame) end
 if frame==2000 then m.video:snapshot();print("FIGHT_SNAPSHOT",frame,m.devices[":maincpu"].state["PC"].value) end
end)
''',encoding='ascii')
            execution=q.command([CORE,*args],temp,cwd=temp,timeout=45);result['execution']=q.compact(execution)
            assert execution['passed'],result['execution'];out=execution.get('stdout','');assert 'FIGHT_SNAPSHOT' in out
            result['mappings']=[line for line in out.splitlines() if line.startswith('MAPPING')]
            for name,key in [('coin','KEYCODE_5'),('start','KEYCODE_1'),('hp','KEYCODE_LCONTROL')]:assert any(name in line and key in line for line in result['mappings']),name
            snapshots=list((temp/STAGE/'profile/snap').rglob('*.png'));assert len(snapshots)==1 and snapshots[0].stat().st_size<250000
            proof=ROOT/STAGE/'gameplay-proof.png';unlinked(proof);shutil.copyfile(snapshots[0],proof)
            result.update(passed=True,small_image=str(proof),image_sha256=q.sha(proof),image_bytes=proof.stat().st_size)
    except Exception as error:result['error']=repr(error)
    p=ROOT/STAGE/'playcheck.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2));return result['passed']

if __name__=='__main__':raise SystemExit(0 if main() else 1)
