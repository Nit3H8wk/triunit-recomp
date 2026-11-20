#include "mk5_training.hpp"
#include "mk5_controls.hpp"
#include <iostream>
#include <stdexcept>
using namespace mk5training;
void need(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
int main(){try{
 using A=mk5controls::Action;
 History h;h.Push(0,1u<<A::Right);h.Push(0,1u<<A::Right);h.Push(0,1u<<A::Right|1u<<A::HighPunch|1u<<A::Start);
 need(h.count[0]==2&&h.rows[0][0].held==(1u<<A::Right|1u<<A::HighPunch)&&h.rows[0][0].frames==1&&h.rows[0][1].frames==2,
      "a change opens a row, a repeat counts frames; start is not shown");
 for(unsigned i=0;i<200;++i)h.Push(1,0);
 need(h.count[1]==1&&h.rows[1][0].frames==kMaxFrames,"the frame count stops at 99");
 for(unsigned i=0;i<20;++i)h.Push(0,i&1?0:1u<<A::Up);
 need(h.count[0]==kRows,"only the newest rows are kept");
 std::vector<uint32_t> o;Draw(o,400,254,History{},{});
 need(o.size()==400*254&&std::all_of(o.begin(),o.end(),[](uint32_t c){return c==0;}),"empty overlay leaves the game visible");
 Draw(o,400,254,History{},{{10,20,30,40,Body},{-5,-5,10,10,Strike}});
 need(o[20*400+10]==(0xff000000u|kBodyColor)&&o[21*400+11]==(0x50000000u|kBodyColor)&&o[59*400+39]==(0xff000000u|kBodyColor)
      &&o[60*400+10]==0&&o[4*400+4]==(0xff000000u|kStrikeColor)&&o[0]==(0x50000000u|kStrikeColor),"boxes: outline, fill, clipped at the edge");
 History one;one.Push(1,1u<<A::Left);Draw(o,400,254,one,{});
 need(o[44*400+(400-6-71)]==0xa0000000u&&o[44*400+5]==0,"P2 panel on the right, P1 empty");
 std::cout<<"PASS training overlay\n";return 0;
}catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<"\n";return 1;}}
