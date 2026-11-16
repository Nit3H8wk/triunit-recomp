#pragma once
// Small bounded file reader and JSON parser for local configuration and setup records (slots.json, setup.json):
// objects, arrays, strings (simple escapes), numbers, true/false/null. Linked paths are refused.
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <map>
#include <optional>
#include <string>
#include <vector>
#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace tinyjson {
inline bool Linked(std::filesystem::path p) {
#ifdef _WIN32
    std::error_code error;p=std::filesystem::absolute(p,error).lexically_normal();if(error)return true;
    for(;!p.empty();){
        const auto a=GetFileAttributesW(p.c_str());
        if(a!=INVALID_FILE_ATTRIBUTES&&(a&FILE_ATTRIBUTE_REPARSE_POINT))return true;
        const auto parent=p.parent_path();if(parent==p)break;p=parent;
    }
#else
    (void)p;
#endif
    return false;
}
inline std::optional<std::string> Read(const std::filesystem::path& path,uintmax_t limit) {
    std::error_code error;
    if(Linked(path)||!std::filesystem::is_regular_file(path,error)||error)return std::nullopt;
    const auto size=std::filesystem::file_size(path,error);if(error||size>limit)return std::nullopt;
    std::ifstream f(path,std::ios::binary);std::string bytes(size_t(size),'\0');
    if(!f.read(bytes.data(),std::streamsize(bytes.size())))return std::nullopt;
    return bytes;
}
struct Value {
    enum Kind{Null,Bool,Number,String,Array,Object} kind=Null;
    bool boolean=false;double number=0;std::string text;
    std::vector<Value> items;std::map<std::string,Value> fields;
};
class Parser {
    const std::string& s_;size_t at_=0;unsigned depth_=0;
    void Space(){while(at_<s_.size()&&(s_[at_]==' '||s_[at_]=='\t'||s_[at_]=='\r'||s_[at_]=='\n'))++at_;}
    bool Take(char c){Space();if(at_<s_.size()&&s_[at_]==c){++at_;return true;}return false;}
    bool Word(const char* w){const std::string t(w);if(s_.compare(at_,t.size(),t)==0){at_+=t.size();return true;}return false;}
    bool String(std::string& out){
        if(!Take('"'))return false;
        while(at_<s_.size()){
            const char c=s_[at_++];
            if(c=='"')return true;
            if(uint8_t(c)<0x20)return false;
            if(c!='\\'){out+=c;continue;}
            if(at_>=s_.size())return false;
            const char e=s_[at_++];
            if(e=='"'||e=='\\'||e=='/')out+=e;else if(e=='n')out+='\n';else if(e=='t')out+='\t';else if(e=='r')out+='\r';
            else if(e=='b')out+='\b';else if(e=='f')out+='\f';
            else if(e=='u'&&at_+4<=s_.size()){ // UTF-16 unit as UTF-8 (surrogate halves kept as-is)
                unsigned code=0;for(int i=0;i<4;++i){const char h=s_[at_++];code<<=4;
                    if(h>='0'&&h<='9')code|=unsigned(h-'0');else if(h>='a'&&h<='f')code|=unsigned(h-'a'+10);else if(h>='A'&&h<='F')code|=unsigned(h-'A'+10);else return false;}
                if(code<0x80)out+=char(code);
                else if(code<0x800){out+=char(0xc0|(code>>6));out+=char(0x80|(code&63));}
                else{out+=char(0xe0|(code>>12));out+=char(0x80|((code>>6)&63));out+=char(0x80|(code&63));}
            }else return false;
        }
        return false;
    }
public:
    explicit Parser(const std::string& s):s_(s){}
    bool Parse(Value& v){
        if(++depth_>32)return false;
        Space();if(at_>=s_.size())return false;
        const char c=s_[at_];bool ok=false;
        if(c=='{'){
            ++at_;v.kind=Value::Object;
            if(Take('}'))ok=true;
            else for(;;){
                std::string key;Value item;
                if(!String(key)||!Take(':')||!Parse(item)||!v.fields.emplace(key,std::move(item)).second)break;
                if(Take('}')){ok=true;break;}
                if(!Take(','))break;
            }
        }else if(c=='['){
            ++at_;v.kind=Value::Array;
            if(Take(']'))ok=true;
            else for(;;){
                Value item;if(!Parse(item))break;v.items.push_back(std::move(item));
                if(Take(']')){ok=true;break;}
                if(!Take(','))break;
            }
        }else if(c=='"'){v.kind=Value::String;ok=String(v.text);}
        else if(Word("true")){v.kind=Value::Bool;v.boolean=true;ok=true;}
        else if(Word("false")){v.kind=Value::Bool;ok=true;}
        else if(Word("null"))ok=true;
        else{
            const size_t first=at_;
            while(at_<s_.size()&&std::string("+-.0123456789eE").find(s_[at_])!=std::string::npos)++at_;
            if(at_==first)return false;
            try{size_t used=0;v.number=std::stod(s_.substr(first,at_-first),&used);ok=used==at_-first&&std::isfinite(v.number);}catch(...){ok=false;}
            v.kind=Value::Number;
        }
        --depth_;return ok;
    }
    bool End(){Space();return at_==s_.size();}
};
}
