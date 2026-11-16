"""J1 front C: MK3 route replay (tools/mk3/replay.py) on the closed stretch reset -> first unobserved branch.

Route: empty tape (reset -> attract, inputs at rest), executor of the working tree (replay.Native(): the whole-image units of tools/mk3/generate.py; formerly the
tree is being edited by other fronts). Expected at the route schedule (every replay.STEP cycles): every record equal up
to the native frontier, the frontier rejection at its PC and cycle, whole regions equal at END.
Finer sampling (records at the first boundary after each native DAC autobuffer timer, and a bisection around the
first one) checks the class found in J1: the ADSP state the TMS sees right after a dcs_reg_timer expiry or an IRQ1
pulse end. Both are scheduler timers in MAME and end the TMS timeslice; mk3::Board::Run now cuts the timeslice at
them (closed in J1 integration: every probe record equal, asserted).
Negative controls must be localized by the bisection, comparing every region:
- a main RAM bit flipped natively at cycle M: first difference at the first boundary >= M, region ram, at the byte;
- an IN1 pulse (P1 Low Punch) on the native tape only: the differing instruction is the first IN1 read at or after M;
- the same IN1 pulse on both tapes: equal again (the Original's tape path), the open class apart;
- one field of one Original record changed per compared region: reported at that record and region.
"""
from pathlib import Path
import copy,json,math,sys,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3 import replay,replay_state

ROOT=Path(__file__).resolve().parents[2]
RECEIPT=ROOT/'build/native/mk3-m2/j1-replay.json'
TRACE=ROOT/'build/native/mk3-m2/j1-trace.json'
FRONTIER='MK3 unobserved branch; PC 4287779776; address 4287779776'
END=(0xff9253c0,21184789)
MUTATION=(0x30000,1,20000000)              # main RAM word (bit address 0x01300000) ^= 1 at TMS 20,000,000
COIN=((20000000,1,0xfffe),(20300000,1,0xffff))   # IN1 bit 0 (P1 Low Punch in INPUT_PORTS(mk3); COIN1 is IN2 bit 0), active low, 300,000 cycles; the name is kept
IO_IN1=0x0187ff90                          # io offset 1 (IN1) as the game reads it
OPEN=()                                    # no region set aside (the ADSP-timer class is closed)
TMS_NS=160


def localized(result):
    b=result.get('bisection') or {}
    return b.get('first_difference'),b.get('instruction'),b.get('window'),len(b.get('rounds',()))


def dac_probe(native,original,nat):
    """Records at the first boundary at/after each native DAC timer expiry and 40 cycles later, compared in full."""
    end=nat['records'][-1]['cycle']
    starts=sorted({math.ceil(t/TMS_NS) for t in nat['summary']['dac_ns'] if math.ceil(t/TMS_NS)<end})
    points=sorted(set(starts+[c+40 for c in starts if c+40<end]))
    n=native.run(0,0,0,end,(),(),None,(),points);r=original.capture(1000,0,0,end,(),(),None,points)
    f=n['fields'];m=replay.masks(f)
    rows=[(a['spec'],replay_state.difference(a,b,f,m)) for a,b in zip(n['records'],r['records']) if a['spec']!='end']
    bad=[(spec,d) for spec,d in rows if d]
    regions={}
    for _,(region,_) in bad:regions[region]=regions.get(region,0)+1
    # the first expiry: bisection between a record a scanline earlier (equal) and one a scanline later
    t0=starts[0];lo=native.run(t0-400,1,t0-400,t0-400)['records'][0]
    first=replay.bisect(native,original,lo,t0+400,(),(),()) if bad and bad[0][0]<=t0+40 else None   # none once the class is closed
    return dict(timers=len(nat['summary']['dac_ns']),points=len(rows),differing=len(bad),by_region=regions,first_differing=bad[:3],
                equal=[spec for spec,d in rows if not d][:8],original_seconds=r['wall_seconds'],first_timer_cycle=nat['summary']['dac_ns'][0]/TMS_NS,
                first_timer_bisection=first)


