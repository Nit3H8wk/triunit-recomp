"""MK2 Original save states: save at a live chunk, replay m chunks after a load with identical rasters, ticks, DAC bits and state."""
import os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import profile,run
from tools.quality import run as q

class SaveStateTests(unittest.TestCase):
    @unittest.skipUnless((q.ROOT/'roms/mk2').is_dir(),'requires authenticated ROMs')
    def test_load_replays_every_raster_DAC_sample_and_state_in_and_across_sessions(self):
        identities=run.verify_roms(q.ROOT/'roms/mk2')
        sources=[p for p in run.SOURCES if p!='native/tests/mk2_foundation_tests.cpp']+['native/tests/mk2_save_state_tests.cpp']
        with q.scratch_tree()as(scratch,cleanup):
            exe=scratch/'save-state.exe';env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH','')}
            build=q.command([q.DEFAULT_CC,'-std=c++17','-O1','-Wall','-Wextra','-Werror',
                '-Wno-unused-parameter','-Wno-missing-field-initializers','-I'+str(q.ROOT/'native/include'),
                *[q.ROOT/p for p in sources],'-lbcrypt','-o',exe],scratch,env=env,timeout=240)
            self.assertTrue(build['passed'],build['stdout'])
            result=q.command([exe,q.ROOT/'roms/mk2',profile.FACTORY_SEED],scratch,env=env,timeout=240)
            self.assertTrue(result['passed'],result['stdout'])
            print(result['stdout'],end='')
            self.assertEqual(identities,run.verify_roms(q.ROOT/'roms/mk2'))
        self.assertFalse(cleanup['exists_after'])
if __name__=='__main__':unittest.main()
