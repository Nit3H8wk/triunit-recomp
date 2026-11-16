#include "mk5_audio_volume.hpp"
#include <array>
#include <iostream>
#include <stdexcept>
void need(bool value,const char* why){if(!value)throw std::runtime_error(why);}
int main(){try{
 const std::array<int16_t,7> input{{-32768,-12345,-1,0,1,12345,32767}};
 for(auto sample:input){need(mk5audio::ScaleVolume(sample,100)==sample,"100% must preserve every sample");need(mk5audio::ScaleVolume(sample,0)==0,"mute must be exact silence");}
 need(mk5audio::ScaleVolume(-32768,50)==-16384&&mk5audio::ScaleVolume(32767,50)==16383,"half volume signed endpoints");
 need(mk5audio::ParseGameVolume("")==100&&mk5audio::ParseGameVolume("37")==37,"default and explicit volume");
 for(const char* bad:{"-1","101","20junk"," 20","1.5"}){bool failed=false;try{mk5audio::ParseGameVolume(bad);}catch(const std::runtime_error&){failed=true;}need(failed,"invalid volume rejected");}
 std::cout<<"PASS software gain identity, mute, signed endpoints and input validation\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
