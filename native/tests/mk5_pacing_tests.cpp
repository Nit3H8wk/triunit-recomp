#include "mk5_timing.hpp"
#include <iostream>
#include <stdexcept>
int main(){try{
 constexpr uint64_t interval=18279250,origin=1000000000;
 uint64_t deadline=0,now=origin,old_deadline=0,lost=0;
 for(unsigned frame=0;frame<30000;++frame){
  // A producer that is comfortably fast, with occasional host scheduling stalls.
  now=std::max(now,deadline);if(frame&&frame%500==0)now+=109000000;
  const auto next=mk5timing::ProducerDeadline(deadline,now,interval,true);
  if(next!=origin+(uint64_t(frame)+1)*interval)throw std::runtime_error("output-clock deadline discarded guest time after host stall");
  deadline=next;
  if(!old_deadline||now>old_deadline+interval){lost+=old_deadline?now-old_deadline:0;old_deadline=now;}old_deadline+=interval;
  now+=6000000;
 }
 if(!lost)throw std::runtime_error("fixture did not reproduce old rebase drift");
 if(mk5timing::ProducerDeadline(100,1000,10,false)!=1010)throw std::runtime_error("silent standalone presentation should still rebase");
 std::cout<<"PASS 30000 guest deadlines, 59 scheduling stalls, no lost output-clock time; old policy lost_ticks="<<lost<<"\n";
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
