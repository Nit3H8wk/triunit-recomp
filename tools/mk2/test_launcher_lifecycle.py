"""Own temporary fake packages/processes; never launch installed games or touch profiles."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as quality
import runpy
backend_arguments=runpy.run_path(quality.ROOT/'tools/launcher_backend_build.py')['arguments']


class LauncherLifecycleTests(unittest.TestCase):
    def test_mk2_restore_draft_uses_supported_defaults_and_keeps_profiles_separate(self):
        with quality.scratch_tree() as (scratch,cleanup):
            executable=scratch/'launcher-settings.exe'
            env={'PATH':str(quality.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH','')}
            sources=('native/tests/mk2_launcher_settings_tests.cpp','native/launcher/launcher_renderer.cpp',
                     'native/launcher/launcher_backend.cpp')
            libraries=('d3d12','dxgi','d3dcompiler','dxguid','windowscodecs','ole32','uuid',
                       'gdi32','user32','shell32','winmm','xinput9_1_0')
            result=quality.command([quality.DEFAULT_CC,'-std=c++17','-O2','-municode',
                '-Wall','-Wextra','-Werror','-Wno-missing-field-initializers',
                *[quality.ROOT/path for path in sources],*['-l'+name for name in libraries],
                '-o',executable]+backend_arguments(quality.ROOT),scratch,env=env,timeout=120)
            self.assertTrue(result['passed'],result)
            result=quality.command([executable,scratch/'root'],scratch,env=env,timeout=20)
            self.assertTrue(result['passed'],result)
        self.assertFalse(cleanup['exists_after'])

    def test_running_session_closes_after_mk2_identity_metadata_disappears(self):
        with quality.scratch_tree() as (scratch,cleanup):
            executable=scratch/'launcher-lifecycle.exe'
            env={'PATH':str(quality.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH','')}
            result=quality.command([quality.DEFAULT_CC,'-std=c++17','-O2','-municode',
                '-Wall','-Wextra','-Werror','-I'+str(quality.ROOT/'native/launcher'),
                quality.ROOT/'native/tests/mk2_launcher_lifecycle_tests.cpp',
                quality.ROOT/'native/launcher/launcher_backend.cpp','-luser32','-o',executable]+backend_arguments(quality.ROOT),
                scratch,env=env,timeout=90)
            self.assertTrue(result['passed'],result)
            result=quality.command([executable,scratch/'root'],scratch,env=env,timeout=55)
            self.assertTrue(result['passed'],result)
        self.assertFalse(cleanup['exists_after'])


if __name__=='__main__':unittest.main()
