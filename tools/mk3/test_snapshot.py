"""K4 front B: the exploration snapshot (mk3_replay_main `fork`, tools/mk3/replay.Explorer; decision 3: search only,
never an acceptance or a count) against runs from reset of the same legal tape (J3 reset -> round start, Profile::Game).

A snapshot copies the Board and the harness before the first boundary >= N is handled. Every branch must print exactly
the lines the run from reset prints from that boundary on: each record (CPU registers, RAM/CMOS/palette/VRAM/DM/PM
hashes, DMA and I/O registers, ADSP fields, PCM segment, event-stream counts and hashes since reset), the END dumps of
every region, the summary (bus counts, host events, interrupts, DAC block times, first-execution log) and the whole
dcs/input/cmos streams. One process visits a chain of snapshots by keep/adopt, as tower.plan_guided does: plain,
mid-DMA (DMA_COMMAND bit 15) and mid-DCS (just after a sound-port write: its 500 ns quantum in force); branches of one
snapshot run in parallel, one with a different tape (equal to its own run from reset). Negative: a copy that drops the
DCS latches (power-on values) must diverge. Builds the working-tree executor (minutes).
"""
from pathlib import Path
import json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3 import explore,replay,replay_state

TAPE=explore.FIGHT_TAPE
H=240_000_000                      # horizon of every compared run (the FIGHT_TAPE rows end at 188,125,000)
STEP=1<<20
PLAIN,DMA=120_000_000,150_006_078  # DMA: a DMA in flight at that boundary (native probe; asserted below)
EXTRA=((200_000_000,3,0xfffe),(200_625_000,3,0xffff))   # a coin pulse past the last fork: the parallel branch's own tape


def is_record(line):return line.startswith('{"spec"')


def tail(lines,at):
    """The lines of a run from reset that a branch from a snapshot at boundary `at` prints (header excluded)."""
    return [l for l in lines[1:] if not is_record(l) or json.loads(l)['cycle']>=at]


class Snapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native=replay.Native(profile='game').__enter__()
        dumps=[(r,0) for r in replay_state.REGIONS]
        run=lambda tape:cls.native.run(STEP,STEP,H,H,tape,dumps,events=True,raw=True)
        cls.ref=run(TAPE).splitlines();cls.ref2=run(tuple(sorted(TAPE+EXTRA))).splitlines()
        cls.dumps=dumps

    @classmethod
    def tearDownClass(cls):cls.native.__exit__(None,None,None)

    def branch(self,at,tape,**kw):return dict(tape=tuple(r for r in tape if r[0]>=at),horizon=H,dumps=self.dumps,**kw)

    def test_chain(self):
        with replay.Explorer(self.native,tuple(r for r in TAPE if r[0]<PLAIN),PLAIN,lines=[f'every {STEP} {STEP} {H}']) as ex:
            self.assertEqual(ex.header,self.ref[0])
            self.assertEqual(ex.base,[l for l in self.ref[1:] if is_record(l) and json.loads(l)['cycle']<ex.snapshot['snapshot']])
            ex.run([self.branch(PLAIN,TAPE),dict(tape=tuple(r for r in TAPE if PLAIN<=r[0]<DMA),horizon=DMA,keep=True)])
            self.assertEqual(ex.raw[0],tail(self.ref,ex.snapshot['snapshot']))
            s=ex.adopt(1);self.assertTrue(s['dma_command']&0x8000,s)                      # mid-DMA
            dcs=next(c for c,_ in json.loads(next(l for l in self.ref if l.startswith('{"events_total"')))['events_full']['dcs'] if c>s['snapshot'])
            ex.run([self.branch(DMA,TAPE),dict(tape=tuple(r for r in TAPE if DMA<=r[0]<dcs+8),horizon=dcs+8,keep=True)])
            self.assertEqual(ex.raw[0],tail(self.ref,s['snapshot']))
            s=ex.adopt(1);self.assertTrue(s['boost'],s)                                      # mid-DCS: a data write's quantum
            at=s['snapshot']
            ex.run([self.branch(at,TAPE),self.branch(at,sorted(TAPE+EXTRA)),self.branch(at,TAPE,drop='latches')])
            self.assertEqual(ex.raw[0],tail(self.ref,at))
            self.assertEqual(ex.raw[1],tail(self.ref2,at))
            self.assertNotEqual((s['latch_control'],s['input_data'],s['output_data']),(0x0c00,0,0))
            self.assertNotEqual(ex.raw[2],tail(self.ref,at))                                # negative: an incomplete copy
            k=next(i for i,(a,b) in enumerate(zip(ex.raw[2],tail(self.ref,at))) if a!=b)
            self.assertTrue(is_record(ex.raw[2][k]) or 'frontier' in ex.raw[2][k])


if __name__=='__main__':unittest.main()
