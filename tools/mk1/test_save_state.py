"""MK1 save states (F5/F7): save between two ContinueMain calls of the live loop, replay 600 frames of the legal route
versus-a after a load, in the session and in a new session: identical rasters, Remastered layers, host PCM after the
gain and serialized state, Original and Remastered with music (synthetic tones as the user's tracks); header refusals
(damaged, truncated, another edition, other tracks). Harness: native/tests/mk5_save_state_tests.cpp."""
from pathlib import Path
import json,math,os,re,struct,sys,unittest,wave
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk1 import routes

ROOT=q.ROOT


class SaveStateTests(unittest.TestCase):
    @unittest.skipUnless((ROOT/'roms/mk1').is_dir(),'requires authenticated ROMs')
    def test_load_replays_every_frame_PCM_and_state_in_and_across_sessions(self):
        from tools.setup import mk1
        mk1.inc_dir();seed=mk1.seed_path().resolve()
        objects=json.loads((ROOT/'tools/mk1/runtime-inputs.json').read_text('utf-8'))['objects']
        with q.scratch_tree() as (scratch,cleanup):
            srcs=[ROOT/'native/tests/mk5_save_state_tests.cpp']+[ROOT/p for p in objects if Path(p).stem not in routes.EXCLUDE]
            exe,_=routes.build(scratch,srcs)
            tape=scratch/'versus-a.tsv';tape.write_bytes(routes.render_tape(routes.HERE/'tapes/versus-a.json'))
            env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH'],'TEMP':str(scratch),'TMP':str(scratch),
                 'MK1_GAME_VOLUME':'0'}
            r=q.command([exe,ROOT,tape,seed,scratch/'music'],scratch,cwd=ROOT,env=env,timeout=1800,output_limit=1<<20)
            self.assertTrue(r['passed'],q.compact(r))
            print(r['stdout'].strip().splitlines()[-1])
        self.assertFalse(cleanup['exists_after'])



def write_tracks(folder,gain_db):
    """Synthetic user tracks (tones, 48 kHz stereo, 2 s, repeat window) for every MK1 slot, under the test scratch."""
    folder.mkdir(parents=True)
    names=re.findall(r'\{"(music-\d+)"',(ROOT/'native/runtime/remastered_music_manifest.hpp').read_text('ascii'))
    for k,name in enumerate(names):
        with wave.open(str(folder/f'{name}.wav'),'wb') as w:
            w.setnchannels(2);w.setsampwidth(2);w.setframerate(48000)
            w.writeframes(b''.join(struct.pack('<hh',*(int(6000*math.sin(n*(0.01+0.002*(k+c)))) for c in (0,1))) for n in range(96000)))
    (folder/'slots.json').write_text(json.dumps({'slots':{n:{'loop_begin':0.5,'loop_end':1.5,'gain_db':gain_db} for n in names}}))


class WindowStateTests(unittest.TestCase):
    """F5/F7 through the product loop of mk5_boot_flow_cli.cpp (the visual stage the game window drives), with the
    test window (native/tests/mk2_host_close_window.cpp: MK2_TEST_STATE=save@N,load@M) and a silent PCM sink: the slot
    under saves/mk1/<program sha>/, a load from memory, a load of that file by a new session, in both editions, and a
    Remastered slot refused with other music tracks. Each session ends at the window close and writes its CMOS."""
    @unittest.skipUnless((ROOT/'roms/mk1').is_dir(),'requires authenticated ROMs')
    def test_live_loop_saves_loads_and_reloads_the_slot_in_a_new_session(self):
        from tools.setup import mk1
        mk1.inc_dir();seed=mk1.seed_path().resolve()
        objects=json.loads((ROOT/'tools/mk1/runtime-inputs.json').read_text('utf-8'))['objects']
        with q.scratch_tree() as (scratch,cleanup):
            srcs=[ROOT/p for p in objects if Path(p).stem not in ('mk5_window','mk5_audio_output')]
            srcs+=[ROOT/'native/tests/mk2_host_close_window.cpp',ROOT/'native/tests/mk2_test_audio_sink.cpp']
            exe,_=routes.build(scratch,srcs)
            write_tracks(scratch/'tracks',0);write_tracks(scratch/'other-tracks',-1)
            env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH'],'TEMP':str(scratch),'TMP':str(scratch)}
            runs=[]
            def session(plan,samples,tracks=None):
                runs.append(plan)
                extra={'MK1_MUSIC_MODE':'remastered','MK1_MUSIC_DIRECTORY':str(scratch/tracks)}if tracks else{'MK1_MUSIC_MODE':'original'}
                dsw=[a for prefix in ('','boot-','task-','body-','main-') for a in (f'--{prefix}dsw-word','65279')]
                dsw+=[a for prefix in ('','body-','active-') for a in (f'--{prefix}irq-in01','0xffffffff',f'--{prefix}irq-in2-dsw','4278190079')]
                r=q.command([exe,'--roms',ROOT/'roms','--stage','visual','--window-frames','0','--irq-pending','0x400',
                             '--raster-next-line','1','--raster-quanta','6325','--body-sound-status-byte','128',*dsw,
                             '--cmos-input',seed,'--cmos-output',scratch/f'cmos-pending-{len(runs)}.bin'],scratch,cwd=scratch,timeout=600,
                            output_limit=1<<20,env=dict(env,MK2_TEST_STATE=plan,MK2_TEST_CLOSE_AFTER_SAMPLES=str(samples),**extra))
                out=r['stdout'];game=next((json.loads(l) for l in out.splitlines() if l.startswith('{"scope":"mk5-visual"')),None)
                self.assertTrue(r['passed'] and game and game['stop']=='window-closed' and game['cmos_saved'],out[-1500:])
                return out
            for name,tracks in (('slot1.state',None),('slot1-remastered.state','tracks')):
                first=session('save@40,load@80',120,tracks)
                self.assertIn('MK1 state saved: saves/mk1/',first);self.assertIn('MK1 state loaded from memory',first)
                slot=next((scratch/'saves/mk1').glob('*/'+name));self.assertGreater(slot.stat().st_size,1<<20)
                second=session('load@10',60,tracks)
                self.assertIn('MK1 state loaded from saves/mk1/',second);self.assertNotIn('not loaded',second)
            retracked=session('load@10',60,'other-tracks')
            self.assertIn('MK1 save state not loaded: MK1 save state was made with other music tracks',retracked)
        self.assertFalse(cleanup['exists_after'])


if __name__=='__main__':unittest.main()
