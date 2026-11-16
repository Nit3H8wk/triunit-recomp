// Minimal device/stream harness for the unchanged pinned DMADAC source.
// Clock scheduling and output-buffer rate conversion are tested separately.
#pragma once
#include <algorithm>
#include <cstdint>
#include <limits>
#include <vector>
using offs_t=uint32_t;
#define ATTR_COLD
#define NAME(value) value
#define DECLARE_DEVICE_TYPE(name,type) extern const int name;
#define DEFINE_DEVICE_TYPE(name,type,shortname,fullname) const int name=0;
struct machine_config {};
class sound_stream {
public:
    using sample_t=float;
    std::vector<float> output;
    int samples() const {return int(output.size());}
    void put(unsigned,int index,float value) {output.at(size_t(index))=value;}
    void update() {}
    void set_sample_rate(double) {}
};
class device_t {
public:
    device_t(const machine_config&,int,const char*,device_t*,uint32_t) {}
    virtual ~device_t()=default;
    virtual void device_start() {}
    template<class T> void save_item(const T&) {}
    template<class... T> void logerror(const char*,T...) {}
};
class device_sound_interface {
    sound_stream stream_;
public:
    device_sound_interface(const machine_config&,device_t&) {}
    virtual ~device_sound_interface()=default;
    virtual void sound_stream_update(sound_stream&)=0;
    sound_stream* stream_alloc(int,int,int) {return &stream_;}
};
