"""Qualification never promotes incomplete, stale or misidentified evidence."""
from pathlib import Path
import sys
import copy
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))


class QualificationTests(unittest.TestCase):
    def test_new_output_directory_and_missing_subprocess_receipt_leave_structured_failure(self):
        import json,hashlib
        from unittest.mock import patch
        from types import SimpleNamespace
        from tools.mk2 import qualification,profile,generate_video_irq as g
        from tools.quality import run as q
        with q.scratch_tree()as(scratch,cleanup):
            recipe=scratch/'case.json';recipe.write_text(json.dumps({'format':'MK2_REPLAY_V1','timebase_hz':100000000,
                'initial_shared_active_low':0xffffffff,'factory_cmos_sha256':profile.FACTORY_SHA256,'factory_cmos_bytes':16384,
                'program_sha256':g.PROGRAM_SHA256,'request_rows':[[1,0xffffffff]],'end_frame':10}))
            sha=q.sha(recipe);proof=scratch/'proof.json';proof.write_text(json.dumps({'passed':True,
                'fixtures':{recipe.relative_to(q.ROOT).as_posix():sha},'cases':[{'input_sha256':sha}]}))
            matrix=self.matrix();matrix['requirements']=matrix['requirements'][:1];row=matrix['requirements'][0]
            row.update(recipe=recipe.relative_to(q.ROOT).as_posix(),recipe_sha256=sha,
                       recognition={'path':proof.relative_to(q.ROOT).as_posix(),'sha256':q.sha(proof)})
            mp=scratch/'matrix.json';mp.write_text(json.dumps(matrix));output=scratch/'new/deep/result.json'
            reference=scratch/'reference';reference.write_bytes(b'fixture-reference')
            def failed_child(command,**kwargs):
                self.assertTrue(Path(command[-1]).parent.is_dir())
                return SimpleNamespace(returncode=1,stderr='child failed before receipt')
            with patch.object(qualification.package,'identities',return_value={'runtime_sources_sha256':'3'*64}),\
                 patch.object(qualification.batch_reference,'MAME',reference),\
                 patch.object(qualification.batch_reference,'MAME_SHA',q.sha(reference)),\
                 patch.object(qualification.subprocess,'run',side_effect=failed_child):
                result=qualification.qualify(mp,report_path=output)
                ambient=output.with_name('ambient-replay.json')
                ambient.write_text('{}')
                with self.assertRaisesRegex(ValueError,'explicit --replay-receipt'):
                    qualification.qualify(mp,report_path=output.with_name('ambient.json'))
            self.assertFalse(result['passed']);self.assertTrue(output.is_file())
            self.assertEqual(result['error'],'Replay subprocess did not produce a receipt')
        self.assertFalse(cleanup['exists_after'])

    def test_static_build_seal_binds_the_existing_candidate_executable(self):
        import json
        from unittest.mock import patch
        from tools.mk2 import qualification, static_batch
        from tools.quality import run as q

        with q.scratch_tree() as (scratch, cleanup):
            matrix = self.matrix()
            matrix['requirements'] = matrix['requirements'][1:]
            matrix_path = scratch / 'matrix.json'
            matrix_path.write_text(json.dumps(matrix))
            binary = scratch / 'candidate.exe'
            binary.write_bytes(b'fixture AOT executable')
            sources = {'runtime_sources_sha256': '3' * 64}
            build = {'format': 'MK2_L31_STATIC_BATCH_V1', 'built': True, 'build': {'passed': True},
                     'native_compile_contract': static_batch.native_compile_contract(),
                     'runtime_inputs': sources, 'executable': str(binary), 'executable_sha256': q.sha(binary)}
            build_path = scratch / 'build.json'
            build_path.write_text(json.dumps(build))
            with patch.object(qualification.package, 'identities', return_value=sources):
                result = qualification.qualify(matrix_path, report_path=scratch / 'report.json',
                                               static_build_path=build_path)
                self.assertEqual(result['static_candidate']['build_receipt_sha256'], q.sha(build_path))
                self.assertEqual(result['static_candidate']['executable_sha256'], q.sha(binary))
                self.assertIn('instrumented', result['static_candidate']['comparison_scope'].lower())
                binary.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'Static candidate identity differs'):
                    qualification.qualify(matrix_path, report_path=scratch / 'changed.json',
                                          static_build_path=build_path)
        self.assertFalse(cleanup['exists_after'])

    def test_original_recognition_requires_exact_recipe_and_observed_scene(self):
        from tools.mk2.qualification import recognition_verified
        sha='1'*64;path='tools/mk2/finisher_replays/case00.json'
        proof={'passed':True,'fixtures':{path:sha},'cases':[{'input_sha256':sha}]}
        self.assertFalse(recognition_verified(proof,path,sha))
        for bad in ({'passed':True},{**proof,'passed':False},{**proof,'fixtures':{path:'2'*64}},
                    {**proof,'cases':[]},{**proof,'cases':[{'input_sha256':'2'*64}]}):
            with self.subTest(proof=bad):self.assertFalse(recognition_verified(bad,path,sha))

    def matrix(self):
        return {'format':'MK2_QUALIFICATION_MATRIX_V1','requirements':[
            {'id':'f01-finisher1','group':'finishers','status':'ready','recipe':'tools/mk2/finisher_replays/case00.json',
             'recipe_sha256':'1'*64,'context':{'fighter':'f01','role':'apply','player':1,'orientation':'right','opponent':'f04','stage':0},
             'recognition':{'path':'receipt.json','sha256':'2'*64}},
            {'id':'f01-campaign','group':'campaign','status':'not_run','recipe':None,'context':{'fighter':'f01'},'reason':'Legal complete route not captured'}]}

    def test_schema_rejects_duplicates_unbound_inputs_and_fake_ready_cases(self):
        from tools.mk2.qualification import validate_matrix
        validate_matrix(self.matrix())
        for change in ('duplicate','missing_recipe','missing_recognition','missing_context','notrun_reason','unknown_group'):
            bad=self.matrix();row=bad['requirements'][0]
            if change=='duplicate':bad['requirements'].append(copy.deepcopy(row))
            if change=='missing_recipe':row['recipe']=None
            if change=='missing_recognition':row.pop('recognition')
            if change=='missing_context':row['context'].pop('role')
            if change=='notrun_reason':bad['requirements'][1].pop('reason')
            if change=='unknown_group':row['group']='anything'
            with self.subTest(change=change),self.assertRaises(ValueError):validate_matrix(bad)

    def test_trajectory_requires_original_roundtrip_and_same_core(self):
        from tools.mk2.qualification import trajectory_verified
        from tools.quality import run as q
        row={'log_sha256':'1'*64,'execution':{'passed':True},'roundtrip':{'passed':True},
             'original':{'passed':True,'dsp_terminal':{'passed':True}}}
        receipt={'passed':True,'sources':{'runtime_sources_sha256':'3'*64},'cases':[row],
                 'diagnostic_inputs':{p:q.sha(q.ROOT/p)for p in ('tools/mk2/replay.py','tools/mk2/replay_reference.py','tools/mk2/replay_audio.py','tools/mk2/dac_reference.py','tools/mk2/replay_state.py','native/tests/mk2_recovery_tests.cpp')}}
        self.assertFalse(trajectory_verified(receipt,'1'*64,'3'*64))
        for changed in ('missing','original','dsp','roundtrip','core','input','duplicate','diagnostic','missing_diagnostics'):
            bad=copy.deepcopy(receipt)
            if changed=='missing':bad['cases']=[]
            if changed in ('original','roundtrip'):bad['cases'][0][changed]['passed']=False
            if changed=='dsp':bad['cases'][0]['original'].pop('dsp_terminal')
            if changed=='core':bad['sources']['runtime_sources_sha256']='4'*64
            if changed=='input':bad['cases'][0]['log_sha256']='5'*64
            if changed=='duplicate':bad['cases'].append(copy.deepcopy(row))
            if changed=='diagnostic':bad['diagnostic_inputs']['tools/mk2/replay.py']='0'*64
            if changed=='missing_diagnostics':bad.pop('diagnostic_inputs')
            with self.subTest(changed=changed):self.assertFalse(trajectory_verified(bad,'1'*64,'3'*64))

    def test_recognition_binds_context_outcome_and_observed_continuation(self):
        from tools.mk2.qualification import recognition_verified
        context={'fighter':'f01','role':'apply','player':1,'orientation':'right','opponent':'f04','stage':0}
        requirement={'recipe':'case.json','recipe_sha256':'1'*64,'context':context,'expected_outcome':'variant-f','continuation_kind':'continue_challenge'}
        expected={'input_sha256':'1'*64,'snapshot_frames':[10,20,30]}
        scene={'input_sha256':'1'*64,'context':context,'observed_outcome':'variant-f','scene_frames':[10,20],
               'visual_acceptance':{'accepted':True,'basis':'Actual Original scene inspected'},
               'continuation':{'observed':True,'kind':'continue_challenge','frame':30}}
        proof={'format':'MK2_ORIGINAL_RECOGNITION_V1','passed':True,'fixtures':{'case.json':'1'*64},'cases':[scene]}
        self.assertTrue(recognition_verified(proof,requirement,expected))
        for change in ('rejected','no_scene','role','arena','outcome','no_continue','wrong_continue','uncaptured_continue','missing_outcome_contract','missing_continuation_contract'):
            bad=copy.deepcopy(proof);row=bad['cases'][0]
            wanted=copy.deepcopy(requirement)
            if change=='rejected':row['visual_acceptance']['accepted']=False
            if change=='no_scene':row.pop('visual_acceptance')
            if change=='role':row['context']['role']='receive'
            if change=='arena':row['context']['stage']=6
            if change=='outcome':row['observed_outcome']='normal_win'
            if change=='no_continue':row.pop('continuation')
            if change=='wrong_continue':row['continuation']['kind']='unobserved'
            if change=='uncaptured_continue':row['continuation']['frame']=99
            if change=='missing_outcome_contract':row.pop('observed_outcome');wanted.pop('expected_outcome')
            if change=='missing_continuation_contract':row['continuation'].pop('kind');wanted.pop('continuation_kind')
            with self.subTest(change=change):self.assertFalse(recognition_verified(bad,wanted,expected))


