#include "mk5_crt.hpp"
#include "mk5_video.hpp"
#include "mk5_video_presets.hpp"
#include "mk5_gamepad.hpp"
#include "mk5_bezel.hpp"
#include "mk5_timing.hpp"
#include "mk5_color.hpp"
#include <iostream>
#include <stdexcept>
void need(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
int main(){try{
 using mk5video::Sampling;
 const auto same_rgb=[](const std::array<float,3>& a,const std::array<float,3>& b){
  return std::abs(a[0]-b[0])<1e-5f&&std::abs(a[1]-b[1])<1e-5f&&std::abs(a[2]-b[2])<1e-5f;
 };
 // 3x ScaleFX output fitted into a 960x720 viewport has an effective prescale of 1 on both axes.
 const auto edge=[](int x,int y){return std::array<float,3>{float(x>=599),float(y>=380),0};};
 const float u=479.5f/960,v=359.5f/720;
 const auto sharp=mk5video::reconstruct(Sampling::sharp_bilinear,u,v,1200,762,960,720,edge);
 const auto linear=mk5video::reconstruct(Sampling::linear,u,v,1200,762,960,720,edge);
 need(same_rgb(sharp,linear)&&std::abs(sharp[0]-.875f)<1e-5f,"effective 1x sharp bilinear must retain the ordinary bilinear ramp");
 // A 4x4 source uses 3x and 4x nearest prescales before fitting the fractional target.
 const auto source=[](int x,int y){
  return std::array<float,3>{float(x>=2),float(y>=2),float(std::clamp(x,0,3)+std::clamp(y,0,3))/6};
 };
 for(int y=0;y<17;++y)for(int x=0;x<13;++x){
  const float u=(x+.5f)/13,v=(y+.5f)/17;
  const auto want=mk5video::reconstruct(Sampling::linear,u,v,12,16,13,17,[&](int sx,int sy){return source(sx/3,sy/4);});
  const auto got=mk5video::reconstruct(Sampling::sharp_bilinear,u,v,4,4,13,17,source);
  need(same_rgb(got,want),"sharp bilinear above 2x must preserve nearest plateaus and continuous edge ramps");
 }
 mk5crt::Settings crt;crt.load([](const char* key){return std::string(key)=="MK1_CRT_PRESET"?std::string("energy"):std::string();});
 need(crt.enabled()&&crt.gain==1&&crt.gamma_in==crt.gamma_out,"energy preset must have neutral gain and gamma");
 mk5crt::Settings pvm;pvm.load([](const char* key){return std::string(key)=="MK1_CRT_PRESET"?std::string("pvm"):std::string();});
 need(pvm.enabled()&&pvm.preset=="pvm"&&pvm.mask_strength>0&&pvm.horizontal_blend>.18f,"distinct PVM presentation preset");
 need(mk5video::presets.size()>9&&std::wstring(mk5video::presets[9].crt)==L"phosphor","append CRT / Fosforo without changing saved preset IDs");
 mk5crt::Settings phosphor;
 phosphor.load([](const char* key){return std::string(key)=="MK1_CRT_PRESET"?std::string("phosphor"):std::string();});
 need(phosphor.enabled()&&phosphor.mask_strength==.22f&&phosphor.mask_pitch==3,"approved RGB aperture grille profile");
 for(int scale:{4,8})for(float light:{0.f,.18f,.94f,1.f}){
  std::vector<std::array<float,3>> row;
  std::array<float,3> mean{};
  for(int y=0;y<scale;++y){
   mk5crt::phosphor_reference_row(phosphor,282,y,6,scale,3,1,[light](int,int,unsigned){return light;},row);
   if(light==.18f)for(unsigned lane=0;lane<3;++lane)
    need(row[lane][lane]>row[lane][(lane+1)%3],"RGB aperture grille concentrates light in its own stripe");
   for(unsigned x=0;x<3;++x)for(unsigned c=0;c<3;++c)mean[c]+=mk5crt::srgb_decode(row[x][c])/(3*scale);
  }
  for(float channel:mean)need(std::abs(channel-light)<1e-6f,"scanline and mask preserve the linear channel budget, including highlights");
 }
 double mean=0;constexpr float level=.1f;for(unsigned y=0;y<10000;++y)mean+=mk5crt::reference(crt,.5f,(40+(y+.5f)/10000.f)/100,100,10,100,100,0,[](int,int,unsigned){return level;})/255;
 mean/=10000;need(std::abs(std::pow(mean,crt.gamma_out)-level)<.025,"energy profile retains shadow detail without boost");
 BootDiInputs base{};base.in01=0xffffffff;base.in2_dsw=0x1234ffff;
 for(unsigned r=0;r<256;++r){std::array<float,3> rgb{{r/255.f,(255-r)/255.f,.3f}};need(mk5color::apply(rgb,0,1)==rgb,"Original/100% must be identity");}
 for(int mode=0;mode<3;++mode)need(mk5color::apply({{0,0,0}},mode,1)==std::array<float,3>{{0,0,0}},"all color settings preserve exact black");
 XINPUT_GAMEPAD pad{};need(mk5pad::map(pad,0,base).in01==base.in01,"disconnected/released pad neutral");
 mk5pad::Ports ports;ports.update({{true,true,false,false}});need(ports.slots[0]==0&&ports.slots[1]==1,"initial P1/P2 assignment");
 ports.update({{false,true,false,false}});need(ports.slots[0]==-1&&ports.slots[1]==1,"disconnecting P1 must leave P2 on its original port");
 ports.update({{true,true,false,false}});need(ports.slots[0]==0&&ports.slots[1]==1,"reconnecting P1 must preserve P2");
 mk5pad::Ports late;late.update({{false,false,false,true}});late.update({{true,false,false,true}});need(late.slots[0]==3&&late.slots[1]==0,"new lower-index controller must not steal P1");
 const WORD buttons[]={XINPUT_GAMEPAD_DPAD_UP,XINPUT_GAMEPAD_DPAD_DOWN,XINPUT_GAMEPAD_DPAD_LEFT,XINPUT_GAMEPAD_DPAD_RIGHT,XINPUT_GAMEPAD_X,XINPUT_GAMEPAD_LEFT_SHOULDER,XINPUT_GAMEPAD_Y,XINPUT_GAMEPAD_A,XINPUT_GAMEPAD_B,XINPUT_GAMEPAD_BACK,XINPUT_GAMEPAD_START};
 const unsigned p1[]={0,1,2,3,4,5,6,28,29,16,18},p2[]={8,9,10,11,12,13,14,25,26,17,21};
 for(unsigned i=0;i<11;++i){pad={};pad.wButtons=buttons[i];for(unsigned p=0;p<2;++p){auto value=mk5pad::map(pad,p,base);need(value.in01==(0xffffffffu^(1u<<(p?p2[i]:p1[i]))),"pad must drive exactly one original electrical bit");need(value.in2_dsw==base.in2_dsw,"pad must preserve DSW");}}
 pad={};pad.sThumbLX=16000;need(mk5pad::map(pad,0,base).in01==base.in01,"stick deadzone neutral");pad.sThumbLX=16001;need(mk5pad::map(pad,0,base).in01==0xfffffff7,"stick direction");
 pad={};pad.bRightTrigger=128;need(mk5pad::map(pad,1,base).in01==0xffffdfff,"trigger block P2");
 unsigned painted=0;mk5bezel::draw(1920,1080,240,0,1680,1080,[&](int l,int t,int r,int b,float,float,float){need(l>=0&&r<=1920&&t>=0&&b<=1080,"bezel bounded");need(r<=240||l>=1680,"bezel never covers game pixels");++painted;});need(painted>10,"visible bezel panels");
 mk5timing::Stats stats;for(unsigned i=0;i<100;++i)stats.observe(1000+i*18279,1000000);need(stats.n==99&&std::abs(stats.sum/stats.n-18.279)<.001,"native cadence statistics");
 for(unsigned hz:{60u,120u,144u,240u}){mk5timing::Cadence clock;clock.interval=1000000/hz;unsigned shown=0;uint64_t last=0;
  for(uint64_t us=1000;us<10001000;us+=100){if(clock.due(us)){if(last)need(us-last>=clock.interval-100,"presentation must stay on desktop cadence");last=us;clock.presented(us);++shown;}}
  need(shown<=hz*10+1&&shown>=hz*10-1,"desktop cadence independent of54.7Hz source");
 }
 std::cout<<"PASS energy, original P1/P2 electrical ports, release/deadzone, triggers, bezel clipping, native timing\n";return 0;
}catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}}
