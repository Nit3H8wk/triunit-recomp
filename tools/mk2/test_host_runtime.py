"""Replay actual host requests through the bounded native experiment, with compact output."""
import json
import os
from pathlib import Path
import sys
import unittest
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import run,generate_first_fight
from tools.quality import run as quality


class HostRuntimeTests(unittest.TestCase):
    @unittest.skipUnless((quality.ROOT/'roms/mk2').is_dir(),'requires authenticated MK2 ROMs')
    def test_native_host_neutral_and_original_actions(self):
        run.verify_roms(quality.ROOT/'roms/mk2')
        sources=[p for p in run.SOURCES if p!='native/tests/mk2_foundation_tests.cpp']
        sources+=['native/tests/mk2_host_controls_tests.cpp']
        inputs={p:quality.sha(__import__('tools.setup.mk2',fromlist=['source']).source(p)) for p in dict.fromkeys(sources+run.HEADERS+[
            'tools/mk2/first_fight_path.json','tools/mk2/test_host_runtime.py'])}
        env={'PATH':str(quality.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH','')}
        receipt={'scope':'finite-native-host-replays','passed':False,'sources':inputs,'replays':{}}
        stage=quality.ROOT/'build/native/mk2-held-controls-20261101';stage.mkdir(parents=True,exist_ok=True)
        receipt_path=stage/('native-replays-'+uuid.uuid4().hex+'.json')
        try:
            with quality.scratch_tree() as (scratch,cleanup):
                receipt['cleanup']=cleanup
                exe=scratch/'host.exe'
                build=quality.command([quality.DEFAULT_CC,'-std=c++17','-O1','-Wall','-Wextra','-Werror',
                    '-Wno-unused-parameter','-Wno-missing-field-initializers',
                    '-I'+str(quality.ROOT/'native/include'),*[quality.ROOT/p for p in sources],
                    '-lbcrypt','-o',exe],scratch,timeout=240,env=env)
                receipt['build']=quality.compact(build)
                self.assertTrue(build['passed'],build['stdout'])
                for mode in ('neutral','high_punch','low_punch','right','prolonged_neutral','chunked_neutral',
                             'right_high_punch_held','right_low_punch_held'):
                    result=quality.command([exe,quality.ROOT/'roms/mk2',mode],scratch,timeout=180,env=env)
                    receipt['replays'][mode]={'execution':quality.compact(result)}
                    self.assertTrue(result['passed'],result)
                    observed=json.loads(result['stdout'])
                    receipt['replays'][mode]['native']=observed
                    prolonged=mode in ('prolonged_neutral','chunked_neutral')
                    measured=(generate_first_fight.measured['windows'][-2] if prolonged else
                              generate_first_fight.interval(86) if mode=='neutral' else
                              generate_first_fight.high_punch_interval() if mode=='high_punch' else
                              generate_first_fight.measured['control_branches'][mode])
                    self.assertEqual(__import__('tools.mk2.oracle_digest',fromlist=['cpu34_digest']).cpu34_digest(observed['cpu34']),measured['end_cpu34_sha256'])
                    expected_instructions=(sum(row['cpu_rows'] for row in generate_first_fight.measured['windows'][1:-1])
                                           if prolonged else measured['cpu_rows'])
                    self.assertEqual(observed['instructions'],expected_instructions)
                    latches=[row for row in observed['events'] if row[3]==7]
                    if mode in ('neutral','prolonged_neutral','chunked_neutral'):self.assertEqual(latches,[])
                    else:
                        held=mode.endswith('_held')
                        pressed=(0xffe7 if mode=='right_high_punch_held' else
                                 0xfff7 if mode in ('right','right_low_punch_held') else
                                 0xffef if mode=='high_punch' else 0xffff)
                        ports=[pressed,0xffff,0xfffe if mode in ('low_punch','right_low_punch_held') else 0xffff]
                        packed=ports[0]|ports[1]<<16|ports[2]<<32
                        self.assertEqual(latches,[[2052759775,packed,packed,7],
                                                  [2111253375 if held else 2060071475,0xffffffffffff,0xffffffffffff,7]])
                        if held:self.assertEqual(observed['chunks'],2)
                self.assertEqual(inputs,{p:quality.sha(__import__('tools.setup.mk2',fromlist=['source']).source(p)) for p in inputs})
            self.assertFalse(cleanup['exists_after'])
            receipt['passed']=True
        finally:
            receipt_path.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':unittest.main()
