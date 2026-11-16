#include "../audio/host_gain.hpp"
#include <cmath>
#include <iostream>
#include <vector>
static void need(bool value,const char* why){if(!value)throw std::runtime_error(why);}
int main(){try{
 const double six=20*std::log10(2.0);
 mk5audio::HostGain exact(six);
 for(double v:{-12000.0,-1.0,0.0,1.0,12000.0})need(exact.Render<1>({v})[0]==int16_t(v*2),"gain is not exact");
 const double below=std::floor(mk5audio::HostGain::ceiling/2);   // lands at or under the ceiling after the gain
 need(exact.Render<2>({below,-below})==std::array<int16_t,2>{int16_t(below*2),int16_t(-below*2)},"stereo gain under the ceiling changed");
 need(!exact.Limited() && !exact.Clipped(),"limiter acted under the ceiling");
 const auto over=exact.Render<2>({20000.0,-10000.0});
 need(std::abs(over[0])<=mk5audio::HostGain::ceiling && over[0]>=mk5audio::HostGain::ceiling-1,"limiter missed the ceiling");
 need(std::abs(over[0]+2*over[1])<=2,"limiter changed the stereo balance");
 need(exact.Limited()==1 && !exact.Clipped(),"one frame over the ceiling is one action, no saturation");
 for(unsigned n=0;n<96000;++n)exact.Render<1>({0.0});
 const auto actions=exact.Limited();
 need(exact.Render<1>({1000.0})[0]==2000 && exact.Limited()==actions,"limiter did not release to unity");
 mk5audio::HostGain unity(0.0);
 const std::vector<int16_t> cut{32767,-32768,100,-100};std::vector<int16_t> out(cut.size());
 unity.Process(cut.data(),out.data(),cut.size(),2);
 need(unity.Clipped()==2,"upstream full-scale samples are not counted as saturated");
 // Actions count every frame the limiter gain is under unity, the release included.
 need(unity.Limited()==2 && std::abs(out[0])<=mk5audio::HostGain::ceiling && out[2]<100 && out[2]>85,"cut input not limited under the ceiling");
 need(std::abs(20*std::log10(mk5audio::HostGain::ceiling/32768)+1.1)<.001,"ceiling is not -1.1 dBFS");
 bool rejected=false;try{unity.Render<1>({std::nan("")});}catch(const std::invalid_argument&){rejected=true;}
 need(rejected,"non-finite mix accepted");
 std::cout<<"PASS host gain exact, limiter only over the ceiling, release, balance and saturation/limiter counters\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
