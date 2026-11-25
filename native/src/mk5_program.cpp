#include "mk5_machine.hpp"
#define WIN32_LEAN_AND_MEAN
#ifdef _WIN32
#include <windows.h>
#include <bcrypt.h>
#else
#include "mk5_win_compat.hpp"
#endif
#include <algorithm>
#include <fstream>
#include <iterator>
#include <limits>
#include <stdexcept>

namespace {
#ifdef _WIN32
struct Algorithm {
    BCRYPT_ALG_HANDLE value=nullptr;
    ~Algorithm(){if(value)BCryptCloseAlgorithmProvider(value,0);}
};
struct Hash {
    BCRYPT_HASH_HANDLE value=nullptr;
    ~Hash(){if(value)BCryptDestroyHash(value);}
};
void checked(NTSTATUS result){if(result<0)throw std::runtime_error("MK 5.0: Windows hash operation failed");}
std::string digest(const std::vector<uint8_t>& bytes,LPCWSTR algorithm){
    Algorithm provider;
    checked(BCryptOpenAlgorithmProvider(&provider.value,algorithm,nullptr,0));
    DWORD object_size=0,digest_size=0,returned=0;
    checked(BCryptGetProperty(provider.value,BCRYPT_OBJECT_LENGTH,reinterpret_cast<PUCHAR>(&object_size),sizeof(object_size),&returned,0));
    checked(BCryptGetProperty(provider.value,BCRYPT_HASH_LENGTH,reinterpret_cast<PUCHAR>(&digest_size),sizeof(digest_size),&returned,0));
    std::vector<uint8_t> object(object_size),output(digest_size);
    Hash hash;
    checked(BCryptCreateHash(provider.value,&hash.value,object.data(),object_size,nullptr,0,0));
    // ROM images here are <=1 MiB, but keep the Windows ULONG length boundary explicit.
    size_t pos=0;
    while(pos<bytes.size()){
        ULONG length=static_cast<ULONG>(std::min(bytes.size()-pos,size_t(std::numeric_limits<ULONG>::max())));
        checked(BCryptHashData(hash.value,const_cast<PUCHAR>(bytes.data()+pos),length,0));
        pos+=length;
    }
    checked(BCryptFinishHash(hash.value,output.data(),digest_size,0));
    constexpr char hex[]="0123456789abcdef";
    std::string text; text.reserve(output.size()*2);
    for(auto byte:output){text.push_back(hex[byte>>4]);text.push_back(hex[byte&15]);}
    return text;
}
#else
// Phase 1 stubs: real SHA-256/SHA-1 arrive with the portable crypto backend.
std::string digest(const std::vector<uint8_t>&,const char*){throw std::runtime_error("MK 5.0: hashing not available on Linux (Phase 1)");}
#endif
std::vector<uint8_t> read(const std::filesystem::path& path){
    std::ifstream input(path,std::ios::binary);
    if(!input)throw std::runtime_error("MK 5.0: program ROM cannot be opened");
    std::vector<uint8_t> bytes{std::istreambuf_iterator<char>(input),{}};
    if(input.bad())throw std::runtime_error("MK 5.0: program ROM read failed");
    return bytes;
}
}

#ifdef _WIN32
std::string Sha256(const std::vector<uint8_t>& bytes){return digest(bytes,BCRYPT_SHA256_ALGORITHM);}
#else
std::string Sha256(const std::vector<uint8_t>& bytes){return digest(bytes,"SHA256");}
#endif

