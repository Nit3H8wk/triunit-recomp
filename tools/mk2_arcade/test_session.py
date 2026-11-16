"""Exercise the real PowerShell launch boundary before starting the core."""
import json,os,subprocess,unittest
from pathlib import Path
from tools.quality import run as q

ROOT=Path(__file__).resolve().parents[2]
SESSION=ROOT/'tools/mk2_arcade/session.ps1'
PS=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'

class SessionTests(unittest.TestCase):
    def test_factory_cmos_is_created_once_and_existing_profile_is_preserved(self):
        from tools.mk2_arcade.build import prepare
        with q.scratch_tree() as (root,cleanup):
            prepare(root)
            command=[str(PS),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(SESSION),'-ProjectRoot',str(root),'-InitializeOnly']
            first=subprocess.run(command,capture_output=True,text=True,timeout=30)
            self.assertEqual(first.returncode,0,first.stderr)
            nvram=root/'build/native/mk2-arcade-v1/profile/nvram/mk2/nvram'
            from tools.setup import mk2 as setup_mk2
            self.assertEqual(nvram.read_bytes(),setup_mk2.seed_path().read_bytes())
            changed=bytes([0x57])*16384;nvram.write_bytes(changed)
            again=subprocess.run(command,capture_output=True,text=True,timeout=30)
            self.assertEqual(again.returncode,0,again.stderr);self.assertEqual(nvram.read_bytes(),changed)

    def test_unsupported_native_crt_preset_is_rejected_by_the_core_session(self):
        from tools.mk2_arcade.build import prepare
        with q.scratch_tree() as (root,cleanup):
            prepare(root)
            result=subprocess.run([str(PS),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(SESSION),'-ProjectRoot',str(root),'-InspectOnly','-CrtPreset','bvm-4k'],capture_output=True,text=True,timeout=30)
            self.assertNotEqual(result.returncode,0,'MK2 must not claim the native BVM shader from a scanline-alpha approximation')

    def test_altered_core_rejects_before_creating_or_touching_profiles(self):
        with q.scratch_tree() as (root,cleanup):
            product=root/'build/native/mk2-arcade-v1/product';product.mkdir(parents=True)
            core=root/'altered core.exe';core.write_bytes(b'not the authenticated core')
            (product/'manifest.json').write_text(json.dumps({'core_path':str(core),'core_sha256':'0'*64,'roms_required':[]}))
            result=subprocess.run([str(PS),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(SESSION),'-ProjectRoot',str(root),'-InspectOnly'],capture_output=True,text=True,timeout=20)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Core SHA-256',result.stdout+result.stderr)
            self.assertFalse((product.parent/'profile').exists())
        self.assertFalse(cleanup['exists_after'])

    def test_real_package_arguments_preserve_clock_and_isolate_all_writable_paths(self):
        from tools.mk2_arcade.build import prepare
        with q.scratch_tree() as (root,cleanup):
            prepare(root)
            result=subprocess.run([str(PS),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(SESSION),'-ProjectRoot',str(root),'-InspectOnly','-Brightness','110','-Filter','linear','-Bezel','0'],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            d=json.loads(result.stdout);args=d['arguments']
            self.assertIn('-throttle',args);self.assertEqual(args[args.index('-speed')+1],'1')
            self.assertIn('-norefreshspeed',args);self.assertIn('-nosyncrefresh',args)
            self.assertEqual(args[args.index('-brightness')+1],'1.10');self.assertIn('-filter',args)
            for key in ('-cfg_directory','-nvram_directory','-state_directory','-snapshot_directory'):
                self.assertTrue(Path(args[args.index(key)+1]).is_relative_to(root/'build/native/mk2-arcade-v1/profile'))
            self.assertFalse((root/'build/native/manual-temporary-8-20261025').exists())
        self.assertFalse(cleanup['exists_after'])

if __name__=='__main__':unittest.main()
