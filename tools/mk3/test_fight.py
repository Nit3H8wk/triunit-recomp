"""J3 route front: reset -> round start with a legal input tape in Profile::Game, compared with the Original at checkpoints.

Tape (tools/mk3/replay.py format, ports 0 IN0, 1 IN1, 2 DSW, 3 IN2, active low; bits from INPUT_PORTS(mk3), midwunit.cpp):
two COIN1 pulses (the CMOS coinage of the seed takes 2 coins per credit), START1, then P1 High Punch on the select screen.
round start (ROM evidence): the speech call (sound 10h) at 0xff80ec30-0xff80ec50 writes DCS command 0x233D
(after 0x2341 "Round" from 0xff80ed80); the route ends at the first TMS boundary after the low byte 0x3D reaches the sound
port. Acceptance of each input is measured on the Original (first read of the pressed value, CMOS credits 0x1401aa0).
Negative controls: the select press only on the Original's tape (the differing instruction is the first IN0 read at or
after it); a main RAM bit flipped natively.
"""
from pathlib import Path
import json,math,sys,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import reference,replay,replay_reference as rr,replay_state,roms

ROOT=Path(__file__).resolve().parents[2]
RECEIPT=ROOT/'build/native/mk3-m2/j3-fight.json'
TMS_HZ=6250000
TAPE=tuple(replay.read_tape(ROOT/'tools/mk3/fight_route.tape'))   # coin, coin, Start P1, P1 High Punch (select)
FIGHT=0x233d
GAME_OVER=0x0021
HIGH,LOW=0xffaa88b0,0xffaa8920
MUTATION=(0x30000,1,160000000)
NL=chr(92)+'n'
CLASSES=[dict(cls='candidate',where='0xffa7b180 (round start route) and 0xffa7f2f0.. / 0xffaacbe0.. (round 2 end, continue): PC outside the candidate',
              fix='38 Original route-trace roots in tools/mk3/fight_trace_roots.json (traces j3-trace-folded 47 s, j3-match-trace-folded 103 s)'),
         dict(cls='unmapped read',where='MOVE *A4(80h),A4,1 at 0xff95daa0 reading 0x781e6380 @187,606,747',
              fix="no handler in midwunit main_map: MAME's unmap value 0 (Ops::Read16)")]


def observe(tape,end):
    """Original with the tape: DCS commands, CMOS credit writes and pressed IN0/IN2 reads (read-only watchpoints)."""
    if q.sha(reference.CORE)!=reference.CORE_SHA:raise ValueError('Reference core identity changed')
    identity=roms.verify(ROOT/'roms/mk3')
    script=rr.script(min([end]+[c for c,_,_ in tape])).rstrip('\n').split('\n')
    extra=[f'wpset 1680000,10,w,1,{{printf "MK3_S %X %X %d{NL}",pc,wpdata,totalcycles;g}}',
           f'wpset 1401aa0,10,w,1,{{printf "MK3_C %X %X %X %d{NL}",pc,wpaddr,wpdata,totalcycles;g}}',
           f'wpset 1800000,80000,r,((wpaddr>>4)&7)==0||((wpaddr>>4)&7)==3,{{printf "MK3_I %X %X %X %d{NL}",pc,wpaddr,wpdata,totalcycles;g}}']
    with q.scratch_tree() as (temp,cleanup):
        (temp/'nvram/mk3').mkdir(parents=True);(temp/'nvram/mk3/nvram').write_bytes(reference.SEED.read_bytes())
        (temp/'f.cmd').write_text('\n'.join(script[:-1]+extra+['go'])+'\n',encoding='ascii')
        (temp/'f.lua').write_text(rr.lua(0,0,0,end,tape),encoding='ascii')
        run=q.command([reference.CORE,'mk3','-rompath',ROOT/'roms','-noreadconfig','-nowriteconfig','-skip_gameinfo','-noplugins',
                       '-video','none','-sound','none','-nothrottle','-debug','-debugger','windows','-debuglog','-debugscript','f.cmd',
                       '-autoboot_delay','0','-autoboot_script','f.lua','-keyboardprovider','none','-mouseprovider','none',
                       '-joystickprovider','none','-lightgunprovider','none','-nvram_directory','nvram','-cfg_directory','cfg',
                       '-homepath','home','-snapshot_directory','snap','-seconds_to_run',str(math.ceil(end/TMS_HZ)+3)],
                      temp,cwd=temp,timeout=3000,output_limit=64<<20)
        if not run['passed'] or 'MK3_EXIT' not in run['stdout']:raise RuntimeError('Reference run failed: '+run.get('stdout','')[-1000:])
        text=(temp/'debug.log').read_text('utf-8')
    if cleanup['exists_after']:raise ValueError('Reference scratch retained')
    rows=lambda tag:[[int(x,16) if i<len(l)-1 else int(x) for i,x in enumerate(l)] for l in (s.split()[1:] for s in text.splitlines() if s.startswith(tag+' '))]
    snd=rows('MK3_S');cmds=[]
    for k in range(0,len(snd)-1,2):
        if snd[k][0]!=HIGH or snd[k+1][0]!=LOW:raise ValueError(f'unpaired sound-port write {snd[k]}')
        cmds.append(((snd[k][1]<<8)|snd[k+1][1],snd[k+1][2]))
    reads=[r for r in rows('MK3_I') if r[2]!=0xffff]
    accepted=[]
    for (c,p,v),nxt in zip(TAPE,TAPE[1:]+((1<<62,0,0),)):
        if v==0xffff:continue
        hit=next((r for r in reads if c<=r[3]<nxt[0] and (r[1]>>4)&7==p and r[2]==v),None)
        accepted.append(dict(tape=[c,p,v],first_read=hit and dict(pc=hex(hit[0]),cycle=hit[3])))
    return dict(commands=cmds,credits=[dict(pc=hex(p),value=v,cycle=c) for p,_,v,c in rows('MK3_C')],accepted=accepted,
                wall_seconds=run['wall_seconds'],program_sha256=identity['program_sha256'],cleanup=cleanup)


