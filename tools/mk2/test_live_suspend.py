"""Instruction-boundary suspension: whole native states and streaming raw AV equality, not Original-prefix qualification."""
import os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import profile,run
from tools.quality import run as q

class LiveSuspendTests(unittest.TestCase):
    @unittest.skipUnless((q.ROOT/'roms/mk2').is_dir(),'requires authenticated ROMs')
    def test_different_partitions_preserve_entire_state_and_every_native_raster_and_DAC_sample(self):
        identities=run.verify_roms(q.ROOT/'roms/mk2')
        sources=[p for p in run.SOURCES if p!='native/tests/mk2_foundation_tests.cpp']+['native/tests/mk2_live_suspend_tests.cpp']
        inputs={p:q.sha(__import__('tools.setup.mk2',fromlist=['source']).source(p))for p in dict.fromkeys(sources+run.HEADERS)}
        with q.scratch_tree()as(scratch,cleanup):
            exe=scratch/'live-suspend.exe';env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH','')}
            build=q.command([q.DEFAULT_CC,'-std=c++17','-O1','-Wall','-Wextra','-Werror',
                '-Wno-unused-parameter','-Wno-missing-field-initializers','-I'+str(q.ROOT/'native/include'),
                *[q.ROOT/p for p in sources],'-lbcrypt','-o',exe],scratch,env=env,timeout=240)
            self.assertTrue(build['passed'],build['stdout'])
            result=q.command([exe,q.ROOT/'roms/mk2',profile.FACTORY_SEED,scratch],scratch,env=env,timeout=240)
            self.assertTrue(result['passed'],result['stdout'])
            print(result['stdout'],end='')
            from PIL import Image
            for name in ('operator-paid','operator-freeplay'):
                raw=(scratch/(name+'.bgra')).read_bytes()
                self.assertEqual(len(raw),400*254*4)
                Image.frombytes('RGBA',(400,254),raw,'raw','BGRA').convert('RGB').save(q.STAGE/('mk2-'+name+'.png'))
            self.assertEqual(inputs,{p:q.sha(__import__('tools.setup.mk2',fromlist=['source']).source(p))for p in inputs})
            self.assertEqual(identities,run.verify_roms(q.ROOT/'roms/mk2'))
        self.assertFalse(cleanup['exists_after'])
if __name__=='__main__':unittest.main()
