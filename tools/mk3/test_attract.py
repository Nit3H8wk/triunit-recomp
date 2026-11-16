"""J2 route front: reset -> one complete attract cycle in Profile::Game, compared with the Original at checkpoints.

Attract cycle (criterion measured on the Original, read-only debugger watchpoint on the sound port 0x01680000): the game
writes each DCS command as two bytes (high at 0xffaa88b0, low at 0xffaa8920). Every demo-fight round of the attract
starts with the command 0x0451 (then 0x0000, 0x0035). One complete cycle runs from the first 0x0451 to the next one;
the route is reset -> that second 0x0451 (empty tape: inputs at rest, CMOS seed, default DIPs).
Route: tools/mk3/replay.py with replay.Native(profile='game') against the Original's records every replay.STEP cycles,
up to the native end (the first rejection, or the cycle end). Expected: every record equal (CPU, RAM/CMOS/palette/VRAM/
ADSP DM/PM hashes, DMA/IO/control, ADSP symbols, DAC samples), whole regions equal at END, the native end recorded.
Negative controls (each localized by the bisection, or reported at the changed record):
- a main RAM bit flipped natively late in the route: first difference at the first boundary >= M, region ram, at the byte;
- one audible DAC sample changed in the Original's decoded ring (record field): reported at that record as pcm.
"""
from pathlib import Path
import copy,json,sys,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import reference,replay,replay_state,roms

ROOT=Path(__file__).resolve().parents[2]
RECEIPT=ROOT/'build/native/mk3-m2/j2-attract.json'
TMS_HZ=6250000
ROUND=0x0451                       # first command of every demo-fight round
HIGH,LOW=0xffaa88b0,0xffaa8920     # sound-port byte writers (high, low)
MUTATION=(0x30000,1,80000000)      # main RAM word (bit address 0x01300000) ^= 1 at TMS 80,000,000
NL=chr(92)+'n'
# Divergence/rejection classes found on this route by the Profile::Game replay and bisection, fixed from the pinned sources.
CLASSES=[
 dict(cls='candidate',where='RETS 0xff9634f0 @64,466,416 (J1 probe; the Original never runs it)',fix='J1 trace roots + GETPC/ADDI software-stack '
      'continuations in tools/mk3/generate.py closure (1,217 static return targets; 240 s Original trace: 9,605 PCs, 8 left outside, kept as roots)'),
 dict(cls='shift-register PIXT/FILL XY',where='PIXT *B2,B2 0xff81b4d0 / FILL XY 0xff81b580 @68,204,719',
      fix='tms34010.cpp read/write_pixel_shiftreg, 34010gfx.hxx fill (shiftreg_w per word, m_gfxcycles 8+rows*words*4, restart over the '
          'timeslice end), midtunit_v.cpp to/from_shiftreg; Board::RunTms hands the timeslice end to Ops (slice_end)'),
 dict(cls='observer (Original side)',where='first audible DAC block @69,211,279 (native -2/-3, ring 0x100/0x180)',
      fix='MAME 0.280 dmadac m_buffer holds 4-byte floats (int16 * 1/32767): replay_reference decodes them; no native change'),
 dict(cls='unmapped write',where='MOVE A14,@1D01010h 0xff929380 @83,869,211',fix='midwunit main_map has no handler there: write dropped (Ops::Unmapped)'),
 dict(cls='graphics ROM window',where='read 0x05eb7fa0 at 0xff929560 @83,869,834',fix='midwunit_gfxrom_r: bank 0x800000*control bits 8-9'),
 dict(cls='sound data ROMs',where='ADSP data bank outside U2 (boot 5, PC 0x850)',fix='replay runner attaches U3-U5 (Dcs8k::AttachSoundData), as the Original loads them'),
 dict(cls='scheduler time overflow',where='Board stalls at 18.4467 s (TMS @115,291,278)',fix='Board::As 128-bit (64-bit attoseconds wrap at 2^64 as = 18.446744 s)'),
 dict(cls='sync instruction form',where='MOVE A14,*A3,0 to DMA_COMMAND 0xff801b10 @830,836,436',fix='MOVE_RN (WFIELD0 then COUNT_CYCLES(1)) qualified for synchronize() at the instruction start'),
]


