#pragma once
// The CMOS profile guard shared by the native games: a session's NVRAM is written only after the shared D3D12
// presenter showed it (flip-model renderer, displayed frames, a successful last Present) and its GPU pixel
// validation, when enabled, matched. A negative HRESULT is FAILED().
#include <charconv>
#include <cstdint>
#include <stdexcept>
#include <string>

// These scalar fields come from the existing shared presenter, never a guest state import.
template<class Integer> inline Integer ProfilePresentationValue(const std::string& json,const char* key) {
    const std::string token=std::string("\"")+key+"\":";
    const auto found=json.find(token);
    if(found==std::string::npos || json.find(token,found+token.size())!=std::string::npos)
        throw std::runtime_error("native profile requires unambiguous presentation metrics");
    const char* first=json.data()+found+token.size();const char* end=json.data()+json.size();
    Integer value{};const auto parsed=std::from_chars(first,end,value);
    if(parsed.ec!=std::errc{} || parsed.ptr==first || parsed.ptr==end || (*parsed.ptr!=',' && *parsed.ptr!='}'))
        throw std::runtime_error("native profile presentation metric is malformed");
    return value;
}
inline void ValidateProfilePresentation(const std::string& json,bool clean_host_stop,bool validate_pixels) {
    const auto frames=ProfilePresentationValue<uint64_t>(json,"gpu_validation_frames");
    const auto fighter_frames=ProfilePresentationValue<uint64_t>(json,"bicubic_fighter_validation_frames");
    if(json.find("\"renderer\":\"D3D12-DXGI-flip\"")==std::string::npos ||
       (frames>2+fighter_frames || fighter_frames>1 || (validate_pixels && !frames && !clean_host_stop)) ||
       ProfilePresentationValue<uint64_t>(json,"gpu_validation_mismatches") ||
       ProfilePresentationValue<uint64_t>(json,"gpu_validation_max_error")>
            ProfilePresentationValue<uint64_t>(json,"gpu_validation_tolerance") ||
       (!clean_host_stop && !ProfilePresentationValue<uint64_t>(json,"displayed_frames")) ||
       int32_t(ProfilePresentationValue<int64_t>(json,"last_present_hresult"))<0)
        throw std::runtime_error("native profile shared DX12 presentation failed or is incomplete");
}
