"""Bounded real MK1 sessions using disposable operator CMOS; no user profile writes."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.quality import run as q

CASES=[(1,3,False,True,True,'original',37,'off'),(2,1,False,False,True,'original',0,'bvm-1080'),(3,2,False,True,False,'original',100,'bvm-4k'),(4,58,False,False,False,'original',50,'bvm-soft'),(5,3,True,True,True,'remastered',37,'pvm'),(5,1,True,False,False,'original',37,'energy')]
def parameter(image,index,value=None):
 at=0x1000+index*8
 if value is None:return int.from_bytes(bytes(image[at+n*2]for n in range(4)),'big')
 for n,b in enumerate((value&0xffffffff).to_bytes(4,'big')):image[at+n*2]=b

def main():
 receipt={'passed':False,'scope':'MK1 real boot/main loop with operator settings, presentation and audio; no full-match certification','cases':[]}
 from tools.setup import mk1 as setup_mk1;seed=setup_mk1.seed_path();seedsha=q.sha(seed)
 profile=q.ROOT/'build/native/manual-temporary-8-20261025/profile/cmos.bin';profilesha=q.sha(profile)if profile.exists()else None
 from tools.mk1 import roms as mk1_roms;program=mk1_roms.program_image()
 assert hashlib.sha256(program).hexdigest()=='ae1e5b310c6e512168b2ab7ff796a7656656898cf82ea98735bed0cd12288a06'
 try:
  with q.scratch_tree()as(s,cleanup):
   receipt['cleanup']=cleanup
   ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
   for n,(difficulty,price,free,blood,violence,mode,volume,crt) in enumerate(CASES):
    root=s/str(n);(root/'profile').mkdir(parents=True);image=bytearray(seed.read_bytes());table=(0xfffaeed0-0xff800000)//8+(price-1)*56
    for i,index in enumerate((2,3,4,5,6,7,8,11,12,9,10)):parameter(image,index,int.from_bytes(program[table+i*2:table+i*2+2],'little',signed=True))
    for index,value in ((1,price),(14,difficulty),(18,int(free)),(21,1)):parameter(image,index,value)
    check=(~sum(image[0x1000:0x1150:2]))&65535;image[0x1150]=check>>8;image[0x1152]=check&255
    (root/'profile/cmos.bin').write_bytes(image);dsw=(0xfeff&~0xc000)|(0x4000 if blood else 0)|(0x8000 if violence else 0)
    args=[ps,'-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',q.PRODUCT/'session.ps1','-ProjectRoot',q.ROOT,'-DataRoot',root,'-WindowFrames','113','-CmosCoinage','1','-DswWord',str(dsw),'-GameMode',mode,'-GameVolume',str(volume),'-VisualMode','presentation','-CrtPreset',crt]
    run=q.command(args,s,cwd=q.ROOT,timeout=90);row={'difficulty':difficulty,'coinage':price,'free_play':free,'blood':blood,'violence':violence,'mode':mode,'volume':volume,'crt':crt,'execution':q.compact(run)};receipt['cases'].append(row)
    if not run['passed']:raise RuntimeError('session failed: '+str(row))
    summaries=list((root/'logs').glob('**/summary.json'));assert len(summaries)==1
    report=json.loads(summaries[0].read_text(encoding='utf-8-sig'));game=report['game'];audio=report['audio'];present=game['window']['presentation']
    assert report['exit_code']==report['child_exit_code']==0 and report['cmos_committed'] and not report['error']
    assert game['body']['raw_dsw']==(dsw&~0x80) and game['main']['executed'] and game['main']['calls']>0 and game['window']['frames']==113
    assert present['crt_preset']==crt and present['displayed_frames']>0 and present['last_present_hresult']==0
    assert audio['submitted']==audio['completed'] and audio['submitted']>0 and audio['underruns']==0
    after=(root/'profile/cmos.bin').read_bytes()
    assert all(parameter(after,i)==v for i,v in ((1,price),(14,difficulty),(18,int(free))))
    row.update(passed=True,frames=113,displayed=present['displayed_frames'],main_calls=game['main']['calls'],audio_frames=audio['completed'],underruns=audio['underruns'],guest_dsw=game['body']['raw_dsw'])
    print(json.dumps({k:v for k,v in row.items()if k!='execution'}),flush=True)
   assert q.sha(seed)==seedsha and (q.sha(profile)if profile.exists()else None)==profilesha
   receipt['passed']=True
 except Exception as error:receipt['error']=str(error)
 (q.STAGE/'operator-runtime.json').write_text(json.dumps(receipt,indent=2)+'\n')
 print(json.dumps({'passed':receipt['passed'],'error':receipt.get('error'),'cleanup':receipt.get('cleanup')}));return 0 if receipt['passed']else 1
if __name__=='__main__':raise SystemExit(main())
