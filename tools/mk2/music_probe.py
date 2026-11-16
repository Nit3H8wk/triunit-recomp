"""Sound-board research only: authenticated instructions, PCM retained in memory."""
from pathlib import Path
import os, subprocess, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q

PROBE = r'''
#include "probe_adsp.hpp"
#include "probe_music.hpp"
#include "mk5_program.hpp"
#include <iostream>
#include <fcntl.h>
#include <io.h>
int main(int argc,char**argv) {try {
    const auto rom=mk2::LoadDcsDataRoms(argv[1]);
    mk2::DcsLink link;mk2::AdspBoot dsp(mk2::DecodeDcsBoot({rom.begin(),rom.begin()+4096}),link,rom);
    // Isolated sound-board diagnostic, never linked into the game package.
    dsp.live_host_domain_=true;dsp.main_horizon_=1000000000;dsp.live_instruction_ceiling_=2000000000;
    dsp.SetTraceObservation(false);_setmode(_fileno(stdout),_O_BINARY);
    if(std::string(argv[2])=="stress") {
        mk2::RemasteredMix mix;
        for(unsigned n=0;n<96000;++n){
            const auto stereo=mix.Render(n%4<2?.5f:-.5f,{0,0});
            std::cout.write(reinterpret_cast<const char*>(stereo.data()),sizeof(stereo));
        }
        return 0;
    }
    if(std::string(argv[2])=="levels") {
        std::vector<int16_t> canonical,presented;
        mk2::DcsAudio original([&](const int16_t*p,size_t n){canonical.assign(p,p+n);});
        mk2::RemasteredAudio player(dsp,argv[3],[&](const int16_t*p,size_t n){presented.assign(p,p+n);});
        for(uint64_t first=0;first<31250;) {
            std::array<float,512> source{};const auto count=std::min<uint64_t>(512,31250-first);
            for(size_t n=0;n<count;++n)source[n]=first+n<10000?.002f:first+n<14000?2.f:first+n<18000?-2.f:.002f;
            original.Feed(first,source.data(),count);player.Feed(first,source.data(),count);
            for(size_t n=0;n<canonical.size();++n){const int16_t row[]{canonical[n],presented[n*2],presented[n*2+1]};std::cout.write(reinterpret_cast<const char*>(row),sizeof(row));}
            first+=count;
        }
        std::cerr<<"clipped="<<player.Clipped()<<"\n";return 0;
    }
    uint64_t tick=0,deadline=0;bool ready=false,high=false,low=false;
    const auto command=unsigned(std::stoul(argv[2],nullptr,0));
    const auto duration=argc>3?std::stoul(argv[3]):8;
    uint64_t began=0;
    std::unique_ptr<mk2::DcsEffects> effects;
    std::unique_ptr<mk2::RemasteredAudio> player;
    std::unique_ptr<mk2::DcsAudio> speaker;
    const bool envelope=argc>4 && std::string(argv[4])=="envelope";
    if(argc>4 && (std::string(argv[4])=="effects" || envelope))effects=std::make_unique<mk2::DcsEffects>(dsp);
    if(argc>4 && std::string(argv[4])=="play")player=std::make_unique<mk2::RemasteredAudio>(dsp,argv[5],[](const int16_t*p,size_t n){std::cout.write(reinterpret_cast<const char*>(p),n*2);});
    if(argc>4 && std::string(argv[4])=="speaker")speaker=std::make_unique<mk2::DcsAudio>([](const int16_t*p,size_t n){std::cout.write(reinterpret_cast<const char*>(p),n*2);});
    bool effect_high=false,effect_low=false,mixed=false;unsigned following=0x221;uint64_t effect_at=0;
    for(int n=5;n<argc;++n)if(std::string(argv[n])=="mix")mixed=true;else if(std::string(argv[n]).rfind("next=",0)==0){mixed=true;following=unsigned(std::stoul(std::string(argv[n]).substr(5),nullptr,0));}
    dsp.SetDacObserver([&](uint64_t first,const float*p,size_t n){if(player)player->Feed(first,p,n);else if(speaker)speaker->Feed(first,p,n);else if(low){
        if(!effects)std::cout.write(reinterpret_cast<const char*>(p),n*sizeof(float));
        else {std::array<float,512> e{},gains{};std::array<uint64_t,512> tags{};effects->Read(first,n,e.data(),tags.data(),gains.data());
            for(size_t at=0;at<n;++at){const float pair[]{p[at],e[at],gains[at]};std::cout.write(reinterpret_cast<const char*>(pair),(envelope?3:2)*sizeof(float));}}
    }});
    dsp.rom_bank=1;dsp.LoadBootPage();dsp.rebooted_=true;dsp.ResetCore();
    while(tick<100000000ULL*(duration+2)) {
        const auto serial=dsp.SerialEventCount();
        dsp.SetInstructionTicks(tick);dsp.Step();link.Synchronize();dsp.ApplyPendingReset();tick+=10;
        if(dsp.SerialEventCount()!=serial&&dsp.sport_enabled)deadline=tick-10+768000;
        if(deadline&&tick>=deadline){
            try {dsp.SportTransfer(deadline);}catch(...){std::cerr<<"tick "<<tick<<" pc "<<dsp.pc<<" imask "<<unsigned(dsp.imask)<<" irq "<<dsp.sport_irq1_asserted<<" base "<<dsp.sport_base<<" reboot "<<dsp.rebooted_<<'\n';throw;}
            if(dsp.sport_irq1_asserted)dsp.ClearSportIrq1(deadline+10);
            deadline+=768000;
        }
        if(tick%2000000==0)dsp.DacUpdate(tick);
        if(dsp.rebooted_&&dsp.pc==0x136&&!dsp.pc_sp&&!dsp.loop_sp)ready=true;
        if(ready&&!high){link.HostWrite(0x01d01030,0x100|(command>>8));link.Synchronize();high=true;began=tick;}
        if(high&&!low&&tick>=began+10000&&!link.Irq2Asserted()){
            link.HostWrite(0x01d01030,0x100|(command&255));link.Synchronize();low=true;
        }
        if(mixed && low && !effect_high && tick>=began+50000000){
            link.HostWrite(0x01d01030,0x100|(following>>8));link.Synchronize();effect_high=true;effect_at=tick;
        }
        if(effect_high&&!effect_low&&tick>=effect_at+10000&&!link.Irq2Asserted()){
            link.HostWrite(0x01d01030,0x100|(following&255));link.Synchronize();effect_low=true;
        }
        if(low&&tick>=began+duration*100000000ULL){dsp.DacUpdate(tick);break;}
    }
    if(!low)throw std::runtime_error("sound board never became ready");
    auto state=dsp.ExecutionState();for(auto v:dsp.pm)state.push_back(v);for(auto v:dsp.dm)state.push_back(v);
    for(auto v:dsp.external_pm)state.push_back(v);for(auto v:dsp.DacBuffer(32768))state.push_back(v);
    for(auto v:dsp.control)state.push_back(v);for(auto v:link.ExecutionState())state.push_back(v);
    const auto* bytes=reinterpret_cast<const uint8_t*>(state.data());
    std::cerr<<"command="<<command<<" ticks="<<tick<<" pc="<<dsp.pc<<" state="<<Sha256({bytes,bytes+state.size()*8})<<"\n";
    if(player)std::cerr<<"starts="<<player->Starts()<<" clipped="<<player->Clipped()<<" limited="<<player->Limited()<<" samples="<<player->OutputSamples()<<"\n";
    for(int n=4;n<argc;++n)if(std::string(argv[n])=="--state"){
        _setmode(_fileno(stderr),_O_BINARY);
        std::cerr.write(reinterpret_cast<const char*>(state.data()),state.size()*sizeof(state[0]));
        break;
    }
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
'''

