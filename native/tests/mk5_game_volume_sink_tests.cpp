// Real WaveOutSink packets; only WinMM is replaced, events remain real Win32 handles.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <mmsystem.h>
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace {
int devices=0,headers=0,opens=0,event_opens=0;
unsigned output_channels=0;
std::vector<int16_t> captured;
std::vector<size_t> packet_frames;
void need(bool value,const char* why){if(!value)throw std::runtime_error(why);}
HANDLE create_event(LPSECURITY_ATTRIBUTES attributes,BOOL manual,BOOL initial,LPCWSTR name){
 ++event_opens;return CreateEventW(attributes,manual,initial,name);
}
MMRESULT open_device(LPHWAVEOUT device,UINT_PTR,LPCWAVEFORMATEX format,DWORD_PTR,DWORD_PTR,DWORD){
 need(format->wFormatTag==WAVE_FORMAT_PCM&&format->nSamplesPerSec==48000&&format->wBitsPerSample==16,"PCM format unchanged");
 output_channels=format->nChannels;need(output_channels==1||output_channels==2,"mono/stereo channel format");
 *device=reinterpret_cast<HWAVEOUT>(1);++devices;++opens;return 0;
}
MMRESULT pause_device(HWAVEOUT){return 0;}
MMRESULT prepare(HWAVEOUT,LPWAVEHDR header,UINT){++headers;header->dwFlags|=WHDR_PREPARED;return 0;}
MMRESULT unprepare(HWAVEOUT,LPWAVEHDR,UINT){--headers;return 0;}
MMRESULT close_device(HWAVEOUT){--devices;return 0;}
MMRESULT reset_device(HWAVEOUT){return 0;}
MMRESULT restart_device(HWAVEOUT){return 0;}
MMRESULT write_device(HWAVEOUT,LPWAVEHDR header,UINT size){
 need(size==sizeof(WAVEHDR)&&header->dwBufferLength%(output_channels*2)==0,"complete PCM frames in packet");
 const auto* samples=reinterpret_cast<const int16_t*>(header->lpData);
 captured.insert(captured.end(),samples,samples+header->dwBufferLength/2);
 packet_frames.push_back(header->dwBufferLength/(output_channels*2));
 header->dwFlags|=WHDR_DONE;return 0;
}
DWORD handles(){DWORD count=0;need(GetProcessHandleCount(GetCurrentProcess(),&count)!=0,"handle measurement");return count;}
}
#define CreateEventW create_event
#define waveOutOpen open_device
#define waveOutPause pause_device
#define waveOutPrepareHeader prepare
#define waveOutUnprepareHeader unprepare
#define waveOutClose close_device
#define waveOutReset reset_device
#define waveOutWrite write_device
#define waveOutRestart restart_device
#include "../src/mk5_audio_output.cpp"

int main(){try{
 _putenv_s("MK1_AUDIO_LATENCY","safe");_putenv_s("MK1_GAME_VOLUME","");
 {mk5audio::WaveOutSink warmup;}
 const auto baseline=handles();unsigned cases=0;
 for(const unsigned channels:{1u,2u})for(const auto* setting:{"","100","0","37","50"}){
  _putenv_s("MK1_GAME_VOLUME",setting);const unsigned percent=*setting?unsigned(std::atoi(setting)):100;
  constexpr size_t frames=960*11+17;
  constexpr std::array<int16_t,16> pattern={-32768,32767,-1,1,0,-30001,30001,-101,101,-32767,32766,-99,99,-17,17,12345};
  std::vector<int16_t> input(frames*channels);
  for(size_t frame=0;frame<frames;++frame)for(unsigned channel=0;channel<channels;++channel)
   input[frame*channels+channel]=pattern[(frame*3+channel*7)%pattern.size()];
  const auto original=input;captured.clear();packet_frames.clear();
  {
   mk5audio::WaveOutSink sink(channels);
   need(devices==1&&headers==8,"sink owns complete prepared resources");
   need(sink.QueueCapacityMs()==160&&sink.StartupReserveMs()==140,"volume cannot alter queue timing");
   sink.Push(nullptr,0);sink.Push(input.data(),31*channels);
   sink.Push(input.data()+31*channels,(960*9+5)*channels);
   sink.Push(input.data()+(31+960*9+5)*channels,(frames-31-960*9-5)*channels);
   sink.Drain();sink.Drain();
   need(sink.Submitted()==frames&&sink.Completed()==frames,"all original frames delivered exactly once");
   need(captured.size()==input.size()&&packet_frames.size()==12,"full packet wrap and partial tail delivered");
   for(size_t i=0;i<packet_frames.size();++i)need(packet_frames[i]==(i<11?960:17),"packet boundaries unchanged");
   need(input==original,"output volume must not change guest source PCM");
   if(percent==100)need(std::memcmp(captured.data(),input.data(),input.size()*sizeof(int16_t))==0,"100 percent is byte-identical mono/stereo");
   for(size_t i=0;i<input.size();++i){
    const int sample=input[i];const int magnitude=(sample<0?-sample:sample)*int(percent)/100;
    const int expected=sample<0?-magnitude:magnitude;
    need(captured[i]==expected,"scaled packet samples preserve signed truncation, endpoints and channel order");
   }
  }
  need(devices==0&&headers==0&&handles()==baseline,"successful sink resources return to baseline");++cases;
 }
 for(const auto* setting:{"-1","101","37x","1.5"," 50","+50","999999999999999999999999"}){
  _putenv_s("MK1_GAME_VOLUME",setting);const auto before_opens=opens,before_events=event_opens;
  bool rejected=false;try{mk5audio::WaveOutSink invalid;}catch(const std::runtime_error&){rejected=true;}
  need(rejected&&opens==before_opens&&event_opens==before_events,"invalid volume rejected before device/event creation");
  need(devices==0&&headers==0&&handles()==baseline,"invalid volume leaves no resources");++cases;
 }
 std::cout<<"PASS: "<<cases<<" real sink cases, exact mono/stereo packets,0/37/50/100/default gain, source/channel/timing preservation and invalid-input resource boundary\n";
 return 0;
}catch(const std::exception& error){std::cerr<<"FAIL: "<<error.what()<<'\n';return 1;}}
