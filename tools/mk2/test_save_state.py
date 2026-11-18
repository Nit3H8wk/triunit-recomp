"""MK2 Original save states: save at a live chunk, replay m chunks after a load with identical rasters, ticks, DAC bits and state."""
import os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import profile,run
from tools.quality import run as q

class SaveStateTests(unittest.TestCase):
    @unittest.skipUnless((q.ROOT/'roms/mk2').is_dir(),'requires authenticated ROMs')
    def test_load_replays_every_raster_DAC_sample_and_state_in_and_across_sessions(self):
        identities=run.verify_roms(q.ROOT/'roms/mk2')
        sources=[p for p in run.SOURCES if p!='native/tests/mk2_foundation_tests.cpp']+['native/tests/mk2_save_state_tests.cpp']
        with q.scratch_tree()as(scratch,cleanup):
            exe=scratch/'save-state.exe';env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH','')}
            build=q.command([q.DEFAULT_CC,'-std=c++17','-O1','-Wall','-Wextra','-Werror',
                '-Wno-unused-parameter','-Wno-missing-field-initializers','-I'+str(q.ROOT/'native/include'),
                *[q.ROOT/p for p in sources],'-lbcrypt','-o',exe],scratch,env=env,timeout=240)
            self.assertTrue(build['passed'],build['stdout'])
            result=q.command([exe,q.ROOT/'roms/mk2',profile.FACTORY_SEED],scratch,env=env,timeout=240)
            self.assertTrue(result['passed'],result['stdout'])
            print(result['stdout'],end='')
            self.assertEqual(identities,run.verify_roms(q.ROOT/'roms/mk2'))
        self.assertFalse(cleanup['exists_after'])


class WindowStateTests(unittest.TestCase):
    """F5/F7 through the live loop of mk2_native_check (the path the game window drives), with the test window: the
    request queue, the slot file under saves/mk2/<program sha>/, a load from memory, and a load of that file by a new
    session. CPU, DSP and CMOS are the real native implementation; no GPU or audio."""
    @unittest.skipUnless((q.ROOT/'roms/mk2').is_dir(),'requires authenticated ROMs')
    def test_live_loop_saves_loads_and_reloads_the_slot_in_a_new_session(self):
        run.verify_roms(q.ROOT/'roms/mk2')
        sources=[q.ROOT/p for p in run.SOURCES if p!='native/tests/mk2_foundation_tests.cpp']
        sources+=[q.ROOT/p for p in ('native/mk2/mk2_native_check.cpp','native/mk2/mk2_music.cpp','native/src/mk5_audio_output.cpp',
                                    'native/tests/mk2_host_close_window.cpp')]
        with q.scratch_tree()as(scratch,cleanup):
            exe=scratch/'state-window.exe';env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH','')}
            build=q.command([q.DEFAULT_CC,'-std=c++17','-O1','-municode','-pthread','-Wall','-Wextra','-Werror',
                '-Wno-unused-parameter','-Wno-missing-field-initializers','-I'+str(q.ROOT/'native/include'),*sources,
                '-lbcrypt','-luser32','-lgdi32','-lwinmm','-o',exe],scratch,env=env,timeout=300)
            self.assertTrue(build['passed'],q.compact(build))
            profile.prepare(scratch/'profile')
            argv=[exe,q.ROOT/'roms/mk2','--window','--host-controls','--through','cmos-live','--profile',scratch/'profile']
            def session(plan,samples):
                result=q.command(argv,scratch,cwd=scratch,timeout=120,output_limit=1<<20,
                                 env=dict(env,MK2_TEST_STATE=plan,MK2_TEST_CLOSE_AFTER_SAMPLES=str(samples)))
                out=result['stdout'];lines=[l[:300] for l in out.splitlines() if 'cmos_hex' not in l]
                # The session ends at the profile guard: CMOS is committed only after a real D3D12 presentation, which
                # the test window does not claim. Any other failure (a state error included) fails the test.
                self.assertFalse(result['timed_out'],lines)
                self.assertEqual((result['exit_code'],'native profile requires unambiguous presentation metrics' in out),(1,True),lines)
                return out
            first=session('save@40,load@80',120)
            slot=next((scratch/'saves/mk2').glob('*/slot1.state'))
            self.assertIn('MK2 state saved: saves/mk2/',first)
            self.assertIn('MK2 state loaded from memory',first)
            self.assertGreater(slot.stat().st_size,1<<20)
            second=session('load@10',60)
            self.assertIn('MK2 state loaded from saves/mk2/',second)
            self.assertNotIn('not loaded',second)
        self.assertFalse(cleanup['exists_after'])
if __name__=='__main__':unittest.main()
