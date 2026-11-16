"""K3 front A: stop class ff963280-io5 of build/native/mk3-m2/k3-stops.json (front B, R3 session pilot).

Source: midwunit_state::io_r (docs/investigation/sources/midwunit_m.cpp:105-131, pinned 4f9dcc8) with the identity
m_ioshuffle of machine_reset (:319-328): offsets 0-3 read the ports, 4 the PIC status << 12 | sound_state_r, every other
offset (5-7) only logs and returns ~0. Past it the same loop (0xff963260: header pointers from *A0+) reads
0x01b00000: midwunit_control_r (docs/investigation/sources/midtunit_v.cpp:392-395) returns m_midtunit_control for both
words. Translation: Ops::Read16 (native/mk3/mk3_cpu.hpp), DevicePaths {Ops::kIoDefaultRead | offset, from = PC} and
{Ops::kControlRead, from = PC}: Strict rejects them unless route-verified, Game runs them and notes them.

Native (Profile::Game, from reset, native/tests/mk3_vram_hook_main.cpp): the reproducer (explore.random_session seed
300088, 180 s) stops at 0xff963280 / 0x01800050 with the negative control (Ops::io_default_reads = false) and runs past
the stop cycle with the rule; its io reads at the stop match the Original's watchpoint reads recorded by front B
(word 4 = 0x0C00, word 5 = 0xFFFF, word 6 = 0xFFFF, same cycles). The second tape (seed 300055) runs past its stop.
Exploration only: the DevicePath stays unverified until a route confirms it in the Original.
"""
import json,os,sys,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import generate,reference,reference_dma
from tools.mk3.explore import random_session,tape_sha,TMS_HZ

ROOT=Path(__file__).resolve().parents[2]
STOP=json.loads((ROOT/'build/native/mk3-m2/k3-stops.json').read_text('utf-8'))
STOP=next(s for s in STOP['stops'] if s['id']=='ff963280-io5')
PC,ADDRESS,CYCLE=int(STOP['native']['pc'],16),int(STOP['native']['address'],16),STOP['native']['cycle']
SECOND=STOP['native']['other_tape']
MARGIN=2_000_000   # TMS cycles past the stop (0.32 s)
WINDOW=(CYCLE-1000,CYCLE+50_000)


def original_reads():
    """[(address, value, cycle)] of the Original's watchpoints inside WINDOW (front B's probe)."""
    out=[]
    for key,(_,_,_,hits) in STOP['original']['reads'].items():
        address=int(key.split()[1],16)
        out+=[(address,v,c) for v,c in hits if WINDOW[0]<=c<=WINDOW[1]]
    return sorted(out,key=lambda r:(r[2],r[0]))


def runs():
    cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
    with q.scratch_tree() as (temp,cleanup):
        exe=temp/'mk3-k3a.exe'
        build=generate.build(temp,[ROOT/'native/tests/mk3_vram_hook_main.cpp',ROOT/'native/mk3/mk3_adsp.cpp',*(ROOT/'native/mk3'/n for n in generate.RUNTIME),
                                   ROOT/'native/mk2/mk2_dcs.cpp',ROOT/'native/src/mk5_program.cpp'],exe,unicode=False)
        assert build['passed'],q.compact(build)
        (temp/'gfx.txt').write_text(''.join(f'{o} {s} {p}\n' for p,o,s in reference_dma.graphics_rows()),encoding='utf-8')
        jobs={}
        for name,seed,horizon,extra in (('negative',STOP['reproducer']['seed'],CYCLE+MARGIN,'negative-io\n'),
                                        ('rule',STOP['reproducer']['seed'],CYCLE+MARGIN,''),
                                        ('second',SECOND['seed'],SECOND['end_cycle']+MARGIN,'')):
            tape=random_session(seed,180*TMS_HZ)['tape']
            if seed==STOP['reproducer']['seed']:assert tape_sha(tape)==STOP['reproducer']['tape_sha256']
            (temp/f'{name}.txt').write_text(f'horizon {horizon}\nreads {WINDOW[0]} {WINDOW[1]}\n'+extra+''.join(f'tape {c} {p} {v}\n' for c,p,v in tape),encoding='ascii')
            jobs[name]=temp/f'{name}.txt'
        def one(name):
            run=q.command([exe,ROOT/'roms/mk3',reference.SEED,temp/'gfx.txt',jobs[name],'off'],temp,cwd=ROOT,env=env,timeout=1800)
            assert run['passed'],q.compact(run)
            return name,dict(json.loads(run['stdout'].strip().splitlines()[-1]),wall_seconds=run['wall_seconds'])
        with ThreadPoolExecutor(3) as ex:out=dict(ex.map(one,jobs))
    assert not cleanup['exists_after']
    return out,build['wall_seconds']


class IoDefault(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.out,cls.build_seconds=runs()

    def test_negative_stops_at_the_recorded_frontier(self):
        neg=self.out['negative']
        self.assertEqual(neg['frontier'],'MK3 read outside translated Wolf-Unit map; PC %d; address %d' % (PC,ADDRESS))
        self.assertEqual(neg['cycles'],CYCLE)

    def test_rule_runs_past_and_reads_what_the_original_read(self):
        rule,second=self.out['rule'],self.out['second']
        self.assertEqual(rule['frontier'],'none');self.assertGreaterEqual(rule['cycles'],CYCLE+MARGIN)
        self.assertNotIn('PC %d' % PC,second['frontier']);self.assertGreaterEqual(second['cycles'],SECOND['end_cycle'])
        native=sorted(((a,v,c) for _,a,v,c in rule['io_reads'] if a in (0x01800040,0x01800050,0x01800060)),key=lambda r:(r[2],r[0]))
        self.assertEqual(native,original_reads())
        paths={(i,f) for i,f,_ in rule['device_paths']}
        self.assertIn((0x01800005,PC),paths)
        print(json.dumps(dict(build_seconds=self.build_seconds,runs={n:{k:r[k] for k in ('frontier','cycles','device_paths','wall_seconds')} for n,r in self.out.items()},
                              reads=len(native)),indent=1))


if __name__=='__main__':unittest.main()
