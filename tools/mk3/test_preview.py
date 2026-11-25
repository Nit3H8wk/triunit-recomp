"""J3 host: the MK3 native executable mk3 (native/mk3/mk3_preview_main.cpp through tools/mk3/preview.py).

Checks, all on one build in one scratch tree:
- inputs: every key and pad control alone (mk3 --input-map) against the ports of INPUT_PORTS(mk3), parsed from
  docs/investigation/sources/midwunit.cpp: exactly the expected bit low, nothing else mapped, every switch of IN0/IN1/IN2
  reachable from the keyboard (Door Interlock excepted: no MAME default);
- a headless smoke of N frames run twice (same per-frame hashes, final frame and PCM counts); the full headless run to
  the `jogo` frontier or the horizon; the `estrito` profile as negative control (strict frontier with its PC);
- the legal round start tape (tools/mk3/fight_route.tape) applied by --tape at TMS boundaries: the DCS command 0x233D must
  be written at the Original's cycle; negative: the same tape without the Start press must not reach it;
- CMOS: window runs save the NVRAM to their profile directory (from the seed when empty) and load it back, only after
  the shared D3D12 presentation check (mk5_profile_presentation.hpp); a headless run loads the profile and leaves it
  unchanged; a profile of the wrong size and a held lock fail closed; the MK1/MK2 profiles and packages, the
  MK3 temporary core profile (kept on disk, unused), both seeds and the default MK3 profile are hashed before and after;
- Original and Remastered layer 1 (EDITIONS of preview.py) in a window, with the shared GPU pixel validation: per
  frame canonical hashes equal between the editions and to the headless run, presentation settings differ; the
  Windows PCM queue without underrun.
The windows appear on the desktop for a few seconds. Receipt: build/native/mk3-m2/j3-host.json (key `preview`).
"""
from pathlib import Path
import hashlib,json,re,sys,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import preview,reference
from tools.mk3.replay import read_tape
from tools.mk3.test_scanout_original import update_receipt
from tools.mk3 import preview_install as install

ROOT=preview.ROOT
FRAMES=300
HORIZON=20000   # ~6 min of machine time
STRICT_FRONTIER='unobserved branch; PC 4287779776'   # 0xff9253c0, docs/MK3_DEVELOPMENT.md (J1)
TAPE_FILE=ROOT/'tools/mk3/fight_route.tape'
FIGHT,FIGHT_CYCLE,FIGHT_FRAMES=0x233d,283339365,2485   # Original: low byte of 0x233D at TMS 283,339,365 (45.334 s = VBLANK 2480)
DRIVER=ROOT/'docs/investigation/sources/midwunit.cpp'
PRESERVED=[*install.PRESERVED,str(reference.SEED.relative_to(ROOT)),'generated/mk2/45b3285496db555efaf4a3608a4f59845dd47a82e4a0593607e0592f47b36f23/mk2-factory-default-cmos.bin',
           str(preview.CMOS_PROFILE.relative_to(ROOT))]
P1,P2=1,2
KEYS={0x26:('JOYSTICK_UP',P1),0x28:('JOYSTICK_DOWN',P1),0x25:('JOYSTICK_LEFT',P1),0x27:('JOYSTICK_RIGHT',P1),
      ord('A'):('BUTTON1',P1),ord('S'):('BUTTON2',P1),ord('D'):('BUTTON3',P1),ord('Z'):('BUTTON4',P1),ord('X'):('BUTTON5',P1),ord('C'):('BUTTON6',P1),
      ord('I'):('JOYSTICK_UP',P2),ord('K'):('JOYSTICK_DOWN',P2),ord('J'):('JOYSTICK_LEFT',P2),ord('L'):('JOYSTICK_RIGHT',P2),
      ord('F'):('BUTTON1',P2),ord('G'):('BUTTON2',P2),ord('H'):('BUTTON3',P2),ord('V'):('BUTTON4',P2),ord('B'):('BUTTON5',P2),ord('N'):('BUTTON6',P2),
      ord('5'):('COIN1',P1),ord('6'):('COIN2',P1),ord('1'):('START1',P1),ord('2'):('START2',P1),
      # MAME 0.280 defaults (measured on the pinned core: Tilt T, Service Mode F2, Service 1 9, Coin 3/4 7/8, Volume -/=, Banknote 1 Backspace)
      ord('T'):('TILT',P1),0x71:('SERVICE',P1),ord('9'):('SERVICE1',P1),ord('7'):('COIN3',P1),ord('8'):('COIN4',P1),
      0xbd:('VOLUME_DOWN',P1),0xbb:('VOLUME_UP',P1),0x08:('BILL1',P1)}