VerifiedMk5Program LoadMk5Program(const std::filesystem::path& root){
    namespace fs=std::filesystem;
    if(!fs::is_directory(root))throw std::runtime_error("MK 5.0: ROM directory does not exist");
    std::vector<fs::path> candidates;
    for(const auto& file:fs::recursive_directory_iterator(root))
        if(file.is_regular_file() && file.file_size()==524288)candidates.push_back(file.path());
    std::sort(candidates.begin(),candidates.end());
    VerifiedMk5Program program;
    std::vector<uint8_t> even,odd;
    for(const auto& path:candidates){
        auto bytes=read(path);
        if(bytes.size()!=524288)continue;
#ifdef _WIN32
        auto sha1=digest(bytes,BCRYPT_SHA1_ALGORITHM);
#else
        auto sha1=digest(bytes,"SHA1");
#endif
        if(even.empty() && sha1=="796ec84d37c8d20ca36d6439c14dee626fb8481e"){
            even=std::move(bytes);program.even_source=path;
        }else if(odd.empty() && sha1=="f66655eeab67c8cf5e496ae42dbae54d6400586f"){
            odd=std::move(bytes);program.odd_source=path;
        }
    }
    if(even.empty() || odd.empty())throw std::runtime_error("MK 5.0: missing expected program ROM content; require both verified 512 KiB lanes");
    program.bytes.resize(1048576);
    for(size_t i=0;i<524288;++i){program.bytes[2*i]=even[i];program.bytes[2*i+1]=odd[i];}
    program.sha256=Sha256(program.bytes);
    if(program.sha256!=kMk5ProgramSha256)throw std::runtime_error("MK 5.0: interleaved program SHA256 mismatch");
    return program;
}

std::vector<uint8_t> Mk5CmosBytes(const std::vector<uint16_t>& words){
    std::vector<uint8_t> bytes;bytes.reserve(words.size()*2);
    for(auto word:words){bytes.push_back(uint8_t(word));bytes.push_back(uint8_t(word>>8));}
    return bytes;
}

std::vector<uint16_t> LoadMk5CmosSnapshot(const std::filesystem::path& path){
    std::error_code error;
    if(!std::filesystem::is_regular_file(path,error) || error)throw std::runtime_error("CMOS input must be a regular raw snapshot file");
    auto size=std::filesystem::file_size(path,error);
    if(error || size!=16384)throw std::runtime_error("CMOS snapshot must be exactly 16384 bytes (8192 little-endian words)");
    std::ifstream file(path,std::ios::binary);std::vector<uint8_t> bytes(16384);
    if(!file.read(reinterpret_cast<char*>(bytes.data()),static_cast<std::streamsize>(bytes.size())) || file.peek()!=std::char_traits<char>::eof())
        throw std::runtime_error("Cannot read exact CMOS snapshot content");
    std::vector<uint16_t> words(8192);
    for(size_t i=0;i<words.size();++i)words[i]=uint16_t(uint16_t(bytes[i*2])|(uint16_t(bytes[i*2+1])<<8));
    return words;
}

void SaveMk5CmosSnapshot(const std::filesystem::path& path,const std::vector<uint16_t>& words){
    if(words.size()!=8192)throw std::runtime_error("CMOS output requires exactly 8192 words");
    const auto bytes=Mk5CmosBytes(words);
#ifdef _WIN32
    // CREATE_NEW atomically refuses existing files, including original ROMs.
    HANDLE file=CreateFileW(path.c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(file==INVALID_HANDLE_VALUE)throw std::runtime_error("Cannot create CMOS snapshot: existing file or invalid output path");
    DWORD written=0;BOOL ok=WriteFile(file,bytes.data(),static_cast<DWORD>(bytes.size()),&written,nullptr);
    CloseHandle(file);
    if(!ok || written!=bytes.size()){
        DeleteFileW(path.c_str());throw std::runtime_error("Cannot write complete CMOS snapshot");
    }
#else
    // Portable equivalent: refuse existing files, then write atomically.
    if(std::filesystem::exists(path))throw std::runtime_error("Cannot create CMOS snapshot: existing file or invalid output path");
    std::ofstream out(path,std::ios::binary);
    if(!out.write(reinterpret_cast<const char*>(bytes.data()),static_cast<std::streamsize>(bytes.size())))
        throw std::runtime_error("Cannot write complete CMOS snapshot");
#endif
}
