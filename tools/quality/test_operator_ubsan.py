"""Focused UBSan trap gate for operator settings; all binaries/profiles are temporary."""
import json
import os
from pathlib import Path
import re
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.launcher_backend_build import arguments as backend_arguments


def dependencies(sources):
    found=set()
    pending=[Path(source) for source in sources]
    roots=[q.ROOT/'native/include',q.ROOT/'native/mk2',q.ROOT/'native/launcher']
    while pending:
        path=pending.pop().resolve()
        if path in found:continue
        found.add(path)
        for name in re.findall(r'^\s*#\s*include\s*"([^"]+)"',path.read_text(encoding='utf-8'),re.M):
            candidate=next((directory/name for directory in [path.parent,*roots] if (directory/name).is_file()),None)
            if candidate is not None:pending.append(candidate)
    return found


def main():
    flags=['-std=c++17','-O1','-g','-fno-omit-frame-pointer','-fsanitize=undefined',
           '-fsanitize-undefined-trap-on-error','-fno-sanitize=vptr','-fno-sanitize-recover=all',
           '-Wall','-Wextra','-Werror',*['-I'+str(q.ROOT/path) for path in ('native/include','native/mk2','native/launcher')]]
    receipt={'passed':False,'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
             'scope':'Focused operator/UI/storage/output-volume contracts; not the whole game runtime',
             'certifies_arcade_fidelity':False,'certifies_no_memory_leaks':False,'sanitizer':'undefined-trap',
             'flags':flags,'runner_sha256':q.sha(Path(__file__)),'compiler_path':str(q.DEFAULT_CC),
             'compiler_sha256':q.sha(q.DEFAULT_CC),'cases':[]}
    try:
        with q.scratch_tree() as (scratch,cleanup):
            receipt['cleanup']=cleanup
            env=dict(os.environ,PATH=str(q.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH',''),TEMP=str(scratch),TMP=str(scratch))
            receipt['compiler']=q.compact(q.command([q.DEFAULT_CC,'--version'],scratch,cwd=q.ROOT,env=env))
            common=[q.DEFAULT_CC,*flags]
            negative=scratch/'signed-overflow.cpp'
            negative.write_text('#include <climits>\nint main(int argc,char**){volatile int n=INT_MAX;n+=argc;(void)n;return 0;}\n')
            executable=scratch/'signed-overflow.exe'
            built=q.command([*common,negative,'-o',executable],scratch,cwd=q.ROOT,env=env)
            row={'name':'signed-overflow-negative-control','build':q.compact(built),'source_sha256':q.sha(negative),'passed':False}
            if built['passed']:
                detected=q.command([executable],scratch,cwd=q.ROOT,env=env)
                row.update(run=q.compact(detected),passed=q.negative_control_detected(detected,'undefined'))
            receipt['cases'].append(row)
            if not row['passed']:raise RuntimeError('Signed-overflow trap negative control did not verify UBSan instrumentation')
            print('PASS signed-overflow trap negative control',flush=True)
            volume=scratch/'volume-helper.cpp'
            volume.write_text('''#include "mk5_audio_volume.hpp"
#include <array>
#include <iostream>
int main(){
 for(int sample=-32768;sample<=32767;++sample)for(unsigned percent:{0u,37u,50u,100u}){
  const int magnitude=(sample<0?-sample:sample)*int(percent)/100;
  if(mk5audio::ScaleVolume(int16_t(sample),percent)!=(sample<0?-magnitude:magnitude))return 1;
 }
 if(mk5audio::ParseGameVolume("")!=100||mk5audio::ParseGameVolume("0")!=0||mk5audio::ParseGameVolume("37")!=37||mk5audio::ParseGameVolume("100")!=100)return 1;
 for(const auto* invalid:{"-1","101","+50","1.5"," 37","37x","999999999999999999"}){
  bool threw=false;try{mk5audio::ParseGameVolume(invalid);}catch(const std::runtime_error&){threw=true;}
  if(!threw)return 1;
 }
 std::cout<<"PASS all65536 PCM samples at0/37/50/100 and volume parsing\\n";
}
''',encoding='utf-8')
            backend=backend_arguments(q.ROOT)
            backend_sources=[Path(argument) for argument in backend if str(argument).endswith('.cpp')]
            ui_libs=['-l'+name for name in ('d3d12','dxgi','d3dcompiler','dxguid','windowscodecs','ole32','uuid','gdi32','user32','shell32','xinput9_1_0')]
            oracle=['native/tests/mk5_operator_settings_tests.cpp',*['native/src/'+name+'.cpp' for name in
                    ('mk5_program','mk5_task_body','mk5_irq','mk5_live_video')]]
            cases=[
                ('volume-helper',[volume],[],[[]],[]),
                ('volume-real-sink',['native/tests/mk5_game_volume_sink_tests.cpp'],[],[[]],[]),
                ('raw-cmos',['native/tests/cmos_file_tests.cpp','native/mk2/mk2_profile.cpp','native/src/mk5_program.cpp'],['-municode','-lbcrypt'],[[scratch/'raw-profile']],[]),
                ('rename-retry',['native/tests/cmos_rename_retry_tests.cpp','native/src/mk5_program.cpp'],['-municode','-lbcrypt'],[[scratch/'retry-profiles']],[]),
                ('operator-rom-oracle',oracle,['-DMKOPERATOR_ORACLE','-municode','-lbcrypt','-luser32','-lgdi32'],[[q.ROOT]],[]),
                ('controller-selection',['native/tests/launcher_selection_tests.cpp','native/launcher/launcher_renderer.cpp','native/launcher/launcher_backend.cpp'],
                 ['-municode',*backend,*ui_libs],[[scratch/'controller-root']],backend_sources),
                ('operator-ui',['native/tests/launcher_operator_ui_tests.cpp','native/launcher/launcher_renderer.cpp','native/launcher/launcher_backend.cpp'],
                 ['-municode',*backend,*ui_libs],[[scratch/'ui-root',q.ROOT]],backend_sources),
                ('operator-backend',['native/tests/launcher_operator_backend_tests.cpp','native/launcher/launcher_backend.cpp'],
                 ['-municode',*backend,'-luser32'],[[q.ROOT,scratch/'backend-mk1','core'],[q.ROOT,scratch/'backend-mk2','mk2-core']],backend_sources),
            ]
            project_sources=[]
            for _,sources,_,_,extra_sources in cases:
                project_sources.extend(q.ROOT/source for source in sources if isinstance(source,str))
                project_sources.extend(extra_sources)
            project_dependencies=dependencies(project_sources)|{q.ROOT/'native/include/mk5_audio_volume.hpp'}
            receipt['source_sha256']={str(path.relative_to(q.ROOT).as_posix()):q.sha(path) for path in sorted(project_dependencies)}
            from tools.setup import mk1 as setup_mk1
            inputs=[setup_mk1.seed_path().relative_to(q.ROOT).as_posix(),'native/runtime/mk2-factory-default-cmos.bin',
                    'roms/mk1/mkt-uj12.bin','roms/mk1/mkt-ug12.bin','roms/mk2/uj12.l31','roms/mk2/ug12.l31',
                    'build/native/mk2-native-v1/product/native-package.ini']
            from tools.setup import mk2 as setup_mk2   # resolves the generated MK2 seed under its former name
            receipt['input_sha256']={name:q.sha(setup_mk2.source(name)) for name in inputs}
            for name,sources,extra,runs,_ in cases:
                source_paths=[q.ROOT/source if isinstance(source,str) else source for source in sources]
                executable=scratch/(name+'.exe')
                built=q.command([*common,*source_paths,*extra,'-o',executable],scratch,cwd=q.ROOT,env=env,timeout=240)
                row={'name':name,'sources':[str(path.relative_to(q.ROOT)) for path in source_paths if not path.is_relative_to(scratch)],
                     'build':q.compact(built),'runs':[],'passed':False}
                if name=='volume-helper':row['generated_source_sha256']=q.sha(volume)
                if built['passed']:
                    row['binary_sha256']=q.sha(executable)
                    for arguments in runs:
                        tested=q.command([executable,*arguments],scratch,cwd=q.ROOT,env=env,timeout=90)
                        row['runs'].append(q.compact(tested))
                    row['passed']=bool(row['runs']) and all(result['passed'] for result in row['runs'])
                receipt['cases'].append(row)
                print(('PASS ' if row['passed'] else 'FAIL ')+name,flush=True)
            receipt['changed_sources']=[name for name,digest in receipt['source_sha256'].items() if q.sha(q.ROOT/name)!=digest]
            receipt['changed_inputs']=[name for name,digest in receipt['input_sha256'].items() if q.sha(q.ROOT/name)!=digest]
        receipt['passed']=bool(receipt['cases']) and all(row['passed'] for row in receipt['cases']) and cleanup.get('exists_after') is False and not receipt['changed_sources'] and not receipt['changed_inputs']
    except Exception as error:
        receipt['error']=repr(error)
    path=q.STAGE/'operator-ubsan.json'
    if any(parent.is_symlink() or parent.is_junction() for parent in (path,*path.parents)):raise RuntimeError('Linked UBSan receipt path rejected')
    path.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(('PASS' if receipt['passed'] else 'FAIL')+' '+str(path),flush=True)
    return 0 if receipt['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