def sound_commands(seconds):
    """Original from reset: every sound-port write (pc, byte, totalcycles) paired into 16-bit commands [(command, cycle)]."""
    if q.sha(reference.CORE)!=reference.CORE_SHA:raise ValueError('Reference core identity changed')
    identity=roms.verify(ROOT/'roms/mk3')
    cmd='\n'.join(['focus :maincpu',f'wpset 1680000,10,w,1,{{printf "MK3_S %X %X %d{NL}",pc,wpdata,totalcycles;g}}','go'])+'\n'
    with q.scratch_tree() as (temp,cleanup):
        (temp/'nvram/mk3').mkdir(parents=True);(temp/'nvram/mk3/nvram').write_bytes(reference.SEED.read_bytes())
        (temp/'attract.cmd').write_text(cmd,encoding='ascii')
        run=q.command([reference.CORE,'mk3','-rompath',ROOT/'roms','-noreadconfig','-nowriteconfig','-skip_gameinfo','-noplugins',
                       '-video','none','-sound','none','-nothrottle','-debug','-debugger','windows','-debuglog','-debugscript','attract.cmd',
                       '-keyboardprovider','none','-mouseprovider','none','-joystickprovider','none','-lightgunprovider','none',
                       '-nvram_directory','nvram','-cfg_directory','cfg','-homepath','home','-snapshot_directory','snap',
                       '-seconds_to_run',str(int(seconds))],temp,cwd=temp,timeout=3600)
        if not run['passed']:raise RuntimeError('Reference run failed: '+run.get('stdout','')[-1000:])
        text=(temp/'debug.log').read_text('utf-8')
    if cleanup['exists_after']:raise ValueError('Reference scratch retained')
    rows=[(int(p,16),int(v,16),int(c)) for p,v,c in (l.split()[1:] for l in text.splitlines() if l.startswith('MK3_S '))]
    out,k=[],0
    while k<len(rows):
        if k+1<len(rows) and rows[k][0]==HIGH and rows[k+1][0]==LOW:out.append(((rows[k][1]<<8)|rows[k+1][1],rows[k+1][2]));k+=2
        else:raise ValueError(f'unpaired sound-port write {rows[k]}')
    return dict(commands=out,wall_seconds=run['wall_seconds'],program_sha256=identity['program_sha256'],cleanup=cleanup)


def attract_cycle(commands):
    """(start, end) cycles of the first complete attract cycle: the first two 0x0451 commands, and the periods seen."""
    rounds=[c for v,c in commands if v==ROUND]
    if len(rounds)<3:raise ValueError('fewer than three attract rounds observed')
    return rounds[0],rounds[1],[b-a for a,b in zip(rounds,rounds[1:])]