class CompleteTrajectoryTests(unittest.TestCase):
    def valid(self):
        from tools.mk2.replay import DIAGNOSTIC_PATHS
        from tools.quality import run as q
        digest='a'*64
        run={'passed':True,'timed_out':False,'exit_code':0,'discarded_output_bytes':0,'owned_job_empty':True}
        mem={'cmos.bin':16384,'ram.bin':524288,'palette.bin':65536,'vram.bin':1048576,'io.bin':56,'dma.bin':36,'shiftreg.bin':8192,'display.bin':4}
        dsp={'dsp-registers.bin':608,'dsp-pm.bin':4096,'dsp-dm.bin':1024,'dsp-external-pm.bin':8192,
             'dsp-external-dm.bin':4096,'dsp-control.bin':64,'dsp-control-raw.bin':64,'dsp-device.bin':136,'dsp-irq1.bin':2,'dcs-latches.bin':6,
             'dsp-stack.bin':108,'dsp-dac-ring.bin':131072}
        raster={'passed':True,'pixels':101600,'native_sha256':digest,'original_sha256':digest}
        cpu=[0xff805f60,0x60200030,12500022]+[0]*31
        original={'passed':True,'execution':run.copy(),'mame_sha256':'84b690dad588253139ea49ae5e3c9fcddf9df7bcd526fccd1724ec7e09120dec',
                  'cpu34_equal':True,'observed_cpu34':[cpu.copy()],
                  'memories':{name:{'passed':True,'bytes':size,'native_bytes':size,'original_bytes':size,'native_sha256':digest,'original_sha256':digest}for name,size in mem.items()},
                  'raster':raster.copy(),'sampled_rasters':[dict(raster,frame=n)for n in (1,100)],
                  'audio':{'passed':True,'DAC':{'samples_compared':62501,'unequal_float32_bits':0},
                           'speaker':{'samples_compared':96001,'unequal_float32_bits':0},'PCM16':{'samples_compared':96001,'unequal_samples':0}},
                  'dsp_terminal':{'passed':True,'files':{name:{'passed':True,'expected_bytes':size,'native_bytes':size,'original_bytes':size,'native_sha256':digest,'original_sha256':digest}for name,size in dsp.items()}}}
        sizes={**mem,'last-frame.ppm':304815,'native-source.bin':250004,'native-speaker.bin':384004,'native-pcm16.bin':192002,
               'frame-1.rgb':304800,'frame-100.rgb':304800,**dsp}
        row={'log_sha256':'1'*64,'initial_cmos_sha256':'2'*64,'input_transitions':2,'requested_cycles':12500000,'snapshot_frames_requested':[1,100],
             'execution':run.copy(),'native':{'passed':True,'pc':cpu[0],'cycles':cpu[2],'frames':109,'DAC_samples':62501,'cpu34':cpu.copy()},
             'original':original,'roundtrip':{'passed':True,'execution':run.copy(),'captured_cmos_equal':True,'cpu34_equal':True,
                                             'files':{name:{'passed':True,'bytes':size}for name,size in sizes.items()}}}
        receipt={'passed':True,'sources':{'runtime_sources_sha256':'3'*64},'cases':[row],
                 'diagnostic_inputs':{p:q.sha(q.ROOT/p)for p in DIAGNOSTIC_PATHS}}
        expected={'input_sha256':'1'*64,'initial_cmos_sha256':'2'*64,'input_transitions':2,'requested_cycles':12500000,'snapshot_frames':[1,100],'recipe_end_frame':100}
        return receipt,expected

    def test_exact_contract_passes_even_if_another_case_in_the_batch_failed(self):
        from tools.mk2.qualification import trajectory_verified
        receipt,expected=self.valid();receipt['passed']=False;receipt['cases'].append({'log_sha256':'9'*64,'execution':{'passed':False}})
        self.assertTrue(trajectory_verified(receipt,expected,'3'*64))

    def test_terminal_tms_shift_register_and_display_are_required(self):
        from tools.mk2 import qualification
        self.assertEqual(qualification.MEMORIES['shiftreg.bin'], 8192)
        self.assertEqual(qualification.MEMORIES['display.bin'], 4)
        for name in ('shiftreg.bin', 'display.bin'):
            receipt, expected = self.valid()
            case = receipt['cases'][0]
            with self.subTest(name=name):
                self.assertTrue(qualification.trajectory_verified(receipt, expected, '3' * 64))
                case['original']['memories'][name]['original_sha256'] = '0' * 64
                self.assertFalse(qualification.trajectory_verified(receipt, expected, '3' * 64))

    def test_static_batch_requires_the_built_tms_dcs_and_runtime_identities(self):
        import hashlib
        from tools.mk2 import replay, static_batch
        from tools.mk2.qualification import trajectory_verified
        receipt, expected = self.valid()
        unit = '7' * 64
        scan = {name: '6' * 64 for name in ('program_sha256', 'decoder_sha256', 'compiler_sha256')}
        scan['decoder_inputs'] = {'decoder.cpp': '5' * 64}
        compiled = {
            'native_compile_contract': static_batch.native_compile_contract(),
            'translator_inputs': {'static_batch.py': '1' * 64},
            'roms': {'program': '2' * 64},
            'aligned_scan': scan,
            'tms': {'source_sha256': {'mk2_tms.cpp': unit}},
            'dcs': {'source_sha256': '8' * 64},
        }
        build = {**copy.deepcopy(compiled), 'format': 'MK2_L31_STATIC_BATCH_V1',
                 'built': True, 'build': {'passed': True}, 'executable_sha256': '4' * 64,
                 'runtime_inputs': copy.deepcopy(receipt['sources'])}
        receipt['roms'] = copy.deepcopy(compiled['roms'])
        receipt['static_batch'] = {**compiled, 'replay_executable_sha256': '9' * 64}
        receipt['generated_harness_sha256'] = hashlib.sha256(replay.recovery_source(audio=True).encode('utf8')).hexdigest()
        receipt['build'] = {**receipt['cases'][0]['execution'], 'object_cleanup': {'exists_after':False}}
        receipt['cleanup'] = {'exists_after':False}
        receipt['cases'][0]['cleanup'] = {'exists_after':False}
        self.assertFalse(trajectory_verified(receipt, expected, '3' * 64))
        self.assertTrue(trajectory_verified(receipt, expected, '3' * 64, static_build=build))
        for change in ('harness','flags','build','objects','case_cleanup'):
            bad=copy.deepcopy(receipt)
            if change=='harness':bad['generated_harness_sha256']='0'*64
            if change=='flags':bad['static_batch']['native_compile_contract']['compile_flags'].append('-ffast-math')
            if change=='build':bad['build']['passed']=False
            if change=='objects':bad['build']['object_cleanup']['exists_after']=True
            if change=='case_cleanup':bad['cases'][0]['cleanup']['exists_after']=True
            with self.subTest(change=change):
                self.assertFalse(trajectory_verified(bad,expected,'3'*64,static_build=build))
        for field, key in (('tms', 'source_sha256'), ('dcs', 'source_sha256'),
                           ('translator_inputs', 'static_batch.py'), ('roms', 'program'),
                           ('aligned_scan', 'program_sha256')):
            stale = copy.deepcopy(receipt)
            stale['static_batch'][field][key] = '0' * 64
            with self.subTest(field=field):
                self.assertFalse(trajectory_verified(stale, expected, '3' * 64, static_build=build))

    def test_incomplete_wrong_horizon_or_wrong_reference_cannot_pass(self):
        from tools.mk2.qualification import trajectory_verified
        for change in ('horizon','snapshots','cmos','memory','audio','IRQ','CPU','reference','roundtrip','diagnostic','root_error','timed_out'):
            receipt,expected=self.valid();row=receipt['cases'][0]
            if change=='horizon':row['requested_cycles']=125000
            if change=='snapshots':row['snapshot_frames_requested']=[1];row['original']['sampled_rasters']=row['original']['sampled_rasters'][:1]
            if change=='cmos':row['initial_cmos_sha256']='4'*64
            if change=='memory':row['original']['memories'].pop('palette.bin')
            if change=='audio':row['original']['audio']['DAC']['samples_compared']-=1
            if change=='IRQ':row['original']['dsp_terminal']['files'].pop('dsp-irq1.bin')
            if change=='CPU':row['native']['cpu34'][5]=1
            if change=='reference':row['original']['mame_sha256']='0'*64
            if change=='roundtrip':row['roundtrip']['files'].pop('dcs-latches.bin')
            if change=='diagnostic':receipt['diagnostic_inputs']['tools/mk2/batch_reference.py']='0'*64
            if change=='root_error':receipt['error']='Source changed'
            if change=='timed_out':row['execution']['timed_out']=True
            with self.subTest(change=change):self.assertFalse(trajectory_verified(receipt,expected,'3'*64))


if __name__=='__main__':unittest.main()
