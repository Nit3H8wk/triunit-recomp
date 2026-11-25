#include "mk5_machine.hpp"
#define WIN32_LEAN_AND_MEAN
#ifdef _WIN32
#include <windows.h>
#include <bcrypt.h>
#else
#include "mk5_win_compat.hpp"
#include <cstring>
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
// Portable SHA-256 and SHA-1 implementations for Linux

struct Sha256Impl {
    uint32_t state[8];
    uint64_t bitlen;
    uint8_t buffer[64];
    size_t buflen;
    
    Sha256Impl() : bitlen(0), buflen(0) {
        state[0] = 0x6a09e667; state[1] = 0xbb67ae85;
        state[2] = 0x3c6ef372; state[3] = 0xa54ff53a;
        state[4] = 0x510e527f; state[5] = 0x9b05688c;
        state[6] = 0x1f83d9ab; state[7] = 0x5be0cd19;
    }
    
    static uint32_t rotr(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }
    
    void transform(const uint8_t* chunk) {
        static const uint32_t k[64] = {
            0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
            0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
            0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
            0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
            0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
            0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
            0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
            0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
            0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
            0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
            0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
            0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
            0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
            0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
            0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
            0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
        };
        
        uint32_t w[64];
        for (int i = 0; i < 16; ++i) {
            w[i] = (chunk[i*4] << 24) | (chunk[i*4+1] << 16) | (chunk[i*4+2] << 8) | chunk[i*4+3];
        }
        for (int i = 16; i < 64; ++i) {
            uint32_t s0 = rotr(w[i-15], 7) ^ rotr(w[i-15], 18) ^ (w[i-15] >> 3);
            uint32_t s1 = rotr(w[i-2], 17) ^ rotr(w[i-2], 19) ^ (w[i-2] >> 10);
            w[i] = w[i-16] + s0 + w[i-7] + s1;
        }
        
        uint32_t a = state[0], b = state[1], c = state[2], d = state[3];
        uint32_t e = state[4], f = state[5], g = state[6], h = state[7];
        
        for (int i = 0; i < 64; ++i) {
            uint32_t S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
            uint32_t ch = (e & f) ^ (~e & g);
            uint32_t temp1 = h + S1 + ch + k[i] + w[i];
            uint32_t S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
            uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
            uint32_t temp2 = S0 + maj;
            
            h = g; g = f; f = e; e = d + temp1;
            d = c; c = b; b = a; a = temp1 + temp2;
        }
        
        state[0] += a; state[1] += b; state[2] += c; state[3] += d;
        state[4] += e; state[5] += f; state[6] += g; state[7] += h;
    }
    
    void update(const uint8_t* data, size_t len) {
        for (size_t i = 0; i < len; ++i) {
            buffer[buflen++] = data[i];
            if (buflen == 64) {
                transform(buffer);
                bitlen += 512;
                buflen = 0;
            }
        }
    }
    
    void finalize(uint8_t* hash) {
        uint64_t bits = bitlen + buflen * 8;
        buffer[buflen++] = 0x80;
        if (buflen > 56) {
            while (buflen < 64) buffer[buflen++] = 0;
            transform(buffer);
            buflen = 0;
        }
        while (buflen < 56) buffer[buflen++] = 0;
        for (int i = 7; i >= 0; --i) buffer[buflen++] = (bits >> (i * 8)) & 0xff;
        transform(buffer);
        
        for (int i = 0; i < 8; ++i) {
            hash[i*4] = (state[i] >> 24) & 0xff;
            hash[i*4+1] = (state[i] >> 16) & 0xff;
            hash[i*4+2] = (state[i] >> 8) & 0xff;
            hash[i*4+3] = state[i] & 0xff;
        }
    }
};

struct Sha1 {
    uint32_t state[5];
    uint64_t bitlen;
    uint8_t buffer[64];
    size_t buflen;
    
    Sha1() : bitlen(0), buflen(0) {
        state[0] = 0x67452301; state[1] = 0xefcdab89;
        state[2] = 0x98badcfe; state[3] = 0x10325476;
        state[4] = 0xc3d2e1f0;
    }
    
    static uint32_t rotl(uint32_t x, int n) { return (x << n) | (x >> (32 - n)); }
    
    void transform(const uint8_t* chunk) {
        uint32_t w[80];
        for (int i = 0; i < 16; ++i) {
            w[i] = (chunk[i*4] << 24) | (chunk[i*4+1] << 16) | (chunk[i*4+2] << 8) | chunk[i*4+3];
        }
        for (int i = 16; i < 80; ++i) {
            w[i] = rotl(w[i-3] ^ w[i-8] ^ w[i-14] ^ w[i-16], 1);
        }
        
        uint32_t a = state[0], b = state[1], c = state[2], d = state[3], e = state[4];
        
        for (int i = 0; i < 80; ++i) {
            uint32_t f, k;
            if (i < 20) { f = (b & c) | (~b & d); k = 0x5a827999; }
            else if (i < 40) { f = b ^ c ^ d; k = 0x6ed9eba1; }
            else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8f1bbcdc; }
            else { f = b ^ c ^ d; k = 0xca62c1d6; }
            
            uint32_t temp = rotl(a, 5) + f + e + k + w[i];
            e = d; d = c; c = rotl(b, 30); b = a; a = temp;
        }
        
        state[0] += a; state[1] += b; state[2] += c; state[3] += d; state[4] += e;
    }
    
    void update(const uint8_t* data, size_t len) {
        for (size_t i = 0; i < len; ++i) {
            buffer[buflen++] = data[i];
            if (buflen == 64) {
                transform(buffer);
                bitlen += 512;
                buflen = 0;
            }
        }
    }
    
    void finalize(uint8_t* hash) {
        uint64_t bits = bitlen + buflen * 8;
        buffer[buflen++] = 0x80;
        if (buflen > 56) {
            while (buflen < 64) buffer[buflen++] = 0;
            transform(buffer);
            buflen = 0;
        }
        while (buflen < 56) buffer[buflen++] = 0;
        for (int i = 7; i >= 0; --i) buffer[buflen++] = (bits >> (i * 8)) & 0xff;
        transform(buffer);
        
        for (int i = 0; i < 5; ++i) {
            hash[i*4] = (state[i] >> 24) & 0xff;
            hash[i*4+1] = (state[i] >> 16) & 0xff;
            hash[i*4+2] = (state[i] >> 8) & 0xff;
            hash[i*4+3] = state[i] & 0xff;
        }
    }
};

std::string digest(const std::vector<uint8_t>& bytes,const char* algorithm){
    constexpr char hex[]="0123456789abcdef";
    if (strcmp(algorithm, "SHA256") == 0) {
        Sha256Impl sha;
        sha.update(bytes.data(), bytes.size());
        uint8_t hash[32];
        sha.finalize(hash);
        std::string text; text.reserve(64);
        for (auto byte : hash) { text.push_back(hex[byte>>4]); text.push_back(hex[byte&15]); }
        return text;
    } else if (strcmp(algorithm, "SHA1") == 0) {
        Sha1 sha;
        sha.update(bytes.data(), bytes.size());
        uint8_t hash[20];
        sha.finalize(hash);
        std::string text; text.reserve(40);
        for (auto byte : hash) { text.push_back(hex[byte>>4]); text.push_back(hex[byte&15]); }
        return text;
    } else {
        throw std::runtime_error("Unsupported algorithm: " + std::string(algorithm));
    }
}
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