class Fight(unittest.TestCase):
    def test_fight_route_game_profile(self):
        t0=time.perf_counter();seen=observe(TAPE,60*TMS_HZ);t_obs=time.perf_counter()-t0
        fight=next(c for v,c in seen['commands'] if v==FIGHT)
        self.assertTrue(all(a['first_read'] for a in seen['accepted']),seen['accepted'])
        end=fight+1
        original=replay.Original()
        with replay.Native(profile='game') as native:
            base,nat,ref=replay.route(native,original,TAPE,horizon=end)
            self.assertIsNone(base['first_record_difference'],base['first_record_difference'])
            self.assertTrue(base['end_integral'] and all(v is None for v in base['end_integral'].values()),base['end_integral'])
            self.assertEqual(base['summary']['frontier'],'none')
            self.assertEqual(nat['summary']['tape_applied'],len(TAPE))
            negatives={}
            # 1. The select press on the Original's tape only: the differing instruction is the first IN0 read at/after it.
            native_tape=TAPE[:6];at=TAPE[6][0]
            reads=native.run(0,0,0,at+700000,TAPE,(),(at,at+700000))['window']['reads']
            select=next(r for r in reads if 0x01800000<=r[1]<=0x0187fff0 and ((r[1]-0x01800000)>>4)%16%8==0)   # first IN0 read at/after it
            r1,_,_=replay.route(native,original,native_tape,horizon=end,reference_tape=TAPE)
            b=r1.get('bisection') or {};i=b.get('instruction') or {}
            negatives['select_reference_only']=dict(detected=r1['first_record_difference'] is not None,instruction=i,expected_read=select,
                                                    original_first_read=next(a for a in seen['accepted'] if a['tape'][1]==0)['first_read'],
                                                    rounds=len(b.get('rounds',())),seconds=r1['timings'].get('bisection'))
            self.assertEqual((i.get('cycle'),i.get('pc')),(select[3],select[0]),(i,select))
            # 2. Native RAM bit: localized at the first boundary >= M, in main RAM, at the byte.
            word,mask,m=MUTATION
            expect=native.run(m,1,m,m,TAPE)['records'][0]
            r2,_,_=replay.route(native,original,TAPE,[MUTATION],horizon=end)
            b=r2.get('bisection') or {};d=b.get('first_difference') or {}
            negatives['ram_bit']=dict(detected=r2['first_record_difference'] is not None,boundary=d.get('boundary_cycle'),expected_boundary=expect['cycle'],
                                      region=d.get('region'),byte=(b.get('window') or {}).get('region_bytes'),seconds=r2['timings'].get('bisection'))
            self.assertEqual((d.get('region'),d.get('boundary_cycle')),('ram',expect['cycle']),d)
            build=native.build_seconds;runs=len(native.runs);source=native.source_identity
        self.assertFalse(native.cleanup['exists_after'])
        first=nat['summary']['first_executions']
        RECEIPT.parent.mkdir(parents=True,exist_ok=True)
        kept={k:v for k,v in (json.loads(RECEIPT.read_text('utf-8')) if RECEIPT.is_file() else {}).items() if k=='match'}
        RECEIPT.write_text(json.dumps(dict(passed=True,**kept,
            route=dict(profile='game',tape=[list(e) for e in TAPE],executor=source,end=dict(cycle=base['end']['cycle'],pc=hex(base['end']['pc']),
                       seconds=base['end']['cycle']/TMS_HZ,frontier=base['summary']['frontier'])),
            fight=dict(criterion='DCS command 0x233D from the speech call at 0xff80ec30-0xff80ec50 (sound 10h), after 0x2341 '
                                 'Round from 0xff80ed80',cycle=fight,seconds=fight/TMS_HZ,commands=[[f'{v:04x}',c] for v,c in seen['commands'] if c<=end]),
            acceptance=dict(inputs=seen['accepted'],credits=seen['credits']),
            checkpoints=dict(step_cycles=replay.STEP,compared=base['records'],hashed_bytes_per_region=base['compared_bytes'],
                             integral_at_end_bytes={n:replay_state.REGION_BYTES[n] for n in replay_state.REGIONS}),
            first_difference=None,classes_fixed=CLASSES,first_executions={k:dict(count=v['count'],first=[[hex(a),hex(f),c] for a,f,c in v['first'][:8]]) for k,v in first.items()},
            negatives=negatives,
            timings_seconds=dict(original_observation=t_obs,native_build=build,native_route=base['timings']['native'],original_route=base['timings']['original'],
                                 comparison=base['timings']['compare'],route_total=base['timings']['total'],original_captures=len(original.runs),
                                 original_capture_seconds_total=sum(original.runs),native_runs=runs),
            identities=base['identities'],
            cleanup=dict(observation=seen['cleanup'],original_route=base['original_io']['cleanup'],native=native.cleanup)),indent=1)+'\n',encoding='utf-8')


    def test_match_route_game_profile(self):
        """Reserve: the same tape, P1 idle after the select press, to the end of the match. The CPU wins both rounds (voices
        0x2341 Round 1 and 0x2346 Round 2, each followed by 0x233D), the continue screen plays 0x0038 (0xff956450) and the game
        ends with the sound call at 0xff8109e0 (DCS 0x0021), next to the CMOS credit/state reset 0x1401ab0-0x1401b10."""
        t0=time.perf_counter();seen=observe(TAPE,105*TMS_HZ);t_obs=time.perf_counter()-t0
        fight=next(c for v,c in seen['commands'] if v==FIGHT)
        over=next(c for v,c in seen['commands'] if v==GAME_OVER and c>fight)
        marks={f'{v:04x}':[c for w,c in seen['commands'] if w==v and c<=over] for v in (0x2341,0x2346,FIGHT,0x0038,GAME_OVER)}
        self.assertEqual((len(marks['2341']),len(marks['2346']),len(marks['233d'])),(1,1,2),marks)
        original=replay.Original()
        with replay.Native(profile='game') as native:
            base,nat,ref=replay.route(native,original,TAPE,horizon=over+1)
            self.assertIsNone(base['first_record_difference'],base['first_record_difference'])
            self.assertTrue(base['end_integral'] and all(v is None for v in base['end_integral'].values()),base['end_integral'])
            self.assertEqual(base['summary']['frontier'],'none')
            source=native.source_identity
        self.assertFalse(native.cleanup['exists_after'])
        first=nat['summary']['first_executions']
        data=json.loads(RECEIPT.read_text('utf-8')) if RECEIPT.is_file() else {}
        data['match']=dict(passed=True,criterion='DCS 0x0021 from the sound call at 0xff8109e0 after the continue countdown (0x0038)',
            game_over_cycle=over,game_over_seconds=over/TMS_HZ,marks=marks,executor=source,
            end=dict(cycle=base['end']['cycle'],pc=hex(base['end']['pc']),frontier=base['summary']['frontier']),
            checkpoints=dict(step_cycles=replay.STEP,compared=base['records'],hashed_bytes_per_region=base['compared_bytes']),first_difference=None,
            first_executions={k:v['count'] for k,v in first.items()},
            timings_seconds=dict(original_observation=t_obs,native_route=base['timings']['native'],original_route=base['timings']['original'],
                                 comparison=base['timings']['compare'],route_total=base['timings']['total']),
            cleanup=dict(observation=seen['cleanup'],original_route=base['original_io']['cleanup'],native=native.cleanup))
        RECEIPT.write_text(json.dumps(data,indent=1)+'\n',encoding='utf-8')


if __name__=='__main__':unittest.main()
