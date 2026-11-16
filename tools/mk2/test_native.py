"""Exercise the real diagnostic process boundary without ROMs or a compiler."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import native
from tools.quality import run as quality


class NativeDiagnosticTests(unittest.TestCase):
    @unittest.skipUnless((quality.ROOT/'roms/mk2').is_dir(),'requires authenticated MK2 ROMs')
    def test_cold_boot_observer_keeps_all_early_rows_and_preserves_guest_state(self):
        native.foundation.verify_roms(quality.ROOT/'roms/mk2')
        sources=['native/tests/mk2_initial_scanout_tests.cpp',*native.foundation.EXECUTOR_SOURCES]
        with quality.scratch_tree() as (scratch,cleanup):
            executable=scratch/'initial-scanout.exe'
            build=quality.command([quality.DEFAULT_CC,'-std=c++17','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(quality.ROOT/'native/include'),*[quality.ROOT/p for p in sources],
                '-lbcrypt','-o',executable],scratch,env=native.environment(),timeout=600)
            self.assertTrue(build['passed'],build)
            result=quality.command([executable,quality.ROOT/'roms/mk2'],scratch,env=native.environment())
            self.assertTrue(result['passed'],result)
        self.assertFalse(cleanup['exists_after'])

    def test_child_keeps_exclusive_temp_and_mandatory_gpu_validation(self):
        with quality.scratch_tree() as (scratch,cleanup):
            with patch.dict(os.environ,{"TEMP":"C:/unowned-temp","TMP":"D:/unowned-temp",
                                        "PYTHONOPTIMIZE":"1","ASAN_SAVE_DUMPS":"1",
                                        "MK1_GRAPHICS_VALIDATE":"0","MK1_CRT_PRESET":"energy"}):
                result=quality.command([sys.executable,"-B","-c",
                    "import json,os;print(json.dumps({k:os.environ.get(k) for k in "
                    "('TEMP','TMP','PYTHONOPTIMIZE','ASAN_SAVE_DUMPS','MK1_GRAPHICS_VALIDATE','MK1_CRT_PRESET')}))"],
                    scratch,env=native.environment())
            self.assertTrue(result["passed"],result)
            child=json.loads(result["stdout"])
            self.assertEqual(child["TEMP"],str(scratch))
            self.assertEqual(child["TMP"],str(scratch))
            self.assertIsNone(child["PYTHONOPTIMIZE"])
            self.assertIsNone(child["ASAN_SAVE_DUMPS"])
            self.assertEqual(child["MK1_GRAPHICS_VALIDATE"],"1")
            self.assertEqual(child["MK1_CRT_PRESET"],"energy")
        self.assertFalse(cleanup["exists_after"])


if __name__=="__main__":unittest.main()
