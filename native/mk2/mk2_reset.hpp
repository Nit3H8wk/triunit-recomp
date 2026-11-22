#pragma once
#include "mk2_program.hpp"
#include "mk2_board.hpp"
#include "mk2_video.hpp"
#include <array>
#include <algorithm>
#include <initializer_list>
#include <map>
#include <vector>

namespace mk2 {
struct ResetAccess {
    uint32_t pc, address_bit;
    uint16_t value;
    uint64_t cycle;
};
// The 32-bit RAM writes' trace: each long address written by a 32-bit store and its value as RAM holds it now (a 16-bit
// store keeps both longs it touches current). Keys in RAM (16-bit aligned) live in a direct table, any other key in a map;
// iteration is in address order, as std::map's, and a save state holds the same count and pairs.
class RamTrace {
    static constexpr uint32_t kFirst=0x01000000,kLast=0x013ffff0;
    static bool Dense(uint32_t key){return key>=kFirst&&key<=kLast&&!(key&15);}
    static size_t Slot(uint32_t key){return (key-kFirst)/16;}
    static constexpr size_t kSlots=(kLast-kFirst)/16+1;
    std::vector<uint32_t> values_;std::vector<uint64_t> present_;std::map<uint32_t,uint32_t> other_;size_t dense_=0;
    void Init(){if(values_.empty()){values_.assign(kSlots,0);present_.assign(kSlots/64,0);}}
public:
    RamTrace()=default;
    RamTrace(std::initializer_list<std::pair<const uint32_t,uint32_t>> entries){for(const auto& [key,value]:entries)if(!Contains(key))(*this)[key]=value;}
    bool Contains(uint32_t key)const{
        if(!Dense(key))return other_.count(key)!=0;
        return !present_.empty()&&(present_[Slot(key)/64]>>(Slot(key)%64)&1);
    }
    uint32_t* Find(uint32_t key){
        if(!Dense(key)){const auto it=other_.find(key);return it==other_.end()?nullptr:&it->second;}
        return Contains(key)?&values_[Slot(key)]:nullptr;
    }
    uint32_t& operator[](uint32_t key){
        if(!Dense(key))return other_[key];
        Init();uint64_t& bits=present_[Slot(key)/64];const uint64_t bit=uint64_t(1)<<(Slot(key)%64);
        if(!(bits&bit)){bits|=bit;++dense_;values_[Slot(key)]=0;}
        return values_[Slot(key)];
    }
    size_t size()const{return dense_+other_.size();}
    // Every entry in address order: f(key, value&).
    template<class F> void ForEach(F&& f){
        auto it=other_.begin();
        for(size_t w=0;w<present_.size();++w)for(uint64_t bits=present_[w];bits;bits&=bits-1){
            const size_t slot=w*64+size_t(__builtin_ctzll(bits));const uint32_t key=uint32_t(kFirst+slot*16);
            for(;it!=other_.end()&&it->first<key;++it)f(it->first,it->second);
            f(key,values_[slot]);
        }
        for(;it!=other_.end();++it)f(it->first,it->second);
    }
    template<class F> void ForEach(F&& f)const{const_cast<RamTrace*>(this)->ForEach([&](uint32_t key,const uint32_t& value){f(key,value);});}
    bool operator==(const RamTrace& o)const{
        if(size()!=o.size()||other_!=o.other_)return false;
        bool same=true;ForEach([&](uint32_t key,const uint32_t& value){if(Dense(key)&&(!o.Contains(key)||o.values_[Slot(key)]!=value))same=false;});
        return same;
    }
    bool operator!=(const RamTrace& o)const{return !(*this==o);}
    // Save states: the count, then each key and value in address order (std::map's form).
    template<class A> friend void Fields(A& a,RamTrace& r){
        const auto count=a.Size(r.size());
        if constexpr(A::reading){
            std::fill(r.present_.begin(),r.present_.end(),uint64_t(0));r.dense_=0;r.other_.clear();   // the table stays allocated
            for(uint64_t n=0;n<count;++n){uint32_t key=0,value=0;a(key,value);r[key]=value;}
        }else r.ForEach([&](uint32_t key,uint32_t& value){uint32_t k=key;a(k,value);});
    }
};
struct ResetTrace {
    std::array<uint32_t, 16> a{};
    std::array<uint32_t, 15> b{}; // B15 shares SP with A15.
    uint32_t status = 0x10, next_pc = kResetPc;
    uint64_t cycles = 0, instructions = 0;
    uint32_t delay_iterations = 0;
    std::vector<ResetAccess> writes, cmos_reads, cmos_writes;
    BoardBootControls board;
    std::vector<ResetAccess> board_writes; // Aligned full-word accesses, 16 bits each.
    bool cmos_write_enabled = false;
    // Pinned MAME accepts masked writes even without a preceding enable.
    void EnableCmos() { cmos_write_enabled = true; }
    void WriteCmos(unsigned offset, uint16_t data, uint16_t mask) {
        auto& word = cmos.at(offset);
        word = uint16_t((word & uint16_t(~mask)) | (data & mask));
        cmos_write_enabled = false;
    }
    // Heap snapshots avoid exhausting the instrumented test stack; cold DEFAULT_ALL_0, no NVRAM.
    std::vector<uint16_t> cmos = std::vector<uint16_t>(8192);
    RamTrace ram;
};
struct BootAccess {
    uint32_t pc, address_bit, value;
    uint64_t cycle;
    unsigned size_bits;
};
}