PAD={'dpad_up':'JOYSTICK_UP','dpad_down':'JOYSTICK_DOWN','dpad_left':'JOYSTICK_LEFT','dpad_right':'JOYSTICK_RIGHT',
     'stick_up':'JOYSTICK_UP','stick_down':'JOYSTICK_DOWN','stick_left':'JOYSTICK_LEFT','stick_right':'JOYSTICK_RIGHT',
     'x':'BUTTON1','rb':'BUTTON2','rt':'BUTTON2','y':'BUTTON3','a':'BUTTON4','b':'BUTTON5','lb':'BUTTON6','lt':'BUTTON6',
     'back':'COIN','start':'START','ls':None,'rs':None}


def driver_ports():
    """{(type, player): (port index 0-2, mask)} of IN0/IN1/IN2 in INPUT_PORTS(mk3) (unused bits left out)."""
    text=DRIVER.read_text('utf-8');body=text[text.index('INPUT_PORTS_START( mk3 )'):];body=body[:body.index('INPUT_PORTS_END')]
    out={};port=None
    for line in body.splitlines():
        m=re.search(r'PORT_START\("(\w+)"\)',line)
        if m:port={'IN0':0,'IN1':1,'IN2':2}.get(m.group(1));continue
        if port is None:continue
        m=re.search(r'PORT_BIT\(\s*(0x[0-9a-f]+),\s*IP_ACTIVE_LOW,\s*IPT_(\w+)\s*\)',line) or re.search(r'PORT_SERVICE_NO_TOGGLE\(\s*(0x[0-9a-f]+)',line)
        if not m:continue
        kind=m.group(2) if m.lastindex==2 else 'SERVICE'
        if kind=='UNUSED':continue
        player=int(re.search(r'PORT_PLAYER\((\d)\)',line).group(1)) if 'PORT_PLAYER' in line else 1
        assert (kind,player) not in out,(kind,player);out[(kind,player)]=(port,int(m.group(1),16))
    return out


def expected(field,ports):
    p=[0xffff]*3
    if field:port,mask=ports[field];p[port]&=~mask
    return p


def tree(path):
    path=ROOT/path
    if path.is_file():return {str(path.relative_to(ROOT)):q.sha(path)}
    return {str(p.relative_to(ROOT)):q.sha(p) for p in sorted(path.rglob('*')) if p.is_file()} if path.is_dir() else {}


def snapshot():return {k:v for p in PRESERVED for k,v in tree(p).items()}


