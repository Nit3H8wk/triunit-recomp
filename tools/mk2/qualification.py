"""Run an explicit legal-flow matrix; missing routes remain incomplete."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import package_native as package,replay,replay_state,batch_reference,static_batch
from tools.quality import run as q

GROUPS={'campaign','finishers','secrets'}
DIAGNOSTICS=replay.DIAGNOSTIC_PATHS
MEMORIES=replay_state.BOARD_FILES


def validate_matrix(data):
    if data.get('format')!='MK2_QUALIFICATION_MATRIX_V1' or not isinstance(data.get('requirements'),list)or not data['requirements']:
        raise ValueError('Invalid qualification matrix')
    seen=set()
    for row in data['requirements']:
        if not isinstance(row,dict)or not isinstance(row.get('id'),str)or not row['id']or row['id']in seen:
            raise ValueError('Duplicate or invalid requirement')
        seen.add(row['id'])
        if row.get('group')not in GROUPS or not isinstance(row.get('context'),dict)or not row['context']:
            raise ValueError('Missing requirement context/group')
        if row.get('status')=='not_run':
            if not row.get('reason'):raise ValueError('Missing unresolved route reason')
            continue
        if row.get('status')!='ready' or not isinstance(row.get('recipe'),str)or not row['recipe']:
            raise ValueError('Missing legal recipe')
        proof=row.get('recognition')
        if not isinstance(proof,dict)or not proof.get('path')or not re.fullmatch('[0-9a-f]{64}',proof.get('sha256','')):
            raise ValueError('Missing Original gate/desfecho recognition evidence')
        if not re.fullmatch('[0-9a-f]{64}',row.get('recipe_sha256','')):raise ValueError('Unbound recipe')
        if row['group']=='finishers'and not {'fighter','role','player','orientation','opponent','stage'}<=row['context'].keys():
            raise ValueError('Missing finisher context')


def capture_contract(path):
    capture=replay.read_capture(path.read_text())
    if not capture.get('end_cycles'):raise ValueError('Qualification requires a recipe with an explicit observation horizon')
    return {'input_sha256':q.sha(path),'initial_cmos_sha256':capture['cmos_sha256'],
            'input_transitions':len(capture['inputs']),'requested_cycles':capture['end_cycles'],
            'snapshot_frames':capture['snapshot_frames'],'recipe_end_frame':capture['recipe_end_frame']}


def _bound_scene(proof,recipe_path,input_sha256):
    if not isinstance(proof,dict)or not isinstance(proof.get('fixtures'),dict)or not isinstance(proof.get('cases'),list):return False
    fixtures={name.replace('\\','/'):digest for name,digest in proof.get('fixtures',{}).items()}
    return (proof.get('passed')is True and fixtures.get(recipe_path.replace('\\','/'))==input_sha256 and
            len([row for row in proof.get('cases',[])if row.get('input_sha256')==input_sha256])==1)


def _run_passed(row):
    return (row.get('passed')is True and row.get('timed_out')is False and row.get('exit_code')==0 and
            row.get('discarded_output_bytes')==0 and row.get('owned_job_empty')is True)


def _same_digest(row):
    a=row.get('native_sha256');b=row.get('original_sha256')
    return isinstance(a,str)and re.fullmatch('[0-9a-f]{64}',a)is not None and a==b


def _batch_matches(receipt, build):
    if build is None:
        return 'static_batch' not in receipt
    try:
        batch = receipt['static_batch']
        scan_fields = ('program_sha256', 'decoder_sha256', 'decoder_inputs', 'compiler_sha256')
        harness = hashlib.sha256(replay.recovery_source(audio=True).encode('utf8')).hexdigest()
        return (
            build['format'] == 'MK2_L31_STATIC_BATCH_V1' and build['built'] is True
            and build['build']['passed'] is True
            and re.fullmatch('[0-9a-f]{64}', build['executable_sha256']) is not None
            and re.fullmatch('[0-9a-f]{64}', batch['replay_executable_sha256']) is not None
            and receipt['generated_harness_sha256'] == harness
            and _run_passed(receipt['build']) and receipt['build']['object_cleanup']['exists_after'] is False
            and receipt['cleanup']['exists_after'] is False
            and batch['native_compile_contract'] == build['native_compile_contract'] == static_batch.native_compile_contract()
            and receipt['sources'] == build['runtime_inputs']
            and receipt['roms'] == batch['roms'] == build['roms']
            and bool(build['translator_inputs']) and batch['translator_inputs'] == build['translator_inputs']
            and bool(build['tms']['source_sha256']) and batch['tms']['source_sha256'] == build['tms']['source_sha256']
            and re.fullmatch('[0-9a-f]{64}', build['dcs']['source_sha256']) is not None
            and batch['dcs']['source_sha256'] == build['dcs']['source_sha256']
            and all(batch['aligned_scan'][key] == build['aligned_scan'][key] for key in scan_fields)
        )
    except (KeyError, TypeError):
        return False


def trajectory_verified(receipt,expected,core_sha256,*,static_build=None):
    """Validate one complete case, regardless of unrelated case failures."""
    if not isinstance(expected,dict)or not isinstance(receipt,dict)or receipt.get('error')or receipt.get('sources',{}).get('runtime_sources_sha256')!=core_sha256:return False
    if not _batch_matches(receipt,static_build):return False
    if receipt.get('diagnostic_inputs')!={p:q.sha(q.ROOT/p)for p in DIAGNOSTICS}:return False
    rows=[row for row in receipt.get('cases',[])if row.get('log_sha256')==expected['input_sha256']]
    if len(rows)!=1:return False
    try:
        row=rows[0];native=row['native'];original=row['original'];trip=row['roundtrip']
        if static_build is not None and row['cleanup']['exists_after'] is not False:return False
        if (row['requested_cycles']!=expected['requested_cycles']or row['initial_cmos_sha256']!=expected['initial_cmos_sha256']or
            row['input_transitions']!=expected['input_transitions']or row['snapshot_frames_requested']!=expected['snapshot_frames']):return False
        if not all(_run_passed(item)for item in (row['execution'],original['execution'],trip['execution'])):return False
        cycles=native['cycles'];cpu=native['cpu34']
        if (type(cycles)is not int or not expected['requested_cycles']<=cycles<=expected['requested_cycles']+2000000 or
            native['passed']is not True or len(cpu)!=34 or any(type(v)is not int for v in cpu)or
            cpu[0]!=native['pc']or cpu[2]!=cycles or native['frames']!=cycles*16//1827925 or
            native['frames']<expected['recipe_end_frame']):return False
        if (original['passed']is not True or original['mame_sha256']!=batch_reference.MAME_SHA or
            original['cpu34_equal']is not True or original['observed_cpu34']!=[cpu]):return False
        if set(original['memories'])!=set(MEMORIES):return False
        for name,size in MEMORIES.items():
            item=original['memories'][name]
            if (item.get('passed')is not True or item.get('bytes')!=size or item.get('native_bytes')!=size or
                item.get('original_bytes')!=size or not _same_digest(item)):return False
        if original['raster'].get('passed')is not True or original['raster'].get('pixels')!=101600 or not _same_digest(original['raster']):return False
        rasters=original['sampled_rasters']
        if [item['frame']for item in rasters]!=expected['snapshot_frames']or any(item.get('passed')is not True or item.get('pixels')!=101600 or not _same_digest(item)for item in rasters):return False
        dac=(cycles*16//2000000)*625+1;speaker=(dac-1)*48000//31250+1
        audio=original['audio']
        if native['DAC_samples']!=dac or audio.get('passed')is not True:return False
        for name,count,unequal in (('DAC',dac,'unequal_float32_bits'),('speaker',speaker,'unequal_float32_bits'),('PCM16',speaker,'unequal_samples')):
            if audio[name].get('samples_compared')!=count or audio[name].get(unequal)!=0:return False
        dsp=original['dsp_terminal']
        if dsp.get('passed')is not True or set(dsp['files'])!=set(replay_state.FILES):return False
        for name,size in replay_state.FILES.items():
            item=dsp['files'][name]
            if (item.get('passed')is not True or item.get('expected_bytes')!=size or item.get('native_bytes')!=size or
                item.get('original_bytes')!=size or not _same_digest(item)):return False
        sizes={**MEMORIES,**replay_state.FILES,'last-frame.ppm':304815,'native-source.bin':dac*4,
               'native-speaker.bin':speaker*4,'native-pcm16.bin':speaker*2,
               **{f'frame-{frame}.rgb':304800 for frame in expected['snapshot_frames']}}
        if (trip.get('passed')is not True or trip.get('cpu34_equal')is not True or trip.get('captured_cmos_equal')is not True or
            set(trip['files'])!=set(sizes)):return False
        return all(trip['files'][name].get('passed')is True and trip['files'][name].get('bytes')==size for name,size in sizes.items())
    except (KeyError,TypeError,ValueError):return False


def recognition_verified(proof,requirement,expected):
    """Legacy sealed trajectories remain provenance, not implicit scene/context proof."""
    if not isinstance(requirement,dict)or not isinstance(expected,dict):return False
    if any(not isinstance(requirement.get(key),str)or not requirement[key]for key in ('expected_outcome','continuation_kind')):return False
    if proof.get('format')!='MK2_ORIGINAL_RECOGNITION_V1'or not _bound_scene(proof,requirement['recipe'],expected['input_sha256']):return False
    scene=next(row for row in proof['cases']if row.get('input_sha256')==expected['input_sha256'])
    acceptance=scene.get('visual_acceptance',{});continuation=scene.get('continuation',{});frames=scene.get('scene_frames',[])
    return (acceptance.get('accepted')is True and bool(acceptance.get('basis'))and scene.get('context')==requirement['context']and
            scene.get('observed_outcome')==requirement.get('expected_outcome')and bool(frames)and
            all(type(frame)is int and frame in expected['snapshot_frames']for frame in frames)and
            continuation.get('observed')is True and continuation.get('kind')==requirement.get('continuation_kind')and
            continuation.get('frame')in expected['snapshot_frames']and continuation['frame']>=max(frames))


def qualify(matrix_path,*,report_path,group=None,static_build_path=None,replay_path=None):
    if report_path.exists():raise ValueError('Preserve previous qualification receipt')
    report_path.parent.mkdir(parents=True,exist_ok=True)
    matrix=json.loads(matrix_path.read_text());validate_matrix(matrix)
    selected=[row for row in matrix['requirements']if group is None or row['group']==group]
    if not selected:raise ValueError('Empty qualification selection')
    report={'passed':False,'scope':'Declared recipes and Original recognition evidence; finite trajectory comparisons are not universal equivalence.',
            'matrix_sha256':q.sha(matrix_path),'requirements':[]}
    with q.scratch_tree()as(scratch,cleanup):
        report['cleanup']=cleanup;env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH']}
        report['sources']=package.identities(scratch,env)
    static_build = None
    if static_build_path is not None:
        static_build_path = static_build_path.absolute()
        package.unlinked(static_build_path)
        data = static_build_path.read_bytes()
        static_build = json.loads(data)
        if (static_build.get('format') != 'MK2_L31_STATIC_BATCH_V1' or static_build.get('built') is not True
                or static_build.get('build', {}).get('passed') is not True or static_build.get('error')):
            raise ValueError('Static candidate receipt has no successful build')
        executable = Path(static_build['executable']).absolute()
        package.unlinked(executable)
        executable = executable.resolve(strict=True)
        if (static_build['runtime_inputs'] != report['sources'] or not executable.is_relative_to(q.ROOT)
                or q.sha(executable) != static_build['executable_sha256']
                or static_build.get('native_compile_contract') != static_batch.native_compile_contract()):
            raise ValueError('Static candidate identity differs')
        report['static_candidate'] = {'build_receipt_sha256': hashlib.sha256(data).hexdigest(),
                                      'executable_sha256': static_build['executable_sha256'],
                                      'comparison_scope': 'Instrumented replay executable with matching generated and runtime sources'}
    core=report['sources']['runtime_sources_sha256'];ready=[]
    for row in selected:
        result={'id':row['id'],'status':'not_run','context':row['context']};report['requirements'].append(result)
        if row['status']=='not_run':result['reason']=row['reason'];continue
        recipe=(q.ROOT/row['recipe']).resolve();proof=(q.ROOT/row['recognition']['path']).resolve()
        if not recipe.is_relative_to(q.ROOT)or not proof.is_relative_to(q.ROOT):raise ValueError('Evidence outside project')
        if q.sha(recipe)!=row['recipe_sha256']or q.sha(proof)!=row['recognition']['sha256']:
            raise ValueError('Recipe or recognition evidence changed')
        scene=json.loads(proof.read_text())
        if not _bound_scene(scene,row['recipe'],row['recipe_sha256']):raise ValueError('Original provenance does not cover this exact recipe')
        expected=capture_contract(recipe)
        ready.append((row,result,recipe,expected,recognition_verified(scene,row,expected)))
    if ready:
        if q.sha(batch_reference.MAME)!=batch_reference.MAME_SHA:raise ValueError('Original executable identity differs')
        combined=replay_path.absolute() if replay_path is not None else report_path.with_name(report_path.stem+'-replay.json')
        if replay_path is None:
            if combined.exists():raise ValueError('Existing replay requires explicit --replay-receipt')
            command=[sys.executable,'-B','-m','tools.mk2.replay',*[str(item[2])for item in ready],
                     '--original','--roundtrip','--report',str(combined)]
            if static_build is not None:
                command.append('--static-batch')
            process=subprocess.run(command,cwd=q.ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
            report['runner_exit_code']=process.returncode;report['runner_error_tail']=process.stderr[-2000:]
        else:
            package.unlinked(combined)
            if not combined.is_file() or not combined.resolve().is_relative_to(q.ROOT):
                raise ValueError('Selected replay receipt must be a project file')
        if not combined.is_file():
            report['error']='Replay subprocess did not produce a receipt'
            for _,result,_,_,_ in ready:result['status']='runner_failed'
        else:
            data=combined.read_bytes()
            receipt=json.loads(data);report['replay_sha256']=hashlib.sha256(data).hexdigest()
            if static_build is not None and _batch_matches(receipt,static_build):
                report['static_candidate']['replay_harness'] = {
                    'executable_sha256': receipt['static_batch']['replay_executable_sha256'],
                    'source_sha256': receipt['generated_harness_sha256'],
                }
            for row,result,_,expected,recognized in ready:
                matched=trajectory_verified(receipt,expected,core,static_build=static_build)
                result['status']=('verified'if recognized else'recognition_incomplete')if matched else'frontier_or_mismatch'
                result['trajectory_verified']=matched;result['recognition_verified']=recognized
                result['recognition']=row['recognition']
            if q.sha(combined)!=report['replay_sha256']:report['error']='Replay receipt changed during qualification'
        for row,_,recipe,_,_ in ready:
            if q.sha(recipe)!=row['recipe_sha256']or q.sha(q.ROOT/row['recognition']['path'])!=row['recognition']['sha256']:
                report['error']='Recipe or recognition changed during qualification'
    if q.sha(matrix_path)!=report['matrix_sha256']:report['error']='Matrix changed during qualification'
    if static_build is not None and (q.sha(static_build_path) != report['static_candidate']['build_receipt_sha256']
                                     or q.sha(executable) != static_build['executable_sha256']):
        report['error'] = 'Static candidate changed during qualification'
    with q.scratch_tree()as(scratch,final_cleanup):
        env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH']}
        if package.identities(scratch,env)!=report['sources']:report['error']='Runtime sources changed during qualification'
    report['final_cleanup']=final_cleanup
    report['passed']=not report.get('error')and bool(report['requirements'])and all(row['status']=='verified'for row in report['requirements'])
    report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--matrix',type=Path,required=True);parser.add_argument('--group',choices=sorted(GROUPS))
    parser.add_argument('--static-build-receipt',type=Path,help='Bind the linked static build and a matching instrumented replay')
    parser.add_argument('--replay-receipt',type=Path,help='Use an explicit replay receipt after verifying its identity')
    parser.add_argument('--report',type=Path,required=True);args=parser.parse_args()
    report=qualify(args.matrix,report_path=args.report,group=args.group,static_build_path=args.static_build_receipt,
                   replay_path=args.replay_receipt)
    print(json.dumps({'passed':report['passed'],'counts':{state:sum(row['status']==state for row in report['requirements'])for state in ('not_run','verified','recognition_incomplete','frontier_or_mismatch','runner_failed')}},indent=2))
    return 0 if report['passed']else 1


if __name__=='__main__':raise SystemExit(main())
