"""Generated MK2 executor from reset: full-state SHA-256 at every former manual-stage boundary and at delivery.

tools/mk2/executor_boundaries.json holds, per route, the (PC, cycle) of each boundary and the SHA-256 of the
serialized machine state there (native/tests/mk2_state_digest.hpp). The digests were taken on 15/11/2026 with the
manual chain and the executor side by side (equal in every section); no raw state is versioned.
"""
from pathlib import Path
import json
import os
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q

BOUNDARIES=Path(__file__).with_name('executor_boundaries.json')
CREDIT_FIXTURE=Path(__file__).with_name('startup_credit_fixture.json')
SOURCES=['native/tests/mk2_executor_tests.cpp','native/mk2/mk2_executor.cpp','native/mk2/mk2_task_batch.cpp',
         'native/mk2/mk2_program.cpp','native/mk2/mk2_dcs.cpp','native/mk2/mk2_adsp.cpp','native/src/mk5_program.cpp']


def images(seed):
    """CMOS images of the four startup profiles: factory seed, Free Play (checksum recomputed), credits below and at the price."""
    base=bytearray(seed.read_bytes())
    free=bytearray(base);free[0x1096]=1
    total=sum(free[0x1000+2*n] for n in range(168));check=(~total)&0xffff
    free[0x1150]=check>>8;free[0x1152]=check&0xff
    credit=bytearray(base)
    for at,value in json.loads(CREDIT_FIXTURE.read_text())['changed_words']:credit[at:at+2]=value.to_bytes(2,'little')
    out={'seed':bytes(base),'free_play':bytes(free)}
    for credits in (1,2):   # below and at the price: startup profiles 2 and 3; 554 holds the complement
        image=bytearray(credit);image[540]=credits;image[554]=255-credits;out[f'credit{credits}']=bytes(image)
    return out


class ExecutorTests(unittest.TestCase):
    @unittest.skipUnless((q.ROOT/'roms/mk2').is_dir(),'requires authenticated MK2 ROMs')
    def test_every_route_matches_the_recorded_boundary_digests(self):
        from tools.mk2 import profile
        routes=json.loads(BOUNDARIES.read_text())['routes']
        with q.scratch_tree() as (scratch,cleanup):
            exe=scratch/'executor.exe'
            env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH'],'TEMP':str(scratch),'TMP':str(scratch)}
            build=q.command([q.DEFAULT_CC,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-fno-access-control',
                '-Inative/include','-I'+str(q.ROOT),*[q.ROOT/p for p in SOURCES],'-lbcrypt','-o',exe],
                scratch,cwd=q.ROOT,env=env,timeout=600)
            self.assertTrue(build['passed'],build.get('stdout'))
            files={}
            for name,data in images(profile.FACTORY_SEED).items():
                files[name]=scratch/(name+'.bin');files[name].write_bytes(data)
            for route in routes:
                points=[f'{pc}:{cycle}' for name,pc,cycle,_ in route['boundaries'] if name!='deliver']
                cmos=str(files[route['cmos']]) if route['cmos'] else '-'
                result=q.command([exe,q.ROOT/'roms/mk2',f"{route['dsw']:x}",cmos,*points],scratch,cwd=q.ROOT,env=env,timeout=120)
                self.assertTrue(result['passed'],(route['route'],result.get('stdout')))
                rows=[line.split() for line in result['stdout'].splitlines() if line.strip()]
                wanted=[[str(pc),str(cycle),digest] for name,pc,cycle,digest in route['boundaries'] if name!='deliver']
                wanted+=[['deliver',str(pc),str(cycle),digest] for name,pc,cycle,digest in route['boundaries'] if name=='deliver']
                self.assertEqual(rows,wanted,route['route']+' '+hex(route['dsw']))
            # The qualified cold drawing TRAP and display IRQ contexts come from the executor itself (only their PCs and
            # cycles are versioned): vector bytes, changed fields and the IRQ entry are checked there.
            result=q.command([exe,q.ROOT/'roms/mk2','fc7d','-','trap-vector'],scratch,cwd=q.ROOT,env=env,timeout=120)
            self.assertTrue(result['passed'],result.get('stdout'))
            self.assertEqual(result['stdout'].split(),['trap-vector','4','6'])
            result=q.command([exe,q.ROOT/'roms/mk2','fc7d','-','display-irq'],scratch,cwd=q.ROOT,env=env,timeout=300)
            self.assertTrue(result['passed'],result.get('stdout'))
            self.assertEqual(result['stdout'].split(),['display-irq','14'])
        self.assertFalse(cleanup['exists_after'])


if __name__=='__main__':unittest.main()
