"""Inject transient Win32 rename failures into real CMOS storage; no ROM or product writes."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as quality

class CmosRenameRetryTests(unittest.TestCase):
    def test_transient_rename_recovery_is_bounded_preserving_and_locked(self):
        with quality.scratch_tree() as (scratch,cleanup):
            root=quality.ROOT
            executable=scratch/'cmos-rename.exe'
            env=dict(os.environ,PATH=str(quality.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH',''),TEMP=str(scratch),TMP=str(scratch))
            built=quality.command([quality.DEFAULT_CC,'-std=c++17','-O2','-municode','-Wall','-Wextra','-Werror',
                '-I'+str(root/'native/include'),'-I'+str(root/'native/mk2'),root/'native/tests/cmos_rename_retry_tests.cpp',
                root/'native/src/mk5_program.cpp','-lbcrypt','-o',executable],scratch,cwd=root,env=env,timeout=90)
            self.assertTrue(built['passed'],quality.compact(built))
            result=quality.command([executable,scratch/'profiles'],scratch,cwd=root,env=env,timeout=30)
            self.assertTrue(result['passed'],quality.compact(result))
            self.assertIn('PASS 20 raw CMOS rename boundary cases',result['stdout'])
        self.assertFalse(cleanup['exists_after'])

if __name__=='__main__':unittest.main()
