"""Original first-boot SPORT and IRQ1 primitive contracts (IRQ1 vector read from the user's U2)."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as quality


class FirstBootSportTests(unittest.TestCase):
    def test_internal_dm_transfer_and_unmasked_irq1_preserve_context(self):
        compiler=quality.DEFAULT_CC
        with quality.scratch_tree() as (scratch,cleanup):
            exe=scratch/'first-boot-sport.exe'
            env={'PATH':str(compiler.parent)+os.pathsep+os.environ.get('PATH','')}
            sources=['native/tests/mk2_first_boot_sport_tests.cpp','native/mk2/mk2_adsp.cpp',
                     'native/mk2/mk2_dcs.cpp','native/src/mk5_program.cpp']
            build=quality.command([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror',
                '-fno-access-control','-I'+str(quality.ROOT/'native/include'),
                *[quality.ROOT/p for p in sources],'-lbcrypt','-o',exe],scratch,env=env,timeout=120)
            self.assertTrue(build['passed'],build.get('stdout',''))
            result=quality.command([exe,quality.ROOT/'roms/mk2/su2.l1'],scratch,env=env)
            self.assertTrue(result['passed'],result.get('stdout',''))
        self.assertFalse(cleanup['exists_after'])


if __name__=='__main__':unittest.main()
