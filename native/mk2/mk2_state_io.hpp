#pragma once
// Save-state serializer core: one field list drives both the writer and the reader (mk2_save_state.hpp).
#include <array>
#include <cstdint>
#include <cstring>
#include <deque>
#include <map>
#include <stdexcept>
#include <string>
#include <tuple>
#include <type_traits>
#include <vector>

namespace mk2::state {
template<class T> constexpr bool kBlock=std::is_arithmetic_v<T> ||
    (std::is_trivially_copyable_v<T> && std::has_unique_object_representations_v<T>);
template<class A,class T> void Io(A&,T&);
template<class A,class T,size_t N> void Io(A&,std::array<T,N>&);
template<class A,class T,class Al> void Io(A&,std::vector<T,Al>&);
template<class A,class T,class Al> void Io(A&,std::deque<T,Al>&);
template<class A,class K,class V,class C,class Al> void Io(A&,std::map<K,V,C,Al>&);
template<class A,class... T> void Io(A&,std::tuple<T...>&);
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
    if constexpr(std::is_enum_v<T> || kBlock<T>)a.Raw(&value,sizeof value);
    else Fields(a,value);
}
template<class A,class T,size_t N> void Io(A& a,std::array<T,N>& values){
    if constexpr(kBlock<T>)a.Raw(values.data(),sizeof values);
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
template<class A,class... T> void Io(A& a,std::tuple<T...>& values){std::apply([&a](auto&... value){(Io(a,value),...);},values);}
template<class A> void Io(A& a,std::string& text){
    const auto size=a.Size(text.size());
    if constexpr(A::reading)text.resize(size_t(size));
    if(size)a.Raw(text.data(),size_t(size));
}
}
