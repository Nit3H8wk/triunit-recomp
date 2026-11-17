#pragma once
#include <cstddef>
#include <cstdint>
#include <ostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace mk2 {
class ReplayCapture {
    std::string program_, cmos_hash_;
    std::vector<uint8_t> cmos_;
    std::vector<std::pair<uint64_t,uint32_t>> inputs_;
    std::size_t limit_=4096;
    uint64_t last_tick_=0;
    bool complete_=true, observed_=false, ended_=false;
public:
    static constexpr std::size_t diagnostic_limit=16384;

    void Start(const std::string& program,const std::string& cmos_hash,const std::vector<uint8_t>& cmos,
               std::size_t limit=4096) {
        const auto digest=[](const std::string& text) {
            return text.size()==64 && text.find_first_not_of("0123456789abcdef")==std::string::npos;
        };
        if(!program_.empty() || !digest(program) || !digest(cmos_hash) || cmos.size()!=16384 ||
           limit==0 || limit>diagnostic_limit)
            throw std::invalid_argument("Invalid replay capture identity");
        program_=program;cmos_hash_=cmos_hash;cmos_=cmos;limit_=limit;inputs_.reserve(limit_);
    }
    void Observe(uint64_t tick,uint32_t input) {
        if(program_.empty() || ended_)return;
        if(observed_ && (tick<last_tick_ || (tick==last_tick_ && !inputs_.empty() && input!=inputs_.back().second)))
            {complete_=false;return;}
        last_tick_=tick;observed_=true;
        if(inputs_.empty() || inputs_.back().second!=input) {
            if(inputs_.size()==limit_)complete_=false;
            else inputs_.emplace_back(tick,input);
        }
    }
    // A save-state load leaves this input timeline; the inputs recorded so far stay a valid replay.
    void End() { ended_=true; }
    void Write(std::ostream& out) const {
        if(program_.empty())return;
        out<<"MK2_REPLAY_V1 "<<program_<<' '<<cmos_hash_<<' '<<inputs_.size()<<' '<<(complete_?1:0)<<'\n';
        out<<"MK2_REPLAY_CMOS ";
        constexpr char digits[]="0123456789abcdef";
        for(const auto byte:cmos_)out<<digits[byte>>4]<<digits[byte&15];
        out<<'\n';
        for(const auto& input:inputs_)out<<"MK2_REPLAY_INPUT "<<input.first<<' '<<input.second<<'\n';
        out<<"MK2_REPLAY_END\n";
    }
};
}
