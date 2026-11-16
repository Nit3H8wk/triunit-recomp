#pragma once
#include <array>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <sstream>
namespace mk5timing {
// Audio consumes every guest sample at a fixed rate. Rebasing a late producer
// permanently loses elapsed guest time and gradually drains its output queue.
// Keep each deadline: overdue guest frames still execute, while the existing
// presentation mailbox may coalesce host images. Silent standalone runs retain
// their previous rebase policy.
inline uint64_t ProducerDeadline(uint64_t next,uint64_t now,uint64_t interval,bool output_clock){
 if(!next || (!output_clock && now>next+interval))next=now;
 return next+interval;
}
struct Cadence {
 uint64_t next=0,interval=1;
 bool due(uint64_t now)const{return now>=next;}
 void presented(uint64_t now){if(!next)next=now+interval;else if(due(now))next+=((now-next)/interval+1)*interval;}
};
// Bounded histogram: 0.25ms buckets up to 128ms. Never retain frame dumps.
struct Stats {
 std::array<uint64_t,513> bins{};uint64_t n=0,previous=0;double sum=0,squares=0,maximum=0;
 void duration(uint64_t ticks,uint64_t frequency){const double ms=double(ticks)*1000/double(frequency);++n;sum+=ms;squares+=ms*ms;maximum=std::max(maximum,ms);++bins[std::min<size_t>(512,size_t(ms*4))];}
 void observe(uint64_t ticks,uint64_t frequency){if(previous&&ticks>=previous)duration(ticks-previous,frequency);previous=ticks;}
 double percentile(double f)const{uint64_t total=0;for(size_t i=0;i<bins.size();++i){total+=bins[i];if(total>=uint64_t(std::ceil(n*f)))return double(i+1)/4;}return 128.25;}
 std::string json()const{std::ostringstream s;const double mean=n?sum/n:0;s<<"{\"samples\":"<<n<<",\"mean_ms\":"<<mean<<",\"stddev_ms\":"<<(n?std::sqrt(std::max(0.,squares/n-mean*mean)):0)<<",\"p95_ms_upper\":"<<(n?percentile(.95):0)<<",\"p99_ms_upper\":"<<(n?percentile(.99):0)<<",\"max_ms\":"<<maximum<<"}";return s.str();}
};
}
