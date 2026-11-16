"""RM2: MK3 Remastered layer 2 - DMA and CPU classes (native/mk3/mk3_dma_observer.hpp), the 4x bicubic of the scenery and
of the fighter layers (as MK2: mk5_stage_bicubic.hpp, mk5_fighter_video.hpp, mk5_fighter_bicubic.hpp).

Checks:
- focal contracts (native/mk3/mk3_remaster_tests.hpp, synthetic): canonical frame independent of the observer, flagged
  backdrop colour = canonical colour through the palette at VBLANK, occlusion (fighter/HUD stay nearest), scenery border
  filtered from the hidden scenery, CPU writes, blanking, clear, fighter slots, fighter layers (1x rebuild, HUD on top,
  CPU stores), CPU page fill, objects bound by their creator (fighter children, screen art; K6: body parts, sprays,
  character figures, combo counter, countdown, code row; K7: binding read at the enqueue, effect processes of a
  fighter, screen labels, the text list moved into 0105DC10; K8: effect parent read at the call, arena floor tiles; K9: arena 0Ah floor object; K10: banner of effect 2Ah), CPU picture rows; each with its negative control;
- the route matrix: every receipt of build/native/mk3-m2/routes (its legal tape, from reset, up to its horizon), headless,
  Original and Remastered: per-frame canonical hashes (`rgb`, `prev`, palette) equal, no flagged pixel off its canonical
  colour, fighter layers rebuilding the canonical frame at 1x, DMA classes and bound objects counted, every popped queue
  entry with its enqueue; the 4x frame hash of the Remastered run;
- windows (shared GPU pixel validation), Original and Remastered, route r1sp00 (attract, select, VS, fight with
  projectiles): per-frame canonical hashes equal to each other and to headless, bicubic stage and fighter frames only in
  the Remastered, fps, PCM underruns and the frame preparation (composition) time;
- preview PNGs (Original nearest 4x | Remastered) of the classes of this round, small crops, in build/native/mk3-rm2.
Everything else lives in the scratch tree of tools/mk3/preview.py, removed also on failure.
Receipt: build/native/mk3-m2/rm2-r9.json (K10; K9: rm2-r8.json, K8: rm2-r7.json, K7: rm2-r6.json, K6: rm2-r5.json, K5: rm2-r4.json, round 3: rm2-r3.json, round 2: rm2-r2.json, round 1: rm2.json).
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib,io,json,os,sys,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import explore,preview

ROOT=preview.ROOT
RECEIPT=ROOT/'build/native/mk3-m2/rm2-r9.json'
PNG_DIR=ROOT/'build/native/mk3-rm2'
ROUTES_DIR=ROOT/'build/native/mk3-m2/routes'
CYCLES_PER_FRAME=506*289*6.25/8   # TMS cycles (6.25 MHz) per raster of 506 x 289 pixel clocks (8 MHz)
WORKERS=int(os.environ.get('MK3_REMASTER_WORKERS','3'))   # route-matrix processes (two runs per route, one at a time per worker)
WINDOW_ROUTE='r1sp00'
# Scenes (route, VBLANK, native crop x, y, w, h, what): Original nearest 4x beside the Remastered 4x. Only this round's new
# class (earlier rounds' PNGs stay; K5: the tower frames chained at FF9FCA00 and the plane 0105DB10 on scroll word 0105D9E0).
SCENES=[('r1fin17',3900,60,60,280,72,'faixa-efeito-2a')]   # K10: r1fin17, the two-part banner of effect 2Ah (FFA8E8E0)
PNG_PREFIX='rm2-r9'
W,H=400,254
# Classes: the DmaClass rules and object sites of native/mk3/mk3_dma_observer.hpp (addresses only). The prose evidence of
# each class (rounds 1-K10) described the program's routines and screens and was removed for publication (plan
# 2026-11-15-conformidade-legal.md, 5.1, 16/11/2026); the receipt keeps the class list.
EVIDENCE={c:'mk3_dma_observer.hpp' for c in ('lutador','lutador (filho)','cenario','texto','limpeza','outros','objetos','cpu')}
OPEN=['objetos de 0105DC10 sem sitio classificado ficam objetos (vizinho mais proximo); uma classe propria exige mudar o formato '
      'de 3 bits do backdrop (mk3_scanout)','PNGs rm2-r5 a rm2-r9 nao conferidos pelo usuario']



def focal():
    cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
    with q.scratch_tree() as (temp,cleanup):
        (temp/'main.cpp').write_text('#include "mk3_remaster_tests.hpp"\nint main() { return mk3remaster_tests::Run(); }\n',encoding='ascii')
        exe=temp/'mk3-remaster-tests.exe'
        made=q.command([cc,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-static','-I'+str(ROOT/'native/mk3'),'-I'+str(ROOT/'native/include'),
                        temp/'main.cpp','-o',exe],temp,cwd=ROOT,env=env,timeout=300)
        run=q.command([exe],temp,cwd=ROOT,env=env,timeout=60) if made['passed'] else None
    return made,run,cleanup


def png(dump,crop,path,what,route):
    from PIL import Image
    x,y,w,h=crop
    original=Image.frombytes('RGB',(W,H),bytes.fromhex(dump['rgb'])).crop((x,y,x+w,y+h)).resize((4*w,4*h),Image.NEAREST)
    remastered=Image.frombytes('RGB',(4*W,4*H),bytes.fromhex(dump['rm4x'])).crop((4*x,4*y,4*(x+w),4*(y+h)))
    out=Image.new('RGB',(8*w+4,4*h));out.paste(original,(0,0));out.paste(remastered,(4*w+4,0))
    buf=io.BytesIO();out.save(buf,'PNG',optimize=True);path.write_bytes(buf.getvalue())
    return dict(path=str(path.relative_to(ROOT)).replace(os.sep,'/'),bytes=len(buf.getvalue()),route=route,frame=dump['dump'],crop=list(crop),
                size=[8*w+4,4*h],shows=what,left='Original (nearest 4x)',right='Remasterizada (camada 2)')


def machine_load():
    """Whole-machine CPU load (%, Win32_Processor) next to the window measurements: other processes change fps/underruns."""
    import subprocess
    out=subprocess.run(['powershell','-NoProfile','-Command','(Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average'],
                       capture_output=True,text=True,timeout=60).stdout.strip()
    return float(out) if out else None


def tape_options(p,name):
    """--tape of the receipt's legal tape (written into the preview scratch tree) and the VBLANKs up to its horizon."""
    r=json.loads((ROUTES_DIR/f'{name}.json').read_text('utf-8'));tape=explore.receipt_tape(r);opts=[]
    if tape:
        f=p.temp/f'{name}.tape';f.write_text(''.join(f'{c} {port} {v}\n' for c,port,v in tape),encoding='ascii');opts=['--tape',f]
    return opts,int(r['horizon']//CYCLES_PER_FRAME),r['tape']['sha256']


class Remaster(unittest.TestCase):
    def test_remaster(self):
        r={'evidence':EVIDENCE,'open':OPEN,'milestone':'RM2 (frente C), rodada 9 (K10)','date':time.strftime('%Y-%m-%d'),'committed':False,'installed':False};t={}
        t0=time.perf_counter();made,run,fc=focal();t['focal']=round(time.perf_counter()-t0,1)
        self.assertTrue(made['passed'],q.compact(made));self.assertTrue(run['passed'],q.compact(run));self.assertFalse(fc['exists_after'])
        r['focal']=json.loads(run['stdout'].strip().splitlines()[-1]);self.assertEqual(r['focal']['failures'],0)
        self.assertEqual(r['focal']['detected'],r['focal']['negatives'])
        names=sorted(f.stem for f in ROUTES_DIR.glob('*.json'));routes={};pngs=[];headless={}
        with preview.Preview() as p:
            r['build_seconds']=q.compact(p.build).get('wall_seconds')
            def route(name):
                opts,frames,tape_sha=tape_options(p,name)
                a=time.perf_counter();o=p.run(*opts,'--frames',frames,'--hashes',timeout=7200,output_limit=256<<20);b=time.perf_counter()
                m=p.run(*opts,'--frames',frames,'--hashes','--edition','remastered',timeout=7200,output_limit=256<<20);c=time.perf_counter()
                view=lambda x:[(f['frame'],f['as'],f['rgb'],f['prev'],f['palette']) for f in x['frames']]
                l2=m['summary']['layer2']
                return name,dict(frames=frames,tape_sha256=tape_sha,canonical_equal=view(o)==view(m) and len(o['frames'])==frames,
                                 last_frame=o['summary']['last_frame'],cycles=o['summary']['cycles'],frontier=[o['summary']['frontier'],m['summary']['frontier']],
                                 classes={k:v for k,v in l2['classes'].items() if v['draws']},bound_draws=l2['bound_draws'],cpu_words=l2['cpu_words'],
                                 scenery_frames=l2['scenery_frames'],mismatched=l2['mismatched'],staged_left=l2['staged_left'],
                                 fighter_frames=l2['fighter_frames'],fighter_layers=l2['fighter_layers'],fighter_mismatched=l2['fighter_mismatched'],
                                 rm_frames=sum(1 for f in m['frames'] if f['rm']!='0'*16),
                                 rm_sha256=hashlib.sha256(''.join(f['rm'] for f in m['frames']).encode()).hexdigest(),
                                 wall_seconds=dict(original=round(b-a,1),remastered=round(c-b,1))),[f['prev'] for f in o['frames']] if name==WINDOW_ROUTE else None
            t1=time.perf_counter()
            with ThreadPoolExecutor(WORKERS) as pool:
                for name,row,prev in pool.map(route,names):
                    routes[name]=row
                    if prev:headless[name]=prev
            t['matrix']=round(time.perf_counter()-t1,1)
            # Preview PNGs: one headless Remastered run per scene route, dumps at the scenes' VBLANKs.
            PNG_DIR.mkdir(parents=True,exist_ok=True)
            for old in PNG_DIR.glob(PNG_PREFIX+'-*.png'):old.unlink()   # earlier rounds' PNGs stay
            k=0
            for name in dict.fromkeys(s[0] for s in SCENES):
                scenes=[s for s in SCENES if s[0]==name];opts,_,_=tape_options(p,name)
                d=p.run(*opts,'--frames',max(s[1] for s in scenes),'--edition','remastered','--dump',','.join(str(s[1]) for s in scenes),timeout=3600,output_limit=256<<20)
                dumps={x['dump']:x for x in d['dumps']}
                for _,frame,*crop,what in scenes:
                    k+=1;self.assertIn('rm4x',dumps[frame],frame)
                    pngs.append(png(dumps[frame],crop,PNG_DIR/f'{PNG_PREFIX}-{k}-{what}-frame{frame}.png',what,name))
                del d,dumps
            # Windows: WINDOW_ROUTE, Original and Remastered, with the GPU pixel validation.
            shown={};opts,frames,_=tape_options(p,WINDOW_ROUTE)
            load={}
            for edition in ('original','remastered'):
                env=dict(preview.EDITIONS[edition],MK1_FULLSCREEN='0',MK1_GRAPHICS_VALIDATE='1');load[edition]=[machine_load()]
                shown[edition]=p.run(*opts,'--window','--audio','--hashes','--edition',edition,'--frames',frames,
                                     '--linger',1,'--cmos-profile',p.temp/f'profile-{edition}',timeout=900,window_env=env)
                load[edition].append(machine_load())
        windows={}
        for e,s in shown.items():
            x=s['summary'];w=x['window'];prev=[f['prev'] for f in s['frames']]
            windows[e]=dict(route=WINDOW_ROUTE,machine_load_percent_before_after=load[e],canonical_equal_headless=prev==headless[WINDOW_ROUTE],frames=x['frames'],fps=x['fps'],realtime_factor=x['realtime_factor'],
                            wall_seconds=x['wall_seconds'],underruns=x['audio']['underruns'],underrun_records=s['underrun_records'],submitted=x['audio']['submitted'],
                            bicubic_stage_frames=w.get('bicubic_stage_frames'),bicubic_stage_validation_frames=w.get('bicubic_stage_validation_frames'),
                            bicubic_fighter_frames=w.get('bicubic_fighter_frames'),bicubic_fighter_validation_frames=w.get('bicubic_fighter_validation_frames'),
                            layer2=x.get('layer2'),window={k:w[k] for k in w if k in ('vsync','repeated_frames','coalesced_host_frames','displayed_frames','frame_preparation_ms','producer_intervals',
                                                                                     'gpu_validation_frames','gpu_validation_mismatches','gpu_validation_max_error')})
        # The receipt is written before the checks, so a failing run (e.g. PCM underruns on a loaded machine) is recorded
        # with its measurements; `windows_passed` and `matrix_passed` say whether the checks below held.
        ok=all(w['canonical_equal_headless'] and not w['underruns'] and not w['window']['gpu_validation_mismatches'] for w in windows.values())
        ok&=windows['original']['bicubic_stage_frames']==0 and windows['original']['bicubic_fighter_frames']==0
        ok&=windows['remastered']['bicubic_stage_frames']>0 and windows['remastered']['bicubic_fighter_frames']>0
        matrix_ok=all(x['canonical_equal'] and not x['mismatched'] and not x['fighter_mismatched'] and not x['staged_left'] for x in routes.values())
        totals={k:sum(x['bound_draws'][k] for x in routes.values()) for k in ('child','screen_art','text')}
        totals.update({k:sum(x['classes'].get(c,{}).get('draws',0) for x in routes.values()) for k,c in (('unclassified_draws','sem classe'),('world_draws','objetos'))})
        totals['picture_words']=sum(x['cpu_words']['picture'] for x in routes.values())
        r.update(routes=routes,matrix=dict(routes=len(routes),frames=sum(x['frames'] for x in routes.values()),
                                          canonical_equal=sum(x['canonical_equal'] for x in routes.values()),bound=totals,workers=WORKERS),
                 matrix_passed=matrix_ok,windows=windows,windows_passed=ok,pngs=pngs,timings_seconds=t,
                 total_seconds=round(time.perf_counter()-t0,1),cleanup=dict(preview=p.cleanup,focal=fc))
        RECEIPT.parent.mkdir(parents=True,exist_ok=True)
        old=json.loads(RECEIPT.read_text('utf-8')) if RECEIPT.exists() else {}
        RECEIPT.write_text(json.dumps({**old,**r},indent=1,ensure_ascii=False)+'\n',encoding='utf-8')
        self.assertFalse(p.cleanup.get('exists_after'))
        self.assertEqual(len(routes),len(names));self.assertGreaterEqual(len(routes),36)   # every receipt of ROUTES_DIR (K3: 36; K4: 67)
        for name,x in routes.items():
            self.assertTrue(x['canonical_equal'],name);self.assertEqual(x['mismatched'],0,name)
            self.assertEqual(x['fighter_mismatched'],0,name);self.assertEqual(x['staged_left'],0,name)
        self.assertGreater(totals['child'],0);self.assertGreater(totals['screen_art'],0);self.assertGreater(totals['picture_words'],0)
        self.assertGreater(totals['text'],0);self.assertEqual(totals['unclassified_draws'],0)
        for e,w in windows.items():
            self.assertTrue(w['canonical_equal_headless'],e);self.assertEqual(w['underruns'],0,e)
            self.assertEqual(w['window']['gpu_validation_mismatches'],0,e)
        self.assertEqual(windows['original']['bicubic_stage_frames'],0);self.assertGreater(windows['remastered']['bicubic_stage_frames'],0)
        self.assertEqual(windows['original']['bicubic_fighter_frames'],0);self.assertGreater(windows['remastered']['bicubic_fighter_frames'],0)


if __name__=='__main__':unittest.main()