class PreviewTest(unittest.TestCase):
    def test_preview(self):
        started=time.perf_counter();r={};t={}
        before=snapshot();self.assertTrue(any('mk2-native-v1/product/profiles' in k.replace(chr(92),'/') for k in before),'MK2 native profile present')
        tape=read_tape(TAPE_FILE);start=next(i for i,e in enumerate(tape) if e[1]==3 and not e[2]&4)   # IN2 bit 2 START1 pressed
        no_start=tape[:start]+tape[start+2:]   # without the press and its release
        with preview.Preview() as p:
            r['build_seconds']=q.compact(p.build).get('wall_seconds')
            # 1. Inputs, one control at a time.
            m=q.command([p.exe,'--input-map'],p.temp,cwd=ROOT,env=p.env,timeout=30)
            self.assertTrue(m['passed'],m['stdout'])
            mapping=json.loads(m['stdout'].strip().splitlines()[-1])['input_map']
            ports=driver_ports()
            self.assertEqual({row[0]:row[1:] for row in mapping['keys']},{vk:expected(f,ports) for vk,f in KEYS.items()})
            reachable=set(KEYS.values());missing=sorted(set(ports)-reachable)
            self.assertEqual(missing,[('DOOR',1)],missing)
            pads={(pl,name):v for pl,name,*v in mapping['pads']}
            for (pl,name),v in pads.items():
                kind=PAD[name];field=None if kind is None else (f'{kind}{pl}',1) if kind in ('COIN','START') else (kind,pl)
                self.assertEqual(v,expected(field,ports),(pl,name))
            self.assertEqual(len(pads),2*len(PAD));self.assertEqual(mapping['rest'],[0xffff]*3)
            # 2. Headless smoke twice, full horizon, strict negative.
            t0=time.perf_counter();a=p.run('--frames',FRAMES,'--hashes');b=p.run('--frames',FRAMES,'--hashes');t['smoke']=time.perf_counter()-t0
            for s in (a,b):self.assertEqual(s['summary']['frames'],FRAMES)
            self.assertEqual([f['prev'] for f in a['frames']],[f['prev'] for f in b['frames']])
            sa,sb=a['summary'],b['summary']
            self.assertEqual((sa['last_frame'],sa['cycles'],sa['audio']),(sb['last_frame'],sb['cycles'],sb['audio']))
            self.assertGreater(sa['audio']['source_samples'],0);self.assertFalse(sa['cmos']['profile'])
            t0=time.perf_counter();full=p.run('--frames',HORIZON,timeout=1800)['summary'];t['full']=time.perf_counter()-t0
            self.assertTrue('; PC ' in full['frontier'] or (full['frontier']=='none' and full['frames']==HORIZON),full['frontier'])
            strict=p.run('--strict')['summary']
            self.assertIn(STRICT_FRONTIER,strict['frontier']);self.assertLess(strict['cycles'],full['cycles'])
            # 3. round start tape and its negative (the same tape without the Start press).
            neg_tape=p.temp/'no-start.tape';neg_tape.write_text(''.join(f'{c} {pt} {v}\n' for c,pt,v in no_start),encoding='ascii')
            t0=time.perf_counter()
            fight=p.run('--tape',TAPE_FILE,'--watch-dcs',hex(FIGHT),'--frames',FIGHT_FRAMES,timeout=1800)['summary']
            t['fight']=time.perf_counter()-t0
            negative=p.run('--tape',neg_tape,'--watch-dcs',hex(FIGHT),'--frames',FIGHT_FRAMES,timeout=1800)['summary']
            # 4. CMOS profile failures (fail closed, before the board runs).
            bad=p.temp/'bad-profile';bad.mkdir();(bad/'cmos.bin').write_bytes(bytes(16384))
            locked=p.temp/'locked-profile';locked.mkdir();(locked/'.cmos.lock').write_bytes(b'')
            failures={}
            for name,d in (('wrong_size',bad),('held_lock',locked)):
                f=q.command([p.exe,ROOT/'roms/mk3',reference.SEED,p.temp/'gfx.txt','--frames',1,'--cmos-profile',d],p.temp,cwd=ROOT,env=p.env,timeout=120)
                failures[name]=dict(failed=not f['passed'],message=f['stdout'].strip().splitlines()[-1][:160] if f['stdout'].strip() else '')
                self.assertFalse(f['passed'],name)
            self.assertEqual((bad/'cmos.bin').stat().st_size,16384,'never repaired')
            # 5. Windows: Original and Remastered layer 1, each from its own empty profile (both start from the seed).
            shown={};profiles={}
            for edition in ('original','remastered'):
                profiles[edition]=p.temp/f'profile-{edition}'
                env=dict(preview.EDITIONS[edition],MK1_FULLSCREEN='0',MK1_GRAPHICS_VALIDATE='1')
                shown[edition]=p.run('--window','--audio','--hashes','--edition',edition,'--frames',FRAMES,'--linger',1,'--cmos-profile',profiles[edition],
                                     timeout=300,window_env=env)
            saved={e:(d/'cmos.bin').read_bytes() for e,d in profiles.items()}
            reload=p.run('--frames',30,'--cmos-profile',profiles['original'])['summary']
            reloaded=(profiles['original']/'cmos.bin').read_bytes()
            leftovers=sorted(x.name for d in profiles.values() for x in d.iterdir() if x.name!='cmos.bin')
        self.assertFalse(p.cleanup['exists_after'])
        after=snapshot()
        # round start route.
        self.assertEqual((fight['frontier'],fight['tape']['applied'],fight['tape']['events']),('none',len(tape),len(tape)))
        self.assertEqual(fight['dcs']['watch_cycle'],FIGHT_CYCLE,fight['dcs'])
        self.assertEqual(negative['tape']['applied'],len(no_start))
        self.assertNotEqual(negative['dcs']['watch_cycle'],FIGHT_CYCLE,negative['dcs'])
        # CMOS.
        self.assertEqual(after,before,'MK1/MK2/MK3-core profiles, seeds or the default MK3 profile changed')
        for e,s in shown.items():
            self.assertTrue(s['summary']['cmos']['profile']);self.assertFalse(s['summary']['cmos']['from_profile'])
            self.assertEqual((s['summary']['cmos']['saved'],s['summary']['cmos']['refused']),(True,''))
            self.assertEqual(len(saved[e]),49152)
        self.assertTrue(reload['cmos']['from_profile']);self.assertEqual(len(reloaded),49152);self.assertEqual(leftovers,[])
        self.assertEqual((reload['cmos']['saved'],reload['cmos']['refused']),(False,'no D3D12 presentation (headless session)'))
        self.assertEqual(reloaded,saved['original'],'a headless session rewrote the profile')
        # Editions.
        hashes={e:[f['prev'] for f in s['frames']] for e,s in shown.items()}
        quiet=all(not s['summary']['inputs']['changes'] for s in shown.values())
        if quiet:
            self.assertEqual(hashes['original'],hashes['remastered'])
            self.assertEqual(hashes['original'],[f['prev'] for f in a['frames']])
            self.assertEqual(saved['original'],saved['remastered'])
        w={e:s['summary']['window'] for e,s in shown.items()}
        self.assertEqual((w['original']['scalefx_amount'],w['remastered']['scalefx_amount']),(0,100))
        for e,s in shown.items():
            x=s['summary'];self.assertEqual(x['frames'],FRAMES);self.assertEqual(x['edition'],e)
            self.assertTrue(x['audio']['device']);self.assertEqual(x['audio']['underruns'],0,x['audio']);self.assertEqual(x['audio']['submitted'],x['audio']['output_samples'])
            v=w[e];self.assertGreater(v['displayed_frames'],0);self.assertEqual((v['source_width'],v['source_height']),(400,254))
            self.assertEqual(v['last_present_hresult'],0);self.assertGreater(v['gpu_validation_frames'],0);self.assertEqual(v['gpu_validation_mismatches'],0)
        def perf(s):return {k:s[k] for k in ('frames','cycles','emulated_seconds','wall_seconds','fps','realtime_factor')}
        update_receipt('preview',dict(passed=True,label='MK3 nativo (perfil jogo); fidelidade só nas rotas comparadas',
            input_map=dict(keys=len(mapping['keys']),pad_controls=len(pads),driver_fields=len(ports),unmapped=['IN2 0x2000 Door Interlock (no MAME default)'],
                           layout='shared MK1/MK2 keyboard + Run C/N + MAME defaults T F2 9 7 8 - = Backspace; pads: shared layout, RB/RT Block, LB/LT Run'),
            smoke=dict(frames=FRAMES,last_frame=sa['last_frame'],cycles=sa['cycles'],audio=sa['audio'],deterministic=True,seconds=round(t['smoke'],1)),
            full_headless=dict(perf(full),frontier=full['frontier'],stop_pc=full['stop_pc'],first_execution=full['first_execution']),
            strict_negative=dict(frontier=strict['frontier'],cycles=strict['cycles']),
            fight_tape=dict(tape=[list(e) for e in tape],frames=fight['frames'],dcs_0x233d_cycle=fight['dcs']['watch_cycle'],original_cycle=FIGHT_CYCLE,
                            dcs_commands=fight['dcs']['commands'],frontier=fight['frontier'],seconds=round(t['fight'],1),perf=perf(fight),
                            first_execution=fight['first_execution']),
            fight_negative_without_start=dict(tape_events=len(no_start),dcs_0x233d_cycle=negative['dcs']['watch_cycle'] or None,
                                              dcs_commands=negative['dcs']['commands'],frontier=negative['frontier']),
            cmos=dict(image_bytes=49152,default_profile=str(preview.CMOS_PROFILE.relative_to(ROOT)).replace('\\','/'),
                      window_saved_sha256={e:hashlib.sha256(v).hexdigest() for e,v in saved.items()},
                      seed_sha256=q.sha(reference.SEED),reloaded_from_profile=reload['cmos']['from_profile'],failures=failures,
                      headless_writes=False,preserved_files=len(before),preserved_equal=after==before),
            editions={e:dict(perf(s['summary']),inputs=s['summary']['inputs'],audio=s['summary']['audio'],
                presentation={k:w[e][k] for k in ('displayed_frames','coalesced_host_frames','submitted_frames','viewport_width','viewport_height',
                    'source_width','source_height','bezel','scanlines','filter','scalefx_amount','last_present_hresult','max_present_ms',
                    'gpu_validation_frames','gpu_validation_mismatches','gpu_validation_max_error','gpu_validation_tolerance')})
                for e,s in shown.items()},
            canonical_hashes_equal=dict(checked=quiet,frames=FRAMES,editions=quiet and hashes['original']==hashes['remastered'],
                                        headless=quiet and hashes['original']==[f['prev'] for f in a['frames']]),
            build_seconds=r['build_seconds'],total_seconds=round(time.perf_counter()-started,1),cleanup=dict(exists_after=p.cleanup['exists_after'])))


if __name__=='__main__':unittest.main()
