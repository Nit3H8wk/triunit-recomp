#pragma once
// MK2 Original save states at a live chunk boundary: CPU34, board, memories, DCS/ADSP and host audio/raster
// continuity, as value fields of the hardware model. References, ROMs, observers and providers stay bound to
// the live session, so a load restores state inside the same machine and never rebinds a callback.
#include "mk2_live_host.hpp"
#include "mk2_scanout.hpp"
#include "mk2_music.hpp"
#include "mk5_program.hpp"
#include <cstring>
#include <deque>
#include <map>
#include <string>
#include <type_traits>
#include <vector>

namespace mk2 {
inline constexpr uint32_t kSaveStateVersion=1;
inline constexpr const char* kSaveStateRevision="mk2 L3.1";
inline constexpr const char* kSaveStateMagic="TRIUNIT-MK2-STATE";

namespace state {
template<class T> constexpr bool kBlock=std::is_trivially_copyable_v<T> && std::has_unique_object_representations_v<T>;
template<class A,class T> void Io(A&,T&);
template<class A,class T,size_t N> void Io(A&,std::array<T,N>&);
template<class A,class T,class Al> void Io(A&,std::vector<T,Al>&);
template<class A,class T,class Al> void Io(A&,std::deque<T,Al>&);
template<class A,class K,class V,class C,class Al> void Io(A&,std::map<K,V,C,Al>&);
template<class A> void Io(A&,std::string&);

struct Writer {
    static constexpr bool reading=false;
    std::vector<uint8_t> bytes;
    void Raw(const void* data,size_t size){const auto* p=static_cast<const uint8_t*>(data);bytes.insert(bytes.end(),p,p+size);}
    uint64_t Size(uint64_t size){Raw(&size,sizeof size);return size;}
    template<class... T> void operator()(T&... values){(Io(*this,values),...);}
};
struct Reader {
    static constexpr bool reading=true;
    const uint8_t* at;const uint8_t* end;
    void Raw(void* data,size_t size){
        if(size_t(end-at)<size)throw std::runtime_error("MK2 save state is truncated");
        std::memcpy(data,at,size);at+=size;
    }
    // Every element occupies at least one byte, which bounds a hostile count before any allocation.
    uint64_t Size(uint64_t){uint64_t size;Raw(&size,sizeof size);if(size>uint64_t(end-at))throw std::runtime_error("MK2 save state count exceeds its data");return size;}
    template<class... T> void operator()(T&... values){(Io(*this,values),...);}
};

template<class A,class T> void Io(A& a,T& value){
    if constexpr(std::is_arithmetic_v<T> || std::is_enum_v<T> || kBlock<T>)a.Raw(&value,sizeof value);
    else Fields(a,value);
}
template<class A,class T,size_t N> void Io(A& a,std::array<T,N>& values){
    if constexpr(kBlock<std::array<T,N>>)a.Raw(values.data(),sizeof values);
    else for(auto& value:values)Io(a,value);
}
template<class A,class T,class Al> void Io(A& a,std::vector<T,Al>& values){
    const auto size=a.Size(values.size());
    if constexpr(A::reading)values.resize(size_t(size));
    if constexpr(kBlock<T>){if(size)a.Raw(values.data(),size_t(size)*sizeof(T));}
    else for(auto& value:values)Io(a,value);
}
template<class A,class T,class Al> void Io(A& a,std::deque<T,Al>& values){
    const auto size=a.Size(values.size());
    if constexpr(A::reading)values.resize(size_t(size));
    for(auto& value:values)Io(a,value);
}
template<class A,class K,class V,class C,class Al> void Io(A& a,std::map<K,V,C,Al>& values){
    const auto size=a.Size(values.size());
    if constexpr(A::reading) {
        values.clear();
        for(uint64_t n=0;n<size;++n){K key{};V value{};Io(a,key);Io(a,value);values.emplace_hint(values.end(),key,std::move(value));}
    } else for(auto& [stored,value]:values){K key=stored;Io(a,key);Io(a,value);}
}
template<class A> void Io(A& a,std::string& text){
    const auto size=a.Size(text.size());
    if constexpr(A::reading)text.resize(size_t(size));
    if(size)a.Raw(text.data(),size_t(size));
}
}

template<class A> void Fields(A& a,ResetAccess& x){a(x.pc,x.address_bit,x.value,x.cycle);}
template<class A> void Fields(A& a,PixbltAccess& x){a(x.pc,x.address_bit,x.value,x.cycle);}
template<class A> void Fields(A& a,AdspBoot::Access& x){a(x.pc,x.address,x.value,x.cycle,x.space);}
template<class A> void Fields(A& a,ResetTrace& s){
    a(s.a,s.b,s.status,s.next_pc,s.cycles,s.instructions,s.delay_iterations,s.writes,s.cmos_reads,s.cmos_writes,
      s.board,s.board_writes,s.cmos_write_enabled,s.cmos,s.ram);
}
template<class A> void Fields(A& a,BootVideo& v){
    // shortcut: Original video only; the Remastered backdrop, fighter and blood layers are a follow-up.
    if(v.BackdropEnabled() || v.FightersEnabled() || v.FighterVideo().enabled() || v.BloodEnabled())
        throw std::logic_error("MK2 Remastered video layers are not in the save state");
    a(v.palette_ram,v.vram,v.shift_register,v.dma_palette,v.dma_registers,v.backdrop_list,v.world_object_list);
}
template<class A> void Fields(A& a,BootCheckpoint& p){a(p.name,p.cpu,p.dsp);}
template<class A> void Fields(A& a,BootExecution& e){a(e.fill_remaining,e.fill_b,e.last_instruction_pc,e.last_instruction_cycles,e.shift_loaded,e.bitmap);}
template<class A> void Fields(A& a,TaskBatchInit& t){
    a(t.ready,t.video,t.main_ram,t.bus,t.points,t.observe_history,t.execution,t.host_origin,t.cpu_trace,t.executed_instructions);
}

namespace state {
struct Header { std::string magic,program,revision,payload; uint32_t version=0; bool audio=false; };
template<class A> void Fields(A& a,Header& h){a(h.magic,h.version,h.program,h.revision,h.audio,h.payload);}
// Identity and integrity before anything is applied; a refused file leaves the session untouched.
inline Reader CheckLiveState(const Program& program,const std::vector<uint8_t>& bytes,bool audio){
    Reader reader{bytes.data(),bytes.data()+bytes.size()};Header header;
    reader(header);
    if(header.magic!=kSaveStateMagic || header.version!=kSaveStateVersion || header.revision!=kSaveStateRevision)
        throw std::invalid_argument("MK2 save state format or revision differs");
    if(header.program!=program.sha256)throw std::invalid_argument("MK2 save state belongs to another program ROM");
    if(header.audio!=audio)throw std::invalid_argument("MK2 save state audio stream differs from this session");
    if(header.payload!=Sha256(std::vector<uint8_t>(reader.at,reader.end)))throw std::invalid_argument("MK2 save state payload is damaged");
    return reader;
}
}

// Only between ResumeValidLiveHost chunks, inside the live domain.
inline std::vector<uint8_t> SaveLiveState(const Program& program,const LiveHostContinuation& continuation,
    const DcsBootMachine& machine,const Scanout& scanout,const OriginalAudio* audio) {
    continuation.ValidateBoundary(program,machine);
    state::Writer payload; // The writer only reads its operands.
    payload(const_cast<LiveHostContinuation&>(continuation),const_cast<DcsBootMachine&>(machine),const_cast<Scanout&>(scanout));
    if(audio)payload(*const_cast<OriginalAudio*>(audio));
    state::Header header{kSaveStateMagic,program.sha256,kSaveStateRevision,Sha256(payload.bytes),kSaveStateVersion,audio!=nullptr};
    state::Writer out;out(header);
    out.bytes.insert(out.bytes.end(),payload.bytes.begin(),payload.bytes.end());
    return std::move(out.bytes);
}
// Call CheckLiveState first to refuse a file without side effects; a failure here leaves partial state and is fatal.
inline void LoadLiveState(const Program& program,const std::vector<uint8_t>& bytes,LiveHostContinuation& continuation,
    DcsBootMachine& machine,Scanout& scanout,OriginalAudio* audio) {
    auto reader=state::CheckLiveState(program,bytes,audio!=nullptr);
    continuation.ValidateBoundary(program,machine);
    reader(continuation,machine,scanout);
    if(audio)reader(*audio);
    if(reader.at!=reader.end)throw std::runtime_error("MK2 save state has trailing data");
    continuation.ValidateBoundary(program,machine);
}
}