def environment(scratch):
    sanitizer=os.environ.get('MK2_MUSIC_SANITIZER','none')
    cc=q.ASAN_CC if sanitizer=='address' else q.DEFAULT_CC
    env=dict(os.environ,PATH=str(cc.parent)+os.pathsep+os.environ['PATH'],TEMP=str(scratch),TMP=str(scratch))
    if sanitizer=='address':env['ASAN_OPTIONS']='halt_on_error=1:abort_on_error=0:exitcode=86:detect_leaks=0:disable_coredump=1:symbolize=0'
    return env

def build(scratch):
    directory=q.ROOT/'native/mk2'
    header=(directory/'mk2_adsp.hpp').read_text().replace('class AdspBoot {','struct AdspBoot {')
    (scratch/'probe_adsp.hpp').write_text(header)
    cpp=(directory/'mk2_adsp.cpp').read_text().replace('#include "mk2_adsp.hpp"','#include "probe_adsp.hpp"')
    (scratch/'probe_adsp.cpp').write_text(cpp)
    (scratch/'probe_music.hpp').write_text((directory/'mk2_music.hpp').read_text().replace('"mk2_adsp.hpp"','"probe_adsp.hpp"'))
    (scratch/'probe_music.cpp').write_text((directory/'mk2_music.cpp').read_text().replace('"mk2_music.hpp"','"probe_music.hpp"').replace('"../runtime/mk2_music_manifest.hpp"','"'+(q.ROOT/'native/runtime/mk2_music_manifest.hpp').as_posix()+'"'))
    (scratch/'probe.cpp').write_text(PROBE)
    exe=scratch/'probe.exe'
    sanitizer=os.environ.get('MK2_MUSIC_SANITIZER','none')
    if sanitizer not in('none','undefined','address'):raise ValueError('unknown music sanitizer')
    cc=q.ASAN_CC if sanitizer=='address' else q.DEFAULT_CC
    env=environment(scratch)
    flags=['-O2','-static'] if sanitizer=='none' else ['-O1','-g','-fno-omit-frame-pointer','-fsanitize='+sanitizer,'-fno-sanitize-recover=all']
    if sanitizer=='undefined':flags+=['-fsanitize-undefined-trap-on-error','-fno-sanitize=vptr']
    if sanitizer!='none':
        probe=scratch/'negative.cpp';negative=scratch/'negative.exe'
        probe.write_text('#include <climits>\nint main(int argc,char**){volatile int n=INT_MAX;n+=argc;return n;}\n'if sanitizer=='undefined'else
                         '#include <cstdlib>\nint main(int argc,char**){volatile char*p=(char*)malloc(argc);p[argc]=0;free((void*)p);}\n')
        result=q.command([cc,'-std=c++17',*flags,probe,'-o',negative],scratch,env=env)
        if not result['passed']:raise RuntimeError(result['stdout'])
        if not q.negative_control_detected(q.command([negative],scratch,env=env),sanitizer):raise RuntimeError('music sanitizer did not detect its negative control')
    result=q.command([cc,'-std=c++17',*flags,'-ffunction-sections','-fdata-sections',
        '-I'+str(directory),'-I'+str(q.ROOT/'native/include'),scratch/'probe.cpp',scratch/'probe_adsp.cpp',
        scratch/'probe_music.cpp',directory/'mk2_dcs.cpp',q.ROOT/'native/src/mk5_program.cpp','-lbcrypt','-Wl,--gc-sections','-o',exe],scratch,env=env,timeout=120)
    if not result['passed']:raise RuntimeError(result['stdout'])
    return exe

