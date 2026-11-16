"""Raw CMOS storage contract; disposable profiles, no product or ROM writes."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as quality

class CmosFileTests(unittest.TestCase):
    def test_raw_cmos_exact_bytes_conflicts_game_locks_and_rollback(self):
        with quality.scratch_tree() as (scratch,cleanup):
            root=quality.ROOT
            executable=scratch/'cmos-file.exe'
            env=dict(os.environ,PATH=str(quality.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH',''),TEMP=str(scratch),TMP=str(scratch))
            result=quality.command([quality.DEFAULT_CC,'-std=c++17','-O2','-municode','-Wall','-Wextra','-Werror',
                '-I'+str(root/'native/include'),'-I'+str(root/'native/mk2'),root/'native/tests/cmos_file_tests.cpp',
                root/'native/mk2/mk2_profile.cpp',root/'native/src/mk5_program.cpp','-lbcrypt','-o',executable],
                scratch,cwd=root,env=env,timeout=90)
            self.assertTrue(result['passed'],quality.compact(result))
            result=quality.command([executable,scratch/'profiles'],scratch,cwd=root,env=env,timeout=30)
            self.assertTrue(result['passed'],quality.compact(result))
            self.assertIn('PASS:',result['stdout'])
            import _winapi
            target=scratch/'junction-target'
            target.mkdir()
            (target/'cmos.bin').write_bytes(b'\x83'*16384)
            junction=scratch/'junction'
            try:
                _winapi.CreateJunction(str(target),str(junction))
                result=quality.command([executable,'reject-link',junction/'cmos.bin',target/'cmos.bin'],
                                       scratch,cwd=root,env=env,timeout=30)
                self.assertTrue(result['passed'],quality.compact(result))
            finally:
                if junction.is_junction():
                    self.assertEqual(junction.absolute().parent,scratch.absolute())
                    junction.rmdir()
        self.assertFalse(cleanup['exists_after'])

if __name__=='__main__':unittest.main()
