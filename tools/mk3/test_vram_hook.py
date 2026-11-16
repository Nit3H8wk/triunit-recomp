"""K3 front A: Ops::vram_observer (native/mk3/mk3_cpu.hpp), the read-only hook on the CPU's VRAM stores asked by front C
(build/native/mk3-m2/rm2.json hooks_requested_from_front_A).

The K1 routes (build/native/mk3-m2/routes attract, fight, match: tape and horizon from reset) run in
native/tests/mk3_vram_hook_main.cpp with the observer attached and detached: the chain of complete-state hashes at every
2^17 cycles, the first-execution/interrupt log, the end cycle, PC and instruction count must be identical, and the
detached run must end where the receipt's integral comparison ended. The observer's calls must each follow their store
(value, PC, cycle) and the match route must show the stores of PC 0xff928130. Native only: no new comparison with the
Original; the routes' digests stay checked by `python tools/mk3/explore.py regress attract fight match`.
"""
import json,os,sys,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import explore,generate,reference,reference_dma

ROOT=Path(__file__).resolve().parents[2]
ROUTES=('attract','fight','match')
SKY_PC=0xff928130


def runs():
    cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
    with q.scratch_tree() as (temp,cleanup):
        exe=temp/'mk3-vram-hook.exe'
        build=generate.build(temp,[ROOT/'native/tests/mk3_vram_hook_main.cpp',ROOT/'native/mk3/mk3_adsp.cpp',*(ROOT/'native/mk3'/n for n in generate.RUNTIME),
                                   ROOT/'native/mk2/mk2_dcs.cpp',ROOT/'native/src/mk5_program.cpp'],exe,unicode=False)
        assert build['passed'],q.compact(build)
        (temp/'gfx.txt').write_text(''.join(f'{o} {s} {p}\n' for p,o,s in reference_dma.graphics_rows()),encoding='utf-8')
        receipts={n:json.loads((ROOT/f'build/native/mk3-m2/routes/{n}.json').read_text('utf-8')) for n in ROUTES}
        for n,r in receipts.items():
            (temp/f'{n}.txt').write_text(f"horizon {r['horizon']}\n"+''.join(f'tape {c} {p} {v}\n' for c,p,v in explore.receipt_tape(r)),encoding='ascii')
        def one(job):
            n,mode=job
            run=q.command([exe,ROOT/'roms/mk3',reference.SEED,temp/'gfx.txt',temp/f'{n}.txt',mode],temp,cwd=ROOT,env=env,timeout=1800)
            assert run['passed'],q.compact(run)
            return job,dict(json.loads(run['stdout'].strip().splitlines()[-1]),wall_seconds=run['wall_seconds'])
        with ThreadPoolExecutor(6) as ex:out=dict(ex.map(one,[(n,m) for n in ROUTES for m in ('off','on')]))
    assert not cleanup['exists_after']
    return receipts,out,build['wall_seconds']


class VramHook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.receipts,cls.out,cls.build_seconds=runs()

    def test_observer_does_not_change_the_routes(self):
        same=('pc','instructions','frontier','cycles','records','chain','first_irq','tape_applied')
        for n in ROUTES:
            off,on=self.out[n,'off'],self.out[n,'on']
            self.assertEqual({k:off[k] for k in same},{k:on[k] for k in same},n)
            end=self.receipts[n]['integral']['end']
            self.assertEqual((off['cycles'],off['pc'],off['instructions'],off['frontier']),(end['cycle'],end['pc'],end['instructions'],'none'),n)
            self.assertEqual(off['calls'],0,n)

    def test_observer_follows_every_store_and_sees_the_sky_writer(self):
        for n in ROUTES:
            on=self.out[n,'on']
            self.assertEqual(on['mismatches'],0,n)
            self.assertLessEqual(on['bus_matched'],on['calls'],n)
        match=self.out['match','on']
        self.assertGreater(match['pcs'].get(f'{SKY_PC:08x}',0),0,'PC ff928130 stores observed on the match route')
        print(json.dumps(dict(build_seconds=self.build_seconds,runs={f'{n}:{m}':{k:v for k,v in r.items() if k!='pcs'}|dict(pcs=len(r['pcs']),
                         sky=r['pcs'].get(f'{SKY_PC:08x}',0)) for (n,m),r in self.out.items()}),indent=1))


if __name__=='__main__':unittest.main()