def identify(exe):
    import json,numpy as np
    from scipy import signal
    def features(x,rate):
        x=signal.resample_poly(x,8000,rate)
        _,_,z=signal.stft(x,8000,nperseg=2048,noverlap=1536)
        f=np.fft.rfftfreq(2048,1/8000);ids=np.flatnonzero((f>65)&(f<2500))
        notes=np.round(69+12*np.log2(f[ids]/440)).astype(int)%12
        mag=np.abs(z)[ids];c=np.stack([mag[notes==i].sum(axis=0)for i in range(12)])
        c=np.log1p(c*100);c-=c.mean(axis=0)
        return c/np.maximum(np.linalg.norm(c,axis=0),1e-6)
    tracks={}
    for p in(q.ROOT/'Musicas MK2 Remaster').glob('*.mp3'):
        pcm=subprocess.run(['ffmpeg','-v','error','-i',str(p),'-ac','1','-ar','8000','-f','f32le','-'],capture_output=True,check=True).stdout
        tracks[p.stem]=features(np.frombuffer(pcm,dtype='<f4'),8000)
    rows=[]
    calibrate='--calibrate'in sys.argv
    commands=(1,2,4,5,6,9,10,13,14,17,18,21,22,25,26,61,66) if calibrate else (range(1,29) if '--all'in sys.argv else (1,3,5,9,13,17,21,25,50,52,54,61,66))
    for cmd in commands:
        p=subprocess.run([exe,q.ROOT/'roms/mk2',str(cmd),'24' if calibrate else '4' if '--all'in sys.argv else '8'],capture_output=True)
        if p.returncode:print(cmd,p.stderr.decode(),flush=True);continue
        c=features(np.frombuffer(p.stdout,dtype='<f4'),31250);scores={}
        for name,d in tracks.items():
            score=sum(signal.correlate(d[i],c[i],mode='valid',method='fft')for i in range(12))/c.shape[1]
            where=int(np.argmax(score));scores[name]={'score':round(float(score[where]),5),'offset_seconds':round(where*512/8000,3)}
            if calibrate:
                peaks=signal.find_peaks(score,distance=round(2*8000/512))[0]
                peaks=sorted(set([0,len(score)-1,*peaks]),key=lambda n:score[n],reverse=True)[:8]
                scores[name]['peaks']=[{'offset':round(int(n)*512/8000,3),'score':round(float(score[n]),5)}for n in peaks]
        row={'command':cmd,'scores':scores};rows.append(row)
        if calibrate:print(cmd,sorted(scores.items(),key=lambda kv:kv[1]['score'],reverse=True)[:1],flush=True)
        else:print(json.dumps(row),flush=True)
    dest=q.ROOT/'build/native/mk2-remastered';dest.mkdir(exist_ok=True)
    (dest/('identification-calibrated.json'if calibrate else 'identification.json')).write_text(json.dumps(rows,indent=2)+'\n')

if __name__=='__main__':
    with q.scratch_tree() as(scratch,cleanup):
        exe=build(scratch)
        if '--identify'in sys.argv:identify(exe)
        else:
            result=subprocess.run([exe,q.ROOT/'roms/mk2',sys.argv[1]if len(sys.argv)>1 else '5','3'],capture_output=True)
            print(result.returncode,len(result.stdout),result.stderr.decode())
    print('scratch removed',not cleanup['exists_after'])
