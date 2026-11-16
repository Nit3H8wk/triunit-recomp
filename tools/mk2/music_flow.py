"""Compare complete canonical PCM/state with music attached on legal replay inputs, in memory."""
from pathlib import Path
import argparse,hashlib,json,re,subprocess,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import replay,package_native as package,music_probe
from tools.quality import run as q


def source():
    text=replay.recovery_source().replace('runtime_capture.Write(std::cout);','').replace('std::cout','std::cerr')
    text='#include <fcntl.h>\n#include <io.h>\n'+text
    marker='machine->dsp.SetTraceObservation(false);'
    assert text.count(marker)==1
    text=text.replace(marker,marker+r'''
        _setmode(_fileno(stdout),_O_BINARY);
        std::unique_ptr<mk2::RemasteredAudio> music;
        uint64_t music_samples=0;int music_peak=0;
        if(std::wstring(argv[4])==L"remaster")music=std::make_unique<mk2::RemasteredAudio>(machine->dsp,
            std::filesystem::path("custom_audio/mk2"),[&](const int16_t*p,size_t n){
                music_samples+=n/2;for(size_t i=0;i<n;++i)music_peak=std::max(music_peak,std::abs(int(p[i])));
            });
        const auto instruction=machine->dsp.music_instruction_;
        uint32_t previous_gain=~0u;
        machine->dsp.music_instruction_=[&,instruction](const auto& d){
            if(d.pc==0x31)std::cerr<<"CUE "<<d.instruction_ticks_<<' '<<d.ar<<'\n';
            if(d.pc==0xa4 && (d.external_pm[0x5fb]>>8)==0){
                const bool active=(d.external_pm[0x388]>>8)||(d.external_pm[0x389]>>8);
                const uint32_t gain=active?(d.external_pm[0x3a0]>>8)*uint32_t(d.dm[0x10e]):0;
                if(gain!=previous_gain){std::cerr<<"GAIN "<<d.instruction_ticks_<<' '<<gain<<'\n';previous_gain=gain;}
            }
            if(instruction)instruction(d);
        };
''')
    marker='[&](uint64_t,const float* pcm,size_t count){'
    assert text.count(marker)==1
    text=text.replace(marker,r'''[&](uint64_t first,const float* pcm,size_t count){
            std::cout.write(reinterpret_cast<const char*>(pcm),count*sizeof(float));
            if(music)music->Feed(first,pcm,count);''')
    marker='        return 0;'
    assert text.count(marker)==1
    text=text.replace(marker,r'''
        if(music && (music->SourceSamples()!=samples || music->OutputSamples()!=(samples-1)*48000/31250+1 ||
                     music_samples!=music->OutputSamples()))throw std::runtime_error("Complete music presentation cardinality differs");
        auto state=machine->dsp.ExecutionState();
        for(auto v:machine->dsp.pm)state.push_back(v);
        for(auto v:machine->dsp.dm)state.push_back(v);
        for(auto v:machine->dsp.external_pm)state.push_back(v);
        for(auto v:machine->dsp.DacBuffer(32768))state.push_back(v);
        for(auto v:machine->dsp.control)state.push_back(v);
        for(auto v:machine->link.ExecutionState())state.push_back(v);
        std::cout.write(reinterpret_cast<const char*>(state.data()),state.size()*sizeof(state[0]));
        std::cerr<<"STATE_BYTES "<<state.size()*sizeof(state[0])<<'\n';
        if(music)std::cerr<<"MUSIC "<<music_samples<<' '<<music->Starts()<<' '<<music->Clipped()<<' '
                         <<music->Limited()<<' '<<music_peak<<'\n';
        return 0;''')
    return text


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe',type=Path);parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--cycles',type=int);args=parser.parse_args()
    if args.report.exists():parser.error('Preserve the existing receipt; select another report')
    capture=replay.read_capture(args.recipe.read_text());cycles=args.cycles or capture['end_cycles']
    report={'passed':False,'scope':'Native observer on/off direct complete canonical PCM and terminal DSP state; legal recipe. No new hardware comparison or whole-song perceptual equivalence.',
            'input_sha256':q.sha(args.recipe),'cycles':cycles,'pcm_saved':False}
    try:
        with q.scratch_tree()as(scratch,cleanup):
            report['cleanup']=cleanup;env=music_probe.environment(scratch)
            report['sources']=package.identities(scratch,env)
            cpp=scratch/'flow.cpp';cpp.write_text(source());exe=scratch/'flow.exe'
            report['harness_sha256']=q.sha(cpp)
            build=q.command([q.DEFAULT_CC,*package.FLAGS,'-fno-access-control','-static',cpp,
                *[q.ROOT/p for p in package.SOURCES if p!='native/mk2/mk2_native_check.cpp'],*package.LIBRARIES,'-o',exe],
                scratch,cwd=q.ROOT,env=env,timeout=240)
            report['build']=q.compact(build);assert build['passed'],build['stdout']
            timeline=scratch/'inputs.txt';timeline.write_text(''.join(f'{t} {v}\n'for t,v in capture['inputs']))
            cmos=scratch/'cmos.bin';cmos.write_bytes(capture['cmos'])
            def run(mode):
                result=subprocess.run([exe,q.ROOT/'roms/mk2','--smoke',str(cycles),mode,'','2000000',timeline,cmos,capture['cmos_sha256']],
                    capture_output=True,cwd=q.ROOT,env=env,timeout=replay.execution_wall_seconds(cycles))
                assert result.returncode==0,result.stderr[-2000:].decode(errors='replace')
                metadata=result.stderr.decode();summary=json.loads(next(line for line in metadata.splitlines()if line.startswith('{')))
                state_bytes=int(re.search(r'STATE_BYTES (\d+)',metadata).group(1))
                assert len(result.stdout)==summary['DAC_samples']*4+state_bytes
                return result.stdout,metadata,summary
            original,a,a_summary=run('original');observed,b,b_summary=run('remaster')
            assert a_summary==b_summary,'Canonical game/DAC summary changed'
            assert original==observed,'Complete canonical PCM or terminal DSP state changed'
            commands=lambda text:[[int(v)for v in line.split()[1:]]for line in text.splitlines()if line.startswith('CUE ')]
            gains=lambda text:[[int(v)for v in line.split()[1:]]for line in text.splitlines()if line.startswith('GAIN ')]
            assert commands(a)==commands(b) and gains(a)==gains(b),'Firmware commands or gain curve changed'
            values=[int(v)for v in re.search(r'MUSIC ([\d ]+)',b).group(1).split()]
            report.update(canonical=a_summary,compared_bytes=len(original),canonical_pcm_and_state_sha256=hashlib.sha256(original).hexdigest(),
                commands=commands(b),gain_changes=gains(b),music=dict(zip(('frames','starts','clipped','limited','sample_peak'),values)))
            assert values[0]==(a_summary['DAC_samples']-1)*48000//31250+1
            # Music starts only for cues whose custom_audio/mk2 slot is filled; an empty folder keeps the arcade music.
            assert values[2]==0 and values[4]<=float(re.search(r'ceiling=([\d.]+);',(q.ROOT/'native/audio/host_gain.hpp').read_text()).group(1))
            assert package.identities(scratch,env)==report['sources'],'Runtime sources changed during test'
        assert not cleanup['exists_after'];report['passed']=True
    except Exception as error:report['error']=repr(error)
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS'if report['passed']else'FAIL',args.report,report.get('error',''),flush=True)
    return 0 if report['passed']else 1


if __name__=='__main__':raise SystemExit(main())
