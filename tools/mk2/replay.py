"""Replay compact MK2 crash inputs from authenticated reset, without video throttling.

One temporary build serves all supplied logs. This is native discovery, not an
Original gameplay qualification; first unsupported paths remain failed cases.
"""
from pathlib import Path
import argparse
import filecmp
import hashlib
import json
import os
import re
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import generate_video_irq as emitter, package_native as package, run, profile
from tools.quality import run as q
DIAGNOSTIC_PATHS=('tools/mk2/replay.py','tools/mk2/replay_reference.py','tools/mk2/replay_audio.py',
                  'tools/mk2/dac_reference.py','tools/mk2/replay_state.py','tools/mk2/batch_reference.py',
                  'tools/mk2/reference.py','native/tests/mk2_recovery_tests.cpp')
HOST_ACTIVE_MASK=0x36277f7f
MAX_CAPTURE_BYTES=1024*1024
MAX_TRANSITIONS=16384
VERY_EASY_SHA256='0dd770a29c1c175b41e3d13916f8fce8fd67b019e6d00e937568a9536d9f1e44'


def describe_failure(output):
    row={'kind':'runtime_rejection'}
    pc=re.search(r'; TMS PC ([0-9]+)',output)
    if pc:row['pc']=f'{int(pc[1]):08x}'
    cpu=re.search(r'; CPU34 ([0-9]+(?:,[0-9]+){33})(?:\s|$)',output)
    if cpu:row['cpu34']=[int(v)for v in cpu[1].split(',')]
    dma=re.search(r'MK2 pair DMA outside measured unscaled commands; command ([0-9]+); xstep ([0-9]+); ystep ([0-9]+)',output)
    if dma:row.update(kind='dma_command',command=f'{int(dma[1]):04x}',xstep=int(dma[2]),ystep=int(dma[3]))
    elif 'PC outside authenticated fixed translation'in output:row['kind']='missing_static_pc'
    elif 'untranslated instruction'in output:row['kind']='untranslated_instruction'
    elif 'wall-clock watchdog expired'in output:row['kind']='watchdog'
    dsp=re.search(r'ADSP untranslated PC ([0-9]+)(?:; opcode ([0-9]+))?',output)
    if dsp:
        if 'pc'in row:row['tms_pc']=row['pc']
        row.update(kind='adsp_untranslated_pc',pc=f'{int(dsp[1]):04x}')
        if dsp[2]:row['opcode']=f'{int(dsp[2]):06x}'
    changed=re.search(r'ADSP translated opcode changed at PC ([0-9]+); expected ([0-9]+); actual ([0-9]+)',output)
    if changed:
        if 'pc'in row:row['tms_pc']=row['pc']
        row.update(kind='adsp_opcode_changed',pc=f'{int(changed[1]):04x}',
                   expected_opcode=f'{int(changed[2]):06x}',opcode=f'{int(changed[3]):06x}')
    return row


def expand_logs(paths):
    files=[]
    for path in paths:files.extend(sorted(path.glob('*.json'))if path.is_dir()else[path])
    if not files or any(not path.is_file()for path in files)or len({path.resolve()for path in files})!=len(files):
        raise ValueError('Provide distinct replay files or a nonempty directory of JSON cases')
    return files


