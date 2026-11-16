"""Published native MK2 operator smoke; real DX12/audio, disposable profile, no captures."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.launcher_backend_build import arguments as backend_arguments


def main(installation_root=q.ROOT):
    parser=argparse.ArgumentParser()
    parser.add_argument('--compile-only',action='store_true',help='verify the fixture builds without launching a game')
    parser.add_argument('--remastered',action='store_true')
    parser.add_argument('--phosphor',action='store_true',help='verify the compensated aperture grille through saved Settings')
    parser.add_argument('--saved-credits',action='store_true',help='exact user CMOS, BVM1080, ScaleFX40 and fullscreen in an isolated installation')
    args=parser.parse_args()
    receipt={'passed':False,'runtime_executed':False,'scope':'Published MK2 native operator/profile/PVM/output-volume smoke; not complete gameplay fidelity',
             'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'runner_sha256':q.sha(Path(__file__)),
             'certifies_arcade_fidelity':False,'certifies_no_memory_leaks':False}
    try:
        with q.scratch_tree() as (scratch,cleanup):
            receipt['cleanup']=cleanup
            root=q.ROOT
            env=dict(os.environ,PATH=str(q.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH',''),TEMP=str(scratch),TMP=str(scratch))
            executable=scratch/'operator-package-smoke.exe'
            sources=[root/'native/tests/mk2_operator_package_smoke.cpp',root/'native/launcher/launcher_backend.cpp',root/'native/launcher/launcher_renderer.cpp']
            backend=backend_arguments(root)
            provenance=[*sources,*[Path(value) for value in backend if str(value).endswith('.cpp')],
                        root/'native/launcher/launcher_backend.hpp',root/'native/launcher/launcher_main.cpp',root/'native/runtime/mk2_music_manifest.hpp',root/'native/include/mk5_operator_settings.hpp',root/'native/include/mk5_video_presets.hpp']
            receipt['source_sha256']={path.relative_to(root).as_posix():q.sha(path) for path in provenance}
            receipt['compiler_path']=str(q.DEFAULT_CC);receipt['compiler_sha256']=q.sha(q.DEFAULT_CC)
            compiled=q.command([q.DEFAULT_CC,'-std=c++17','-O2','-static','-municode','-Wall','-Wextra','-Werror',
                                '-I'+str(root/'native/launcher'),*sources,*backend,*['-l'+n for n in ('d3d12','dxgi','d3dcompiler','dxguid','windowscodecs','ole32','uuid','gdi32','user32','shell32','xinput9_1_0')],'-o',executable],
                               scratch,cwd=root,env=env,timeout=180)
            receipt['compile']=q.compact(compiled)
            if not compiled['passed']:raise RuntimeError('Packaged operator fixture compilation failed')
            if not args.compile_only:
                published=installation_root/'build/native/mk2-native-v1/product'
                receipt['published_manifest_sha256']=q.sha(published/'native-package.ini')
                fields=dict(line.split('=',1) for line in (published/'native-package.ini').read_text(encoding='utf-8').splitlines() if '=' in line)
                receipt['published_identity']={name:fields[name] for name in ('executable_sha256','source_sha256','core_overlays_sha256','runtime_sources_sha256','rom_profile_sha256')}
                smoke_root=scratch/('Coleção MK2'if args.remastered else 'root')
                options=[name for name,enabled in (('--remastered',args.remastered),('--saved-credits',args.saved_credits),('--phosphor',args.phosphor)) if enabled]
                tested=q.command([executable,installation_root,smoke_root,*options],scratch,cwd=root,env=env,timeout=90)
                receipt['runtime_executed']=True;receipt['test']=q.compact(tested)
                log=smoke_root/'build/native/mk2-native-v1/product/logs/native-experiment-latest.log'
                if not tested['passed']:
                    if log.is_file() and log.stat().st_size<=1024*1024:
                        receipt['native_failure']=[line[:240] for line in log.read_text(encoding='utf-8',errors='replace').splitlines()
                                                   if line and not line.startswith(('MK2_REPLAY_','{'))][:8]
                    raise RuntimeError('Published native operator session failed')
                summaries=[json.loads(line) for line in tested['stdout'].splitlines() if line.startswith('{')]
                assert len(summaries)==1 and summaries[0]['scope']=='mk2-operator-package-smoke','missing unambiguous smoke summary'
                receipt['session']=summaries[0]
                assert log.stat().st_size<=1024*1024,'native smoke log exceeds compact bound'
                records=[]
                for line in log.read_text(encoding='utf-8').splitlines():
                    try:record=json.loads(line)
                    except ValueError:continue
                    if record.get('scope')=='mk2-native-cmos-live-experiment':records.append(record)
                assert len(records)==1,'missing unambiguous published native live record'
                record=records[0];presentation=record['presentation'];audio=record['audio'];profile=record['profile']
                assert record['operator_dsw_word']==(0xfc7d if args.saved_credits else 0x3c7d),'actual native board DIP must match requested switches'
                assert record['through']=='cmos-live' and record['termination']=='valid_cmos_live_stop_requested'
                host=record['host_controls']
                receipt['live_input']={key:host[key] for key in ('provider_admitted','provider_requests')}
                assert record['frames']>0 and host['provider_admitted'] is True and host['provider_requests']>0, 'smoke closed before the live input provider ran'
                assert presentation['renderer']=='D3D12-DXGI-flip' and presentation['submitted_frames']>0 and presentation['displayed_frames']>0
                assert presentation['source_width']==record['width'] and presentation['source_height']==record['height']
                assert presentation['crt_preset']==('phosphor'if args.phosphor else 'bvm-1080'if args.saved_credits else'pvm') and presentation['crt_source']=='complete-original' and presentation['fullscreen_start'] is (args.saved_credits or args.phosphor)
                if args.phosphor:
                    assert presentation['scalefx_amount']==100 and presentation['scalefx_passes']==5 and presentation['crt_integer_vertical']
                    assert presentation['filter']=='sharp-bilinear' and presentation['scale_mode']==5
                    assert presentation['cas_amount']==25 and presentation['bilateral_amount']==25 and presentation['smaa'] is True
                if args.saved_credits:assert presentation['scalefx_amount']==40 and presentation['scalefx_passes']==5
                readbacks=presentation['gpu_validation_frames']
                fighter_readbacks=presentation['bicubic_fighter_validation_frames']
                assert presentation['gpu_validation_mismatches']==0 and presentation['last_present_hresult']>=0
                if args.remastered:
                    assert 0<=fighter_readbacks<=1 and max(1,fighter_readbacks)<=readbacks<=2+fighter_readbacks
                else:
                    assert readbacks==1 and fighter_readbacks==0 and presentation['bicubic_fighter_frames']==0
                assert presentation['gpu_validation_max_error']<=presentation['gpu_validation_tolerance']
                assert record['audio_playback'] is True and audio['source_rate']==31250 and audio['output_rate']==48000 and audio['channels']==(2 if args.remastered else 1)
                assert audio['music_mode']==('remastered' if args.remastered else 'original') and audio['music_clipped']==0
                assert audio['source_samples']>0 and audio['output_samples']==audio['submitted']==audio['completed'] and audio['underruns']==0
                assert profile['committed'] is True and profile['loaded_sha256']==receipt['session']['loaded_cmos_sha256'] and profile['saved_sha256']==receipt['session']['saved_cmos_sha256']
                receipt['native']={'scope':record['scope'],'operator_dsw_word':record['operator_dsw_word'],'source_frames':record['frames'],
                                   'displayed_frames':presentation['displayed_frames'],'renderer':presentation['renderer'],'crt_preset':presentation['crt_preset'],
                                   'source_width':record['width'],'source_height':record['height'],'gpu_validation_mismatches':presentation['gpu_validation_mismatches'],
                                   'filters':{key:presentation[key] for key in ('filter','scale_mode','scalefx_amount','cas_amount','bilateral_amount','smaa')},
                                   'gpu_validation_max_error':presentation['gpu_validation_max_error'],'gpu_validation_tolerance':presentation['gpu_validation_tolerance'],
                                   'gpu_validation_frames':readbacks,'bicubic_fighter_validation_frames':fighter_readbacks,
                                   'audio':audio,'profile':profile,'native_log_bytes':log.stat().st_size}
                receipt['published_manifest_unchanged']=q.sha(published/'native-package.ini')==receipt['published_manifest_sha256']
                assert receipt['published_manifest_unchanged'],'published installation changed during smoke'
            receipt['source_changes']=[name for name,digest in receipt['source_sha256'].items() if q.sha(root/name)!=digest]
        receipt['passed']=not args.compile_only and receipt['runtime_executed'] and not receipt['source_changes'] and cleanup.get('exists_after') is False
    except Exception as error:
        receipt['error']=repr(error)
    if args.compile_only:
        prepared='compile' in receipt and receipt['compile']['passed'] and receipt.get('cleanup',{}).get('exists_after') is False
        print(json.dumps({'prepared':prepared,'runtime_executed':False,'compile':receipt.get('compile'),'error':receipt.get('error'),'cleanup':receipt.get('cleanup')},indent=2))
        return 0 if prepared else 1
    path=q.STAGE/('operator-package-smoke'+('-saved-credits'if args.saved_credits else'')+('-remastered'if args.remastered else'')+('-phosphor'if args.phosphor else'')+'.json')
    if any(parent.is_symlink() or parent.is_junction() for parent in (path,*path.parents)):raise RuntimeError('Linked smoke receipt path rejected')
    path.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(('PASS ' if receipt['passed'] else 'FAIL ')+str(path))
    if not receipt['passed']:print(json.dumps({name:receipt[name] for name in ('error','compile','test','live_input','native_failure','cleanup') if name in receipt},indent=2))
    return 0 if receipt['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
