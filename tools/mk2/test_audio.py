"""DCS output adapter contracts; no device or ROM is required."""
import os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as quality


class AudioTests(unittest.TestCase):
    def test_bounded_pcm_adapter_is_independent_of_host_chunks_and_rejects_invalid_boundaries(self):
        cc=quality.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ.get('PATH','')}
        with quality.scratch_tree() as (scratch,cleanup):
            executable=scratch/'audio.exe'
            build=quality.command([cc,'-std=c++17','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(quality.ROOT/'native/include'),quality.ROOT/'native/tests/mk2_audio_tests.cpp',
                '-o',executable],scratch,env=env)
            self.assertTrue(build['passed'],build['stdout'])
            result=quality.command([executable],scratch,env=env)
            self.assertTrue(result['passed'],result['stdout'])
            print(result['stdout'].strip())
        self.assertFalse(cleanup['exists_after'])


if __name__=='__main__':unittest.main()
