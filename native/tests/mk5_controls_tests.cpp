#include "mk5_controls.hpp"
#include <iostream>
#include <stdexcept>
using namespace mk5controls;
void need(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
int main(){try{
 const Config d;Config c;
 need(parse(format(d),c)&&format(c)==format(d),"format/parse round trip");
 c.keys[1][Run]=0x70;c.pad[0][Block]=1u<<20;c.socd=1;c.runAhead=1;c.training=1;Config back;
 need(parse(format(c),back)&&back.keys[1][Run]==0x70&&back.pad[0][Block]==1u<<20&&back.socd==1&&back.runAhead==1&&back.training==1,"edited controls survive the text form");
 for(const char* bad:{"","1,2","zz,"}) {Config x=d;need(!parse(bad,x)&&format(x)==format(d),"invalid text rejected without change");}
 auto text=format(d);text.back()='2';need(!parse(text,c),"training out of range rejected");
 text=format(c);text.resize(text.size()-2);need(parse(text,back)&&back.runAhead==1&&back.training==0,"a profile from before training keeps run-ahead, training off");
 text.back()='2';need(!parse(text,c),"run-ahead out of range rejected");
 text=format(c);text.resize(text.size()-4);need(parse(text,back)&&back.socd==1&&back.runAhead==0&&back.training==0,"a profile from before run-ahead keeps SOCD, run-ahead off");
 text.back()='2';need(!parse(text,back),"SOCD mode out of range rejected");
 need(!parse(format(c)+",0",back),"an extra field is rejected");
 // Neutral: opposite directions cancel each other, other actions pass.
 Socd s;const uint32_t lr=1u<<Left|1u<<Right|1u<<HighPunch;
 need(clean(lr,0,s)==(1u<<HighPunch),"neutral SOCD releases both directions");
 // Last input wins: hold Left, add Right -> Right; keep both -> still Right; release Right -> Left.
 Socd l;need(clean(1u<<Left,1,l)==(1u<<Left),"single direction passes");
 need(clean(1u<<Left|1u<<Right,1,l)==(1u<<Right),"newest direction wins");
 need(clean(1u<<Left|1u<<Right,1,l)==(1u<<Right),"winner kept while both are held");
 need(clean(1u<<Left,1,l)==(1u<<Left),"release returns to the held direction");
 Socd both;need(clean(1u<<Up|1u<<Down,1,both)==0,"both pressed together stay neutral");
 // HID buttons: 1-10 on the common layout, 11-24 on their own bits, others ignored.
 need(hid_button(1)==X&&hid_button(10)==START&&hid_button(11)==1u<<18&&hid_button(24)==1u<<31&&!hid_button(0)&&!hid_button(25),"HID button table");
 // Defaults: LB runs (and blocks without Run), RB blocks; Run never drives an electrical bit of the shared word.
 need(from_pad(d,0,LB,0)==(1u<<Run)&&from_pad(d,1,RT,0)==(1u<<Block),"default shoulders");
 need(shared(1u<<Run,0,0xffffffffu,true)==~(1u<<5)&&shared(1u<<Run,0,0xffffffffu,false)==0xffffffffu,"Run blocks only where requested");
 std::array<bool,256> keys{};keys['C']=true;need(from_keys(d,0,keys)==(1u<<Run),"default P1 Run key");
 std::cout<<"PASS controls: text form, SOCD neutral and last input, HID buttons, Run\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