def read_capture(text):
    if len(text)>MAX_CAPTURE_BYTES:raise ValueError('Replay log exceeds compact capture limit')
    if text.lstrip().startswith('{') and not re.search(r'^MK2_REPLAY_V1 ',text,re.M):
        data=json.loads(text)
        if (data.get('format')!='MK2_REPLAY_V1' or data.get('timebase_hz')!=100000000 or
            data.get('initial_shared_active_low')!=0xffffffff):raise ValueError('Invalid Original input recipe identity')
        if 'initial_cmos_sha256' in data or 'initial_cmos_bytes' in data:
            if ('factory_cmos_sha256' in data or 'factory_cmos_bytes' in data or
                data.get('initial_cmos_sha256')!=VERY_EASY_SHA256 or data.get('initial_cmos_bytes')!=profile.SIZE):
                raise ValueError('Invalid Original recipe initial CMOS identity')
            digest=VERY_EASY_SHA256
        else:
            if data.get('factory_cmos_sha256')!=profile.FACTORY_SHA256 or data.get('factory_cmos_bytes')!=profile.SIZE:
                raise ValueError('Invalid Original recipe factory CMOS identity')
            digest=profile.FACTORY_SHA256
        rows=data.get('request_rows')
        if not isinstance(rows,list)or not 1<=len(rows)<=MAX_TRANSITIONS or any(not isinstance(row,list)or len(row)!=2 or any(type(v)is not int for v in row)for row in rows):
            raise ValueError('Invalid Original recipe request rows')
        seed=bytearray(profile._read(profile.FACTORY_SEED,factory=True))
        if digest==VERY_EASY_SHA256:
            # Exact operator parameter 14 and settings checksum from the captured seed.
            seed[4214]=1;seed[4434]=63
        canonical=f'MK2_REPLAY_V1 {data.get("program_sha256")} {digest} {len(rows)} 1\nMK2_REPLAY_CMOS {seed.hex()}\n'+''.join(f'MK2_REPLAY_INPUT {t} {v}\n'for t,v in rows)+'MK2_REPLAY_END\n'
        result=read_capture(canonical)
        ends=[int(row.split('\t')[1])for row in data.get('candidate_events',[])if re.fullmatch(r'END\t[0-9]+(?:\t.*)?',row)]
        frame=data.get('end_frame',ends[0]if len(ends)==1 else None)
        if type(frame)is not int or not 1<=frame<=0xffffffffffffffff//1827925:raise ValueError('Missing/invalid Original recipe end frame')
        # Extend the recipe observation to the next full50Hz audio block; input times stay exact.
        result['recipe_end_frame']=frame;result['end_cycles']=((frame*1827925+15)//16+124999)//125000*125000
        snapshots=data.get('snapshot_frames',[])
        if (not isinstance(snapshots,list)or len(snapshots)>64 or any(type(v)is not int or not 1<=v<=frame for v in snapshots)or
            len(set(snapshots))!=len(snapshots)):raise ValueError('Invalid recipe raster sample frames')
        result['snapshot_frames']=sorted(snapshots)
        visual=data.get('visual_acceptance')
        typed=data.get('Original_visual_acceptance')
        if data.get('kind')=='stage_natural' and isinstance(visual,dict) and 'accepted' not in visual:
            # Archived stage tapes store scene frame locators. Recognition requires a separate sealed receipt.
            kill=visual.get('stage_kill_frame');banner=visual.get('finish_banner_frame')
            if (set(visual)!={'stage_kill_frame','finish_banner_frame','contact_sha256'} or
                data.get('Original_accepted') is not True or typed is not None or
                type(kill) is not int or type(banner) is not int or
                kill not in snapshots or banner not in snapshots or kill>=banner or
                not isinstance(visual['contact_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',visual['contact_sha256'])):
                raise ValueError('Invalid archived stage scene locators')
            visual=None
        acceptances=[value for value in (visual,typed) if value is not None]
        if any(not isinstance(value,dict)or type(value.get('accepted'))is not bool for value in acceptances)or (len(acceptances)>1 and acceptances[0]!=acceptances[1]):
            raise ValueError('Invalid or conflicting Original acceptance metadata')
        result['recipe']=data.get('recipe');result['reference_visual_acceptance']=acceptances[0]if acceptances else None
        return result
    lines=text.splitlines()
    headers=[n for n,line in enumerate(lines) if line.startswith('MK2_REPLAY_V1 ')]
    if len(headers)!=1:raise ValueError('Exactly one complete replay capture required')
    begin=headers[0];header=lines[begin].split()
    if len(header)!=5 or header[1]!=emitter.PROGRAM_SHA256 or not re.fullmatch('[0-9a-f]{64}',header[2]):
        raise ValueError('Replay ROM/CMOS identity is invalid')
    if not header[3].isdecimal() or not 0<=int(header[3])<=MAX_TRANSITIONS or header[4]!='1':
        raise ValueError('Replay input prefix is incomplete or overflowed')
    count=int(header[3]);payload=lines[begin+1:]
    if len(payload)!=count+2 or payload[-1]!='MK2_REPLAY_END' or not payload[0].startswith('MK2_REPLAY_CMOS '):
        raise ValueError('Replay is truncated or ambiguous')
    hex_image=payload[0].removeprefix('MK2_REPLAY_CMOS ')
    if not re.fullmatch('[0-9a-f]{32768}',hex_image):raise ValueError('Invalid exact replay CMOS image')
    cmos=bytes.fromhex(hex_image)
    if hashlib.sha256(cmos).hexdigest()!=header[2]:raise ValueError('Replay CMOS hash differs')
    inputs=[]
    for line in payload[1:-1]:
        match=re.fullmatch(r'MK2_REPLAY_INPUT ([0-9]+) ([0-9]+)',line)
        if match is None:raise ValueError('Invalid input transition')
        tick,value=map(int,match.groups())
        if value<=0xffffffff and ((value^0xffffffff)&~HOST_ACTIVE_MASK):raise ValueError('Input outside legal host control map')
        if tick>0xffffffffffffffff or value>0xffffffff or (inputs and tick<=inputs[-1][0]):
            raise ValueError('Non-monotonic or out-of-range replay input')
        if inputs and value==inputs[-1][1]:raise ValueError('Redundant replay transition')
        inputs.append((tick,value))
    cpu=re.search(r'; CPU34 ([0-9]+(?:,[0-9]+){33})(?:\r?\n|$)',text[:text.index('MK2_REPLAY_V1 ')])
    return {'program_sha256':header[1],'cmos_sha256':header[2],'cmos':cmos,'inputs':inputs,
            'failed_cpu34':[int(v)for v in cpu[1].split(',')] if cpu else None}


def recovery_source(*,audio=False,fighter_observation=False):
    source=(q.ROOT/'native/tests/mk2_recovery_tests.cpp').read_text()
    source=source.replace('#include "../mk2/mk2_native_check.cpp"',
        '#include "'+(q.ROOT/'native/mk2/mk2_native_check.cpp').as_posix()+'"').replace(
        '#include "../mk2/mk2_factory_seed.hpp"','#include "'+(q.ROOT/'native/mk2/mk2_factory_seed.hpp').as_posix()+'"')
    marker='    try {\n'
    assert source.count(marker)==1
    source=source.replace(marker,marker+'        if(argc!=10)throw std::runtime_error("Replay harness requires validated timeline/CMOS/hash");\n')
    old='std::ifstream stream(mk2::FactorySeedPath(),std::ios::binary);'
    assert source.count(old)==1
    source=source.replace('const auto image=[]{','const auto image=[&]{').replace(old,
        'std::ifstream stream(std::filesystem::path(argv[8]),std::ios::binary);')
    old='Sha256(image)!="f401005e9be6b161ba3becb3cc20b8fd72359e3234652af3b5c2fbbce0d06e1f"'
    assert source.count(old)==1
    source=source.replace(old,'Sha256(image)!=std::filesystem::path(argv[9]).string()')
    marker='        mk2::GeneratedBoot generated('
    assert source.count(marker)==1
    source=source.replace(marker,'        mk2::ReplayCapture runtime_capture;runtime_capture.Start(Sha256(program.bytes),Sha256(image),image,mk2::ReplayCapture::diagnostic_limit);\n'+marker)
    first=source.index('        auto provider=[=]');last=source.index('        auto current=',first)
    source=source[:first]+'''        std::ifstream timeline{std::filesystem::path(argv[7])};
        std::vector<std::pair<uint64_t,uint32_t>> events;uint64_t at;uint32_t value;
        while(timeline>>at) {
            if(!(timeline>>value) || events.size()==mk2::ReplayCapture::diagnostic_limit)
                throw std::runtime_error("Invalid replay timeline");
            events.emplace_back(at,value);
        }
        if(!timeline.eof())throw std::runtime_error("Invalid replay timeline");
        size_t cursor=0;uint32_t requested=0xffffffffu;
        auto provider=[&](uint64_t tick){
            while(cursor<events.size() && events[cursor].first<=tick)requested=events[cursor++].second;
            if(cursor)runtime_capture.Observe(tick,requested);
            return requested;
        };
'''+source[last:]
    # Discovery does not retain raster/memory snapshots; only the final in-memory state summary.
    source=source.replace('        const bool controls=argc>4 && std::wstring(argv[4])==L"controls";','')
    assert source.count('        return 0;')==1
    source=source.replace('        return 0;','        runtime_capture.Write(std::cout);return 0;')
    progress=[line for line in source.splitlines()if 'std::cerr<<"progress PC="'in line]
    assert len(progress)==1
    source=source.replace(progress[0],'')
    marker='        machine->SetScanlineObserver([&](const auto& edge,const auto& video){scanout.Line(edge,video);});'
    assert source.count(marker)==1
    source=source.replace(marker,'''        std::vector<uint64_t> sampled_frames;
        if(!output.empty() && std::filesystem::exists(output/"sample-frames.txt")) {
            std::ifstream frames(output/"sample-frames.txt");uint64_t frame;
            while(frames>>frame)sampled_frames.push_back(frame);
            if(!frames.eof() || sampled_frames.size()>64 || !std::is_sorted(sampled_frames.begin(),sampled_frames.end()))
                throw std::runtime_error("Invalid replay raster observation list");
        }
        machine->SetScanlineObserver([&](const auto& edge,const auto& video){
            const auto before=scanout.frames();scanout.Line(edge,video);
            if(scanout.frames()!=before && std::binary_search(sampled_frames.begin(),sampled_frames.end(),scanout.frames())) {
                std::ofstream frame(output/("frame-"+std::to_string(scanout.frames())+".rgb"),std::ios::binary);
                for(auto rgb:scanout.pixels()){const char bytes[]={char(rgb>>16),char(rgb>>8),char(rgb)};frame.write(bytes,3);}
                frame.close();if(!frame)throw std::runtime_error("Replay complete sampled raster write failed");
            }
        });''')
    if audio:
        from tools.mk2 import replay_audio,replay_state
        source=replay_audio.native_source(source)
        source=replay_state.native_source(source)
    if fighter_observation:
        source=source.replace('mk2::Scanout scanout;', 'mk2::Scanout scanout(true);\n'
            '        uint64_t fighter_frames=0,fighter_layers=0,fighter_pixels=0;')
        old='const auto video=mk2::RunVideoInit(program,powerup,*machine);'
        assert source.count(old)==1
        source=source.replace(old,'''auto video=mk2::RunVideoInit(program,powerup,*machine);
        video.video.EnableBackdrop();
        video.video.EnableFighters();''')
        old='const auto before=scanout.frames();scanout.Line(edge,video);'
        assert source.count(old)==1
        source=source.replace(old,old+'''
            const auto& fighter=scanout.fighter_frame();
            if(scanout.frames()!=before && fighter.serial){
                if(fighter.serial!=scanout.frames())throw std::runtime_error("Mixed MK2 fighter frame serial");
                ++fighter_frames;
                fighter_layers+=fighter.layers.size();
                fighter_pixels+=std::count(fighter.covered.begin(),fighter.covered.end(),uint8_t(1));
            }''')
        old='        runtime_capture.Write(std::cout);return 0;'
        assert source.count(old)==1
        source=source.replace(old,'''        std::cout<<"FIGHTER "<<fighter_frames<<' '<<fighter_layers<<' '<<fighter_pixels<<'\\n';
'''+old)
    return source


def execution_wall_seconds(cycles):
    # Long reset-to-Pit-II chains need more host time; guest watchdogs stay unchanged.
    return max(180,min(2400,(cycles+6249999)//6250000))


def compact_execution(result):
    compact=q.compact(result)
    compact['output_tail']='\n'.join(line[:240]for line in result['stdout'].splitlines()
        if line and not line.startswith(('MK2_REPLAY_','{')))[:2000]
    return compact


def checked_snapshot_frames(frames,cycles):
    if (len(frames)>64 or len(set(frames))!=len(frames) or
        any(type(frame)is not int or not 1<=frame<=cycles*16//1827925 for frame in frames)):
        raise ValueError('Invalid snapshot frames for requested execution horizon')
    return sorted(frames)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logs',type=Path,nargs='+');parser.add_argument('--cycles',type=int)
    parser.add_argument('--original',action='store_true',help='Compare CPU, complete memories, final raster and all audio against pinned Original')
    parser.add_argument('--roundtrip',action='store_true',help='Capture actual provider transitions and replay them again; compare entire native state/raster/audio')
    parser.add_argument('--static-batch', action='store_true', help='Compile and exercise the isolated batch AOT candidate')
    parser.add_argument('--snapshot-frames',type=int,nargs='+',help='Complete intermediate rasters to compare, at most64 frames within the execution horizon')
    parser.add_argument('--fighter-observation',action='store_true',help='Enable fighter layer collection and count complete frames, layers and native coverage')
    parser.add_argument('--report',type=Path,required=True);args=parser.parse_args()
    if args.report.exists():parser.error('Preserve the existing receipt; choose another --report')
    cases=[]
    for path in expand_logs(args.logs):
        if path.stat().st_size>MAX_CAPTURE_BYTES:parser.error('Replay log exceeds compact capture limit')
        content=path.read_bytes();capture=read_capture(content.decode('utf8'));capture['source_sha256']=hashlib.sha256(content).hexdigest()
        cycles=args.cycles or capture.get('end_cycles') or (capture['failed_cpu34'][2]+2000000 if capture['failed_cpu34'] else None)
        if not cycles or cycles<=0 or cycles>0xffffffffffffffff//16:parser.error('Supply valid --cycles when the failure has no CPU34')
        if args.original and cycles%125000:
            parser.error('--original requires --cycles on a 125000-cycle audio boundary; choose the next boundary without changing input times')
        if capture['inputs'] and capture['inputs'][-1][0]>cycles*16:parser.error('Input timeline extends beyond requested discovery endpoint')
        capture['snapshot_frames']=checked_snapshot_frames(args.snapshot_frames if args.snapshot_frames is not None else capture.get('snapshot_frames',[]),cycles)
        cases.append((path,capture,cycles))
    r={'passed':False,'scope':'Reset plus exact captured CMOS and legal input timeline. '+('Full pinned Original state/raster/audio comparison per case.'if args.original else'Native discovery only; no Original/finisher qualification.'),'cases':[]}
    diagnostic_paths=DIAGNOSTIC_PATHS
    r['diagnostic_inputs']={p:q.sha(q.ROOT/p)for p in diagnostic_paths}
    try:
        with q.scratch_tree()as(scratch,cleanup):
            r['cleanup']=cleanup
            env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH'],'TEMP':str(scratch),'TMP':str(scratch)}
            identity=package.identities(scratch,env);r['sources']=identity;r['roms']=run.verify_roms(q.ROOT/'roms/mk2')
            source=scratch/'replay.cpp'
            source.write_bytes(recovery_source(audio=args.original or args.roundtrip,fighter_observation=args.fighter_observation).encode('utf8'))
            exe=scratch/'replay.exe'
            r['generated_harness_sha256']=q.sha(source)
            if args.static_batch:
                from tools.mk2 import static_batch
                r['static_batch'] = {}
                batch_sources = static_batch.prepare(scratch, q.ROOT/'roms/mk2', r['static_batch'])
                build = static_batch.compile_candidate(scratch, batch_sources, exe, env, replay_source=source)
            else:
                build=q.command([q.DEFAULT_CC,*package.FLAGS,'-static',source,
                    *[q.ROOT/p for p in package.SOURCES if p!='native/mk2/mk2_native_check.cpp'],
                    *package.LIBRARIES,'-o',exe],scratch,cwd=q.ROOT,env=env,timeout=240)
            r['build']=q.compact(build);assert build['passed'],build['stdout']
            if args.static_batch:
                r['static_batch']['replay_executable_sha256'] = q.sha(exe)
            negative=q.command([exe,scratch/'missing-roms','--smoke'],scratch,cwd=q.ROOT,env=env)
            r['incomplete_arguments']=q.compact(negative)
            assert not negative['passed'] and 'Replay harness requires validated timeline/CMOS/hash' in negative['stdout']
            for path,capture,cycles in cases:
                wall_seconds=execution_wall_seconds(cycles)
                assert q.sha(path)==capture['source_sha256'],'Input capture changed during discovery'
                timeline=scratch/'inputs.txt';timeline.write_text(''.join(f'{tick} {value}\n'for tick,value in capture['inputs']))
                cmos=scratch/'initial-cmos.bin';cmos.write_bytes(capture['cmos'])
                with q.scratch_tree()as(case_scratch,case_cleanup):
                    output=case_scratch/'native';output.mkdir()
                    frame_list=''.join(f'{n}\n'for n in capture.get('snapshot_frames',[]))
                    (output/'sample-frames.txt').write_text(frame_list)
                    result=q.command([exe,q.ROOT/'roms/mk2','--smoke',str(cycles),'replay',output if args.original or args.roundtrip else '',
                                      '2000000',timeline,cmos,capture['cmos_sha256']],case_scratch,cwd=q.ROOT,env=env,timeout=wall_seconds,output_limit=MAX_CAPTURE_BYTES)
                    row={'log_sha256':capture['source_sha256'],'requested_cycles':cycles,'input_transitions':len(capture['inputs']),
                         'snapshot_frames_requested':capture['snapshot_frames'],
                         'initial_cmos_sha256':capture['cmos_sha256'],'host_wall_limit_seconds':wall_seconds,'execution':compact_execution(result),'cleanup':case_cleanup}
                    if 'recipe'in capture:row.update(recipe=capture['recipe'],reference_visual_acceptance=capture['reference_visual_acceptance'],recipe_end_frame=capture['recipe_end_frame'])
                    r['cases'].append(row)
                    if result['passed']:
                        if result['discarded_output_bytes']:raise ValueError('Replay stdout capture was truncated')
                        row['native']=json.loads(next(line for line in result['stdout'].splitlines()if line.startswith('{')))
                        if args.fighter_observation:
                            counts=[line.split()[1:] for line in result['stdout'].splitlines() if line.startswith('FIGHTER ')]
                            if len(counts)!=1 or len(counts[0])!=3:raise ValueError('Incomplete fighter layer observation')
                            row['fighter_layers']=dict(zip(('frames','layers','covered_pixels'),map(int,counts[0])))
                        if args.roundtrip:
                            observed=read_capture(result['stdout'])
                            timeline.write_text(''.join(f'{tick} {value}\n'for tick,value in observed['inputs']))
                            observed_cmos=case_scratch/'captured-initial-cmos.bin';observed_cmos.write_bytes(observed['cmos'])
                            again=case_scratch/'roundtrip';again.mkdir()
                            (again/'sample-frames.txt').write_text(frame_list)
                            second=q.command([exe,q.ROOT/'roms/mk2','--smoke',str(cycles),'replay',again,'2000000',timeline,observed_cmos,observed['cmos_sha256']],case_scratch,cwd=q.ROOT,env=env,timeout=wall_seconds,output_limit=MAX_CAPTURE_BYTES)
                            trip={'passed':False,'execution':compact_execution(second),'captured_transitions':len(observed['inputs']),
                                  'captured_cmos_equal':observed['cmos']==capture['cmos']};row['roundtrip']=trip
                            if second['passed']:
                                comparison_started = time.perf_counter()
                                if second['discarded_output_bytes']:raise ValueError('Roundtrip stdout capture was truncated')
                                other=json.loads(next(line for line in second['stdout'].splitlines()if line.startswith('{')))
                                from tools.mk2.replay_state import BOARD_FILES, FILES
                                fixed_sizes={**BOARD_FILES, **FILES}
                                names=(*fixed_sizes,'last-frame.ppm','native-source.bin','native-speaker.bin','native-pcm16.bin')
                                names+=tuple(f'frame-{n}.rgb'for n in capture.get('snapshot_frames',[]))
                                trip['files']={}
                                for name in names:
                                    size=(output/name).stat().st_size
                                    exact_size=name not in fixed_sizes or size==fixed_sizes[name]
                                    trip['files'][name]={'passed':exact_size and filecmp.cmp(output/name,again/name,shallow=False),'bytes':size}
                                trip['cpu34_equal']=row['native']['cpu34']==other['cpu34']
                                trip['passed']=trip['captured_cmos_equal']and trip['cpu34_equal']and all(v['passed']for v in trip['files'].values())
                                trip['comparison_seconds'] = time.perf_counter()-comparison_started
                        if args.original:
                            from tools.mk2 import replay_reference
                            try:row['original']=replay_reference.compare(case_scratch/'original',capture,row['native'],output,env,wall_seconds=wall_seconds)
                            except Exception as error:row['original']={'passed':False,'error':repr(error)}
                    else:
                        row['first_frontier']=describe_failure(result['stdout'])
                        if 'pc'in row['first_frontier'] and not row['first_frontier']['kind'].startswith('adsp_'):
                            pc=int(row['first_frontier']['pc'],16)
                            try:
                                rows,proof=__import__('tools.mk2.offline_decode',fromlist=['decode']).decode(emitter.load_program(q.ROOT/'roms/mk2'),[pc])
                                row['first_frontier'].update(authenticated_instruction=rows[pc],decoder=proof)
                            except ValueError as error:row['first_frontier']['decoder_error']=str(error)
            assert identity==package.identities(scratch,env),'Source changed during replay discovery'
            if args.static_batch:
                assert r['static_batch']['native_compile_contract']==static_batch.native_compile_contract(),'Native compiler or build recipe changed'
                assert r['static_batch']['replay_executable_sha256']==q.sha(exe),'Replay executable changed during discovery'
            assert all(q.sha(path)==capture['source_sha256']for path,capture,_ in cases),'Input capture changed during discovery'
            assert r['diagnostic_inputs']=={p:q.sha(q.ROOT/p)for p in diagnostic_paths},'Diagnostic source changed during discovery'
            r['passed']=all(row['execution']['passed']and row.get('original',{'passed':True})['passed']and row.get('roundtrip',{'passed':True})['passed']for row in r['cases'])
    except Exception as error:r['error']=repr(error)
    args.report.write_text(json.dumps(r,indent=2));print(json.dumps({k:v for k,v in r.items()if k not in ('sources','roms')},indent=2))
    return 0 if r['passed']else 1


if __name__=='__main__':raise SystemExit(main())
