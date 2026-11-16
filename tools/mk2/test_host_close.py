"""Real native CPU/DSP cooperative-close regression with a strict fake window; no GPU claim."""
import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import native,profile,run as foundation
from tools.quality import run as quality
ROOT=quality.ROOT
FAKE_WINDOW=ROOT/'native/tests/mk2_host_close_window.cpp'


class HostCloseLifecycleTests(unittest.TestCase):
    @unittest.skipUnless((ROOT/'roms/mk2').is_dir()and quality.DEFAULT_CC.is_file(),
                         'requires authenticated MK2 ROMs and compiler; no real window or audio')
    def test_real_guest_closes_at_yield_preserves_held_input_and_rejects_driver_failure(self):
        foundation.verify_roms(ROOT/'roms/mk2')
        profile._read(profile.FACTORY_SEED,factory=True)
        with quality.scratch_tree()as(scratch,cleanup):
            executable=scratch/'host-close.exe'
            sources=[ROOT/name for name in foundation.SOURCES if name!='native/tests/mk2_foundation_tests.cpp']
            sources+=[ROOT/'native/mk2/mk2_native_check.cpp',ROOT/'native/mk2/mk2_music.cpp',ROOT/'native/src/mk5_audio_output.cpp',FAKE_WINDOW]
            env={'PATH':str(quality.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH','')}
            build=quality.command([quality.DEFAULT_CC,'-std=c++17','-O1','-municode','-pthread',
                '-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-missing-field-initializers',
                '-I'+str(ROOT/'native/include'),*sources,'-lbcrypt','-luser32','-lgdi32','-lwinmm',
                '-o',executable],scratch,env=env,timeout=150)
            self.assertTrue(build['passed'],quality.compact(build))
            argv=[executable,ROOT/'roms/mk2','--window','--host-controls','--through','cmos-host',
                  '--cmos-image',profile.FACTORY_SEED]
            cases=[]
            for samples in(0,1,2):
                result=quality.command(argv,scratch,env=dict(env,MK2_TEST_CLOSE_AFTER_SAMPLES=str(samples),
                    MK2_TEST_INPUT='ffffffef'),timeout=25,output_limit=256*1024)
                self.assertTrue(result['passed'],quality.compact(result))
                self.assertEqual(result['discarded_output_bytes'],0)
                observed=json.loads(result['stdout']);payload=bytes.fromhex(observed.pop('cmos_hex'))
                self.assertEqual(len(payload),profile.SIZE)
                native.validate_valid_host_boundary(observed)
                host=observed['host_controls'];presentation=observed['presentation']
                self.assertIs(host['stop_requested'],True)
                self.assertIs(presentation['test_double'],True)
                self.assertIs(presentation['closed'],True)
                self.assertEqual(presentation['host_samples'],samples)
                self.assertEqual(observed['termination'],'finite_valid_cmos_host_stop_requested')
                if not samples:
                    self.assertTrue(native.frontier_matches(observed['cpu34'],native.frontier('cmos-draw')))
                    self.assertIs(host['provider_admitted'],False)
                    self.assertEqual(host['provider_requests'],0)
                    self.assertEqual(host['events'],[])
                else:
                    self.assertIs(host['provider_admitted'],True)
                    self.assertGreaterEqual(host['provider_requests'],samples)
                    self.assertEqual(host['last_input'],0xffffffef)
                    self.assertLess(observed['cpu34'][2],10000000)
                cases.append((observed,payload))
            left,right=cases[1:]
            for field in('cpu34','frame_sha256','frames'):
                self.assertEqual(left[0][field],right[0][field])
            self.assertEqual(left[0]['host_controls']['events'],right[0]['host_controls']['events'])
            self.assertEqual(left[1],right[1],'all16384 CMOS bytes must match across close timings')
            failed=quality.command(argv,scratch,env=dict(env,MK2_TEST_CLOSE_AFTER_SAMPLES='0',
                MK2_TEST_FAILURE_AFTER_FALSE='1'),timeout=25,output_limit=256*1024)
            self.assertFalse(failed['passed'])
            self.assertEqual(failed['exit_code'],1)
            self.assertIn('published fake GPU driver failure',failed['stdout'])
            self.assertNotIn('cmos_hex',failed['stdout'])
            self.assertNotIn('{',failed['stdout'],'driver failure must not emit successful JSON')
            seed=scratch/'service-factory.bin'
            image=profile.FACTORY_SEED.read_bytes()
            seed.write_bytes(image)
            service=[executable,ROOT/'roms/mk2','--window','--through','test-switch','--cmos-image',seed]
            service_env=dict(env,MK2_TEST_CLOSE_AFTER_SAMPLES='32',MK2_TEST_INPUT='ffffffff')
            result=quality.command(service,scratch,env=service_env,timeout=25,output_limit=8000)
            self.assertTrue(result['passed'],quality.compact(result))
            observed=json.loads(result['stdout'])
            self.assertEqual(observed['operator_dsw_word'],0xfc7c)
            self.assertEqual(observed['first_input_tick'],61*1827925)
            self.assertEqual(observed['input_samples'],32)
            self.assertGreaterEqual(observed['frames'],80)
            self.assertEqual(observed['termination'],'window_closed')
            self.assertTrue(observed['presentation']['closed'])
            self.assertEqual(seed.read_bytes(),image)
            unsupported=quality.command(service,scratch,env=dict(service_env,MK2_TEST_INPUT='fffffffe'),
                                        timeout=25,output_limit=8000)
            self.assertFalse(unsupported['passed'])
            self.assertIn('accepts P1 Down and High Punch',unsupported['stdout'])
            seed.write_bytes(bytes([image[0]^1])+image[1:])
            modified=quality.command(service,scratch,env=service_env,timeout=25,output_limit=8000)
            self.assertFalse(modified['passed'])
            self.assertIn('requires the authenticated factory CMOS image',modified['stdout'])
            combined=quality.command(service+['--dsw-word','0xfc7d'],scratch,env=service_env,timeout=25,output_limit=8000)
            self.assertFalse(combined['passed'])
            self.assertIn('usage:',combined['stdout'])
        self.assertFalse(cleanup['exists_after'])


if __name__=='__main__':unittest.main()