class Attract(unittest.TestCase):
    def test_attract_route_game_profile(self):
        t0=time.perf_counter()
        sound=sound_commands(400);t_sound=time.perf_counter()-t0
        start,end,periods=attract_cycle(sound['commands'])
        original=replay.Original()
        with replay.Native(profile='game') as native:
            base,nat,ref=replay.route(native,original,horizon=end)
            self.assertIsNone(base['first_record_difference'],base['first_record_difference'])
            self.assertTrue(base['end_integral'] and all(v is None for v in base['end_integral'].values()),base['end_integral'])
            audible=[k for k,r in enumerate(nat['records']) if r['spec']!='end' and any(bytes.fromhex(r['samples']))]
            first=nat['summary']['first_executions']
            negatives={}
            # 1. Native RAM bit late in the route: localized at the first boundary >= M, in main RAM, at the byte.
            word,mask,m=MUTATION
            if m<base['end']['cycle']:
                expect=native.run(m,1,m,m)['records'][0]
                r1,_,_=replay.route(native,original,(),[MUTATION],horizon=end)
                b=r1.get('bisection') or {};d=b.get('first_difference') or {}
                negatives['ram_bit']=dict(detected=r1['first_record_difference'] is not None,boundary=d.get('boundary_cycle'),region=d.get('region'),
                                          expected_boundary=expect['cycle'],byte=(b.get('window') or {}).get('region_bytes'),
                                          rounds=len(b.get('rounds',())),seconds=r1['timings'].get('bisection'))
                self.assertEqual((d.get('region'),d.get('boundary_cycle')),('ram',expect['cycle']),d)
                self.assertEqual(negatives['ram_bit']['byte']['offset'],2*word)
            # 2. One audible sample of the Original's decoded ring: reported at that record, region pcm.
            fields=nat['fields'];masks=replay.masks(fields)
            if audible:
                at=audible[0];changed=dict(ref,records=copy.deepcopy(ref['records']));changed['records'][at]['pcm']['hash']='0'
                got=replay_state.first_difference(nat,changed,fields,masks)
                negatives['pcm_sample']=dict(record=at,detected=got is not None and got[:2]==(at,'pcm'))
                self.assertTrue(negatives['pcm_sample']['detected'],got)
            build=native.build_seconds;runs=len(native.runs);source=native.source_identity
        self.assertFalse(native.cleanup['exists_after'])
        kinds={k:dict(count=v['count'],first=[[hex(i),hex(f),c] for i,f,c in v['first'][:8]]) for k,v in first.items()}
        RECEIPT.parent.mkdir(parents=True,exist_ok=True)
        RECEIPT.write_text(json.dumps(dict(passed=True,
            attract=dict(criterion='DCS command 0x0451 (first command of every demo-fight round: 0x0451, 0x0000, 0x0035) written to the '
                                   'sound port; one complete attract cycle = first 0x0451 -> next 0x0451; route = reset -> that second 0x0451',
                         first_round_cycle=start,cycle_end=end,cycle_seconds=(end-start)/TMS_HZ,route_seconds=end/TMS_HZ,
                         round_periods_seconds=[round(p/TMS_HZ,3) for p in periods],observed_seconds=400,commands=len(sound['commands']),
                         original_seconds=sound['wall_seconds']),
            route=dict(profile='game',tape=[],executor=source,horizon=end,end=dict(pc=hex(base['end']['pc']),cycle=base['end']['cycle'],
                       seconds=base['end']['cycle']/TMS_HZ,instructions=base['end']['instructions'],frontier=base['summary']['frontier'],
                       dcs_frontier=base['summary']['dcs_frontier']),reached_cycle_end=base['end']['cycle']>=end),
            checkpoints=dict(step_cycles=replay.STEP,compared=base['records'],audible_records=len(audible),end_included=True,
                             hashed_bytes_per_region=base['compared_bytes'],integral_at_end_bytes={n:replay_state.REGION_BYTES[n] for n in replay_state.REGIONS},
                             pcm=dict(samples_to_end=nat['records'][-1]['pcm']['count'],nonzero=nat['records'][-1]['pcm']['nonzero'])),
            first_difference=None,classes_fixed=CLASSES,first_executions=kinds,negatives=negatives,
            timings_seconds=dict(original_attract_probe=t_sound,native_build=build,native_route=base['timings']['native'],
                                 original_route=base['timings']['original'],comparison=base['timings']['compare'],route_total=base['timings']['total'],
                                 bisection_ram_bit=negatives.get('ram_bit',{}).get('seconds'),original_captures=len(original.runs),
                                 original_capture_seconds_total=sum(original.runs),native_runs=runs),
            identities=base['identities'],
            cleanup=dict(attract_probe=sound['cleanup'],original_route=base['original_io']['cleanup'],native=native.cleanup)),indent=1)+'\n',encoding='utf-8')


if __name__=='__main__':unittest.main()
