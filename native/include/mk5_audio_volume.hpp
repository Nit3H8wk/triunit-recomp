#pragma once
#include <charconv>
#include <cstdint>
#include <stdexcept>
#include <string_view>
namespace mk5audio {
inline unsigned ParseGameVolume(std::string_view text){
 if(text.empty())return 100;
 unsigned value=0;const auto parsed=std::from_chars(text.data(),text.data()+text.size(),value);
 if(parsed.ec!=std::errc{}||parsed.ptr!=text.data()+text.size()||value>100)throw std::runtime_error("MK1_GAME_VOLUME must be an integer from 0 to 100");
 return value;
}
// Output gain only: guest PCM, sound clocks and mixer state stay untouched.
inline int16_t ScaleVolume(int16_t sample,unsigned percent){return int16_t(int32_t(sample)*int32_t(percent)/100);}
}