class Replay(unittest.TestCase):
    def test_route_and_negative_controls(self):
        original=replay.Original()
        with replay.Native() as native:
            base,nat,ref=replay.route(native,original)
            self.assertIsNone(base['first_record_difference'],base['first_record_difference'])
            self.assertEqual(base['summary']['frontier'],FRONTIER)
            self.assertEqual(base['summary']['dcs_frontier'],'')
            self.assertEqual((base['end']['pc'],base['end']['cycle']),END)
            self.assertTrue(base['end_integral'] and all(v is None for v in base['end_integral'].values()),base['end_integral'])
            t=time.perf_counter();probe=dac_probe(native,original,nat);probe['seconds']=time.perf_counter()-t
            fb=probe['first_timer_bisection'] or dict(first_difference=None,instruction=None,rounds=[])
            fd=fb['first_difference']
            self.assertIsNone(fd,fd);self.assertEqual(probe['differing'],0,probe['first_differing'])
            negatives={}
            # 1. State mutation: located at the first boundary >= M, in main RAM, at the mutated byte.
            word,mask,m=MUTATION
            expect=native.run(m,1,m,m)['records'][0]
            r1,_,_=replay.route(native,original,(),[MUTATION],ignore=OPEN)
            d,instruction,window,rounds=localized(r1)
            negatives['ram_bit']=dict(detected=r1['first_record_difference'] is not None,rounds=rounds,first_difference=d,instruction=instruction,
                                      expected_boundary=expect['cycle'],window_region=window and window.get('region_bytes'),
                                      seconds=r1['timings'].get('bisection'))
            self.assertEqual((d['region'],d['boundary_cycle']),('ram',expect['cycle']),d)
            self.assertEqual(window['region_bytes']['offset'],2*word)
            # 2. Tape mutation on the native side: the differing instruction is the first IN1 read at or after M.
            start=COIN[0][0]
            reads=native.run(0,0,0,start+400000,COIN,(),(start,start+400000))['window']['reads']
            first_read=next(r for r in reads if r[1]==IO_IN1)
            r2,_,_=replay.route(native,original,COIN,(),None,(),ignore=OPEN)
            d,instruction,window,rounds=localized(r2)
            negatives['tape_native_only']=dict(detected=r2['first_record_difference'] is not None,rounds=rounds,first_difference=d,instruction=instruction,
                                               expected_read=first_read,window_reads=window and window['native_reads'],seconds=r2['timings'].get('bisection'))
            self.assertEqual((instruction['cycle'],instruction['pc']),(first_read[3],first_read[0]),(instruction,first_read))
            self.assertEqual(d['region'],'cpu')
            # 3. The same tape on both sides: equal up to the native end (the Original's tape path).
            r3,nat3,ref3=replay.route(native,original,COIN,ignore=OPEN)
            self.assertIsNone(r3['first_record_difference'],r3['first_record_difference'])
            open_class=replay.compare_records(nat3,ref3)   # with nothing set aside: only the open class may remain
            self.assertTrue(open_class is None or open_class[1] in OPEN,open_class)
            self.assertTrue(all(v is None for v in r3['end_integral'].values()))
            self.assertEqual(nat3['summary']['tape_applied'],sum(c<=r3['end']['cycle'] for c,_,_ in COIN))   # the IN1-pulse route may end earlier
            same_tape=dict(tape=[list(e) for e in COIN],records=r3['records'],end=r3['end'],frontier=r3['summary']['frontier'],end_integral_equal=True,
                           set_aside=list(OPEN),open_class_difference=open_class,timings=r3['timings'])
            # 4. One field per region in one Original record: reported at that record and region.
            fields=nat['fields'];masks=replay.masks(fields)
            pick=next(k for k,r in enumerate(ref['records']) if r['pcm']['since_reset']['segment']>r['pcm']['segment']>0)
            adsp=next(f for f,m in zip(fields,masks) if m and f!='totalcycles')
            changes={'cpu':lambda r:r['registers'].__setitem__(3,r['registers'][3]^1),'dma':lambda r:r['dma'].__setitem__(4,r['dma'][4]^1),
                     'io':lambda r:r['io'].__setitem__(5,r['io'][5]^1),'control':lambda r:r.__setitem__('control',r['control']^1),
                     'adsp':lambda r:r['adsp'].__setitem__(adsp,r['adsp'][adsp]^1),'pcm':lambda r:r['pcm'].__setitem__('hash','0')}
            for name in replay_state.REGIONS:changes[name]=lambda r,name=name:r['hash'].__setitem__(name,'0')
            fields_detected={}
            for k,(name,change) in enumerate(changes.items()):
                at=(pick+7*k)%(len(ref['records'])-1) if name!='pcm' else pick
                changed=dict(ref,records=copy.deepcopy(ref['records']));change(changed['records'][at])
                got=replay_state.first_difference(nat,changed,fields,masks)
                fields_detected[name]=got is not None and got[:2]==(at,name)
            negatives['record_fields']=fields_detected
            self.assertTrue(all(fields_detected.values()),fields_detected)
            native_runs=len(native.runs);build=native.build_seconds;source=native.source_identity
        self.assertFalse(native.cleanup['exists_after'])
        # tools/mk3/trace_stream.py results (noloop 30 s: PCs and pairs; folded: PCs over a longer attract)
        trace={p.stem:json.loads(p.read_text('utf-8')) for p in (TRACE,TRACE.with_name('j1-trace-folded.json')) if p.is_file()} or None
        RECEIPT.parent.mkdir(parents=True,exist_ok=True)
        RECEIPT.write_text(json.dumps(dict(passed=True,
            route=dict(name='reset -> attract (empty tape, inputs at rest), CMOS seed, default DIPs',tape=[],
                       executor=dict(source,note='native/mk3 of this commit (other fronts edit the working tree)'),
                       horizon='native frontier',end=dict(pc=hex(base['end']['pc']),cycle=base['end']['cycle'],instructions=base['end']['instructions'],
                       frontier=base['summary']['frontier'])),
            checkpoints=dict(rule='first TMS instruction boundary at a cycle >= C with ST.P clear: native mk3::Board::stop before each instruction '
                                  '(Board::Cycles()); Original: one debugger registerpoint totalcycles>=temp9&&(st&0x2000000)==0 at the instruction hook, '
                                  'schedule kept in Lua (MAME runs only the first matching registerpoint per hook); several C due at one boundary give one record',
                             schedule=dict(step_cycles=replay.STEP,first=replay.STEP),compared=base['records'],end_included=True),
            compared=dict(per_record='PC, ST, totalcycles, A0-A14, SP, B0-B14; main RAM, CMOS, palette, video RAM, ADSP DM (0-0x2fff, 0x3800-0x39ff) and '
                                     'PM (0-0x3ff, 0x800-0x1fff) as FNV-1a 64 of every word; 18 DMA registers, 32 TMS I/O registers, midwunit control latch '
                                     'in full; ADSP debugger symbols (tools/mk3/test_adsp.py masks, totalcycles excepted); DAC samples since the previous record',
                          hashed_bytes_per_region=base['compared_bytes'],integral_at_end_bytes={n:replay_state.REGION_BYTES[n] for n in replay_state.REGIONS},
                          integral_at_end='byte by byte, all equal',pcm=dict(samples_to_end=nat['records'][-1]['pcm']['count'],
                          nonzero=nat['records'][-1]['pcm']['nonzero'],note='every stored DAC sample of the route is zero')),
            first_difference=dict(route_schedule=None,
                finer_sampling=dict(fd or {},instruction=fb['instruction'],
                    cause='closed: dcs_reg_timer (DAC autobuffer, first expiry at ADSP 96,277,400 ns = TMS 601,733.75) and the IRQ1 pulse '
                          'end are scheduler timers in MAME that end the TMS timeslice; before the J1 integration mk3::Board did not cut '
                          'there (844 of 848 probe records differed, transiently). mk3::Board::Run now ends the timeslice at Dcs8k::NextTimerNs.',
                    dac_timer_probe={k:v for k,v in probe.items() if k!='first_timer_bisection'},bisection_rounds=fb['rounds'])),
            negatives=negatives,negatives_set_aside=list(OPEN),same_tape_both_sides=same_tape,
            timings_seconds=dict(native_build=build,native_route=base['timings']['native'],original_route_capture=base['timings']['original'],
                                 comparison=base['timings']['compare'],route_total=base['timings']['total'],dac_probe=probe['seconds'],
                                 bisection_ram_bit=negatives['ram_bit']['seconds'],bisection_tape=negatives['tape_native_only']['seconds'],
                                 original_captures=len(original.runs),original_capture_seconds_total=sum(original.runs),native_runs=native_runs),
            identities=base['identities'],
            transport=dict(original_stdout_bytes=base['original_io']['stdout_bytes'],original_debug_log_bytes=base['original_io']['log_bytes'],
                           native_stdout_bytes=base['native_stdout_bytes'],disk='debugger log in a scratch tree removed after each capture; pipes otherwise'),
            gaps=['Differences that appear and vanish between two records are not seen at route level (the DAC-timer class above is one).',
                  'ADSP control registers 0x3fe0-0x3fff and the latches are not read by the Lua observer (side effects); the debugger symbols cover the core.',
                  'DAC samples stored before a dmadac enable(0) inside a record interval are not observable at the next record.',
                  'Hashes establish per-region equality up to collision between records; whole regions are compared at END and at the bisected boundary.'],
            trace_stream=trace,
            cleanup=dict(original_route=base['original_io']['cleanup'],native=native.cleanup)),indent=1)+'\n',encoding='utf-8')


if __name__=='__main__':unittest.main()
