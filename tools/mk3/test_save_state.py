"""MK3 save states (F5/F7) through the live loop of mk3.exe (native/mk3/mk3_preview_main.cpp), headless, with the legal
round start tape (tools/mk3/fight_route.tape) as the inputs. In each edition (Original; Remastered with its DMA layers):
- save at frame S, digest the state at frame E, load (from memory) and replay to E: every frame line of S+1..E (raster,
  previous frame, palette, machine time and cycle, host PCM, Remastered composite) and the state digest at E identical;
- a new process loads the slot file at an earlier frame and replays the same frames;
- refusals: a slot of the other edition and a damaged slot leave the session running.
--state-test drives the same request queue that F5/F7 of the window feed. No window, GPU or audio device.
"""
from pathlib import Path
import shutil,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3 import preview

ROOT=preview.ROOT
TAPE=ROOT/'tools/mk3/fight_route.tape'
S,E,LOAD_AT=1000,2560,5   # across the tape's inputs (frames 1094-1646) and the round start (DCS 0x233D near frame 2480)


class SaveStateTests(unittest.TestCase):
    @unittest.skipUnless((ROOT/'roms/mk3').is_dir(),'requires authenticated ROMs')
    def test_load_replays_every_frame_PCM_and_state_in_and_across_sessions(self):
        with preview.Preview() as p:
            slots={}
            for edition in ('original','remastered'):
                cwd=p.temp/edition;cwd.mkdir()
                run=lambda plan,frames=E+1,where=cwd:p.run('--hashes','--tape',TAPE,'--edition',edition,'--frames',frames,
                                                         '--state-test',plan,cwd=where,timeout=1800)
                a=run(f'save@{S},hash@{E},load@{E},hash@{E}')
                states=[(s['save_state'],s.get('frame'),s.get('from')) for s in a['states']]
                self.assertEqual(states,[('saved',S,None),('hash',E,None),('loaded',S,'memory'),('hash',E,None)],a['states'])
                self.assertTrue(a['states'][0]['file'])
                self.assertEqual(a['states'][1]['sha256'],a['states'][3]['sha256'],'state at E differs after the load')
                frames=a['frames'];self.assertEqual([f['frame'] for f in frames],[*range(1,E+1),*range(S+1,E+2)])
                first,replay=frames[S:E],frames[E:2*E-S]
                self.assertEqual(first,replay,'load changed a frame line')
                self.assertTrue(all('pcm' in f for f in first) and len({f['pcm'] for f in first})>1)
                if edition=='remastered':self.assertTrue(any(f.get('rm','0'*16)!='0'*16 for f in first),'no Remastered composite in range')
                slot=next((cwd/'saves/mk3').glob('*/'+('slot1-remastered.state' if edition=='remastered' else 'slot1.state')))
                self.assertGreater(slot.stat().st_size,1<<20);slots[edition]=slot
                b=run(f'load@{LOAD_AT}')
                self.assertEqual([(s['save_state'],s.get('from')) for s in b['states']],[('loaded','file')],b['states'])
                self.assertEqual(b['frames'][LOAD_AT:LOAD_AT+E-S],first,'a new session replayed other frames')
                print(edition,'state bytes',a['states'][0]['bytes'],'frames compared',2*(E-S))
            # The Original slot offered to a Remastered session, then a damaged Remastered slot.
            cross=p.temp/'cross';target=cross/slots['remastered'].relative_to(p.temp/'remastered')
            target.parent.mkdir(parents=True);shutil.copyfile(slots['original'],target)
            refused=lambda:p.run('--hashes','--edition','remastered','--frames',LOAD_AT+2,'--state-test',f'load@{LOAD_AT}',cwd=cross)['states']
            self.assertEqual(refused(),[{'save_state':'refused','error':'MK3 save state belongs to another edition'}])
            data=bytearray(slots['remastered'].read_bytes());data[-1]^=1;target.write_bytes(data)
            self.assertEqual(refused(),[{'save_state':'refused','error':'MK3 save state payload is damaged'}])


if __name__=='__main__':unittest.main()
