"""Actual sink gain contract with a required negative control; no real audio or dumps."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as quality

class GameVolumeTests(unittest.TestCase):
    def test_actual_sink_gain_and_negative_control(self):
        with quality.scratch_tree() as (scratch,cleanup):
            root=quality.ROOT
            env=dict(os.environ,PATH=str(quality.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH',''),TEMP=str(scratch),TMP=str(scratch))
            flags=[quality.DEFAULT_CC,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-I'+str(root/'native/include')]
            test=root/'native/tests/mk5_game_volume_sink_tests.cpp'
            sink=root/'native/src/mk5_audio_output.cpp'
            gain='else std::transform(data,data+n,slot.samples.data()+filled,[this](int16_t sample){return ScaleVolume(sample,volume);});'
            actual=sink.read_text(encoding='utf-8')
            self.assertEqual(actual.count(gain),1,'gain site moved: update negative control explicitly')
            (scratch/'negative-sink.cpp').write_text(actual.replace(gain,'else std::memcpy(slot.samples.data()+filled,data,n*2);'),encoding='utf-8')
            negative=scratch/'negative-test.cpp'
            negative.write_text(test.read_text(encoding='utf-8').replace('#include "../src/mk5_audio_output.cpp"','#include "negative-sink.cpp"'),encoding='utf-8')
            for name,source,expected in (('negative',negative,False),('actual',test,True)):
                executable=scratch/(name+'.exe')
                built=quality.command([*flags,source,'-o',executable],scratch,cwd=root,env=env,timeout=90)
                self.assertTrue(built['passed'],quality.compact(built))
                result=quality.command([executable],scratch,cwd=root,env=env,timeout=30)
                self.assertEqual(result['passed'],expected,quality.compact(result))
                if expected:self.assertIn('PASS: 17 real sink cases',result['stdout'])
                else:
                    self.assertEqual(result['exit_code'],1,quality.compact(result))
                    self.assertIn('scaled packet samples preserve signed truncation',result['stdout'])
        self.assertFalse(cleanup['exists_after'])

if __name__=='__main__':unittest.main()
