"""Portable native adapter contract: real C++ profile API with hidden fake child, no guest/GPU/audio."""
from pathlib import Path
import os,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as quality
from tools.mk2 import run as foundation
from tools.launcher_backend_build import arguments

class NativeLauncherTests(unittest.TestCase):
    @unittest.skipUnless((quality.ROOT/'roms/mk2').is_dir()and quality.DEFAULT_CC.is_file(),'requires authenticated ROMs/compiler; no game or visible UI')
    def test_explicit_native_adapter_argv_env_profile_CAS_and_owned_close(self):
        foundation.verify_roms(quality.ROOT/'roms/mk2')
        with quality.scratch_tree()as(scratch,cleanup):
            exe=scratch/'native-launcher-contract.exe'
            env={'PATH':str(quality.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH',''),'MK2_ADAPTER_PROJECT_ROOT':str(quality.ROOT)}
            build=quality.command([quality.DEFAULT_CC,'-std=c++17','-O2','-static','-municode','-Wall','-Wextra','-Werror',
                '-I'+str(quality.ROOT/'native/launcher'),quality.ROOT/'native/tests/mk2_native_launcher_tests.cpp',
                quality.ROOT/'native/launcher/launcher_backend.cpp','-luser32','-lshell32',*arguments(quality.ROOT),'-o',exe],scratch,env=env,timeout=120)
            self.assertTrue(build['passed'],quality.compact(build))
            result=quality.command([exe,scratch/'portable root'],scratch,env=env,timeout=35)
            self.assertTrue(result['passed'],quality.compact(result))
        self.assertFalse(cleanup['exists_after'])

if __name__=='__main__':unittest.main()
