"""K2 front A: the inline-parameter call FF97EF90 (tools/mk3/generate.py INLINE_CALLS; class "inline-parameter call
FF97EF90" of build/native/mk3-m2/k2-stops.json).

Closure: every caller found by scanning the decoded image, each continuation = return address + 0x30 bits, and the 8
FF992160 longs from the ROM. Native (Profile::Game, from reset): the two R1 exploration reproducers (versus.random_versus
seeds 200045 and 200046, 90 s) stop at 0xff97cf10 / 0xff97cab0 without the rule (negative control) and run past those
cycles with it. Exploration only: "explored natively, not yet compared"; the new PCs stay candidate, not verified.
"""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3 import generate,roms,replay,versus
from tools.mk3.explore import tape_sha,TMS_HZ

ROOT=Path(__file__).resolve().parents[2]
STOPS={200045:(0xff97cf10,341837814,'7223e7ed5436537eb35cc3c86e8b8c2a1cf797637176305ae201892a537461be'),
       200046:(0xff97cab0,427064618,'5cefb1e14b17009591f0798d44925eaaf5e7d81f2ff64c2a3425a7ad9d40f16a')}
MARGIN=2_000_000   # TMS cycles past the stop (0.32 s)


def frontiers(rule):
    # Negative: without the rule the route set (which holds blocks only the continuation reaches) does not apply; the
    # game profile ignores it, so the build uses no route file.
    saved=generate.INLINE_CALLS,generate.ROUTES
    if not rule:generate.INLINE_CALLS={};generate.ROUTES=ROOT/'tools/mk3/route_verified.absent.json'
    try:
        with replay.Native(profile='game') as native:
            out={}
            for seed,(pc,cycle,sha) in STOPS.items():
                item=versus.random_versus(seed,int(90*TMS_HZ))
                assert tape_sha(item['tape'])==sha,seed
                s=native.run(0,0,0,cycle+MARGIN,item['tape'])
                out[seed]=(s['summary']['frontier'],s['records'][-1]['cycle'])
            return out
    finally:generate.INLINE_CALLS,generate.ROUTES=saved


class InlineCalls(unittest.TestCase):
    def test_closure_continuations_from_the_image(self):
        rom=roms.program_image(ROOT/'roms/mk3',roms.definition());rows,_=generate.scan(rom)
        sites=sorted(pc for pc,r in rows.items() if r[0] and r[3].startswith(('CALLR','CALLA')) and r[3].endswith('FF97EF90h'))
        self.assertEqual([f'{pc:08x}' for pc in sites],['ff97aa80','ff97ca60','ff97cec0','ff97e610','ff97ef20'])
        graph={pc:() for pc in [0xff97ef90,*sites]}
        got=generate.inline_calls(rom,rows,graph)
        want={pc+32+0x30 for pc in sites}|{0xff982520,0xff9825b0,0xff982330,0xff9823b0,0xff9822f0,0xff982290}
        self.assertEqual(got,want)
        self.assertEqual(generate.inline_calls(rom,rows,{pc:() for pc in sites}),set(),'only once the routine is in the closure')

    def test_reproducers_stop_without_the_rule_and_run_past_with_it(self):
        without,with_rule=frontiers(False),frontiers(True)
        for seed,(pc,cycle,_) in STOPS.items():
            self.assertIn('outside the authenticated fixed translation; PC %d' % pc,without[seed][0],seed)
            self.assertNotIn('PC %d' % pc,with_rule[seed][0],seed)
            self.assertGreaterEqual(with_rule[seed][1],cycle,seed)
        print(dict(without=without,with_rule=with_rule))


if __name__=='__main__':unittest.main()
