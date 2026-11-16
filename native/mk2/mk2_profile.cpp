#include "mk2_profile.hpp"
#include "mk5_program.hpp"
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <algorithm>
#include <atomic>
#include <cstddef>
#include <stdexcept>
#include <utility>

namespace mk2 {
namespace {
namespace fs=std::filesystem;
constexpr size_t kSize=16384;
constexpr const char* kFactorySha="f401005e9be6b161ba3becb3cc20b8fd72359e3234652af3b5c2fbbce0d06e1f";
[[noreturn]] void Fail(const char* message) {throw std::runtime_error(message);}
struct Handle {
    HANDLE h=INVALID_HANDLE_VALUE;
    explicit Handle(HANDLE value=INVALID_HANDLE_VALUE):h(value){}
    Handle(const Handle&)=delete;
    Handle& operator=(const Handle&)=delete;
    Handle(Handle&& other)noexcept:h(std::exchange(other.h,INVALID_HANDLE_VALUE)){}
    ~Handle(){if(h!=INVALID_HANDLE_VALUE)CloseHandle(h);}
};
BY_HANDLE_FILE_INFORMATION Info(HANDLE h,bool directory) {
    BY_HANDLE_FILE_INFORMATION info{};
    if(h==INVALID_HANDLE_VALUE || !GetFileInformationByHandle(h,&info) || GetFileType(h)!=FILE_TYPE_DISK ||
       (info.dwFileAttributes&FILE_ATTRIBUTE_REPARSE_POINT) ||
       bool(info.dwFileAttributes&FILE_ATTRIBUTE_DIRECTORY)!=directory)
        Fail("MK2 profile requires ordinary unlinked files and directories");
    return info;
}
bool Same(const BY_HANDLE_FILE_INFORMATION& a,const BY_HANDLE_FILE_INFORMATION& b) {
    return a.dwVolumeSerialNumber==b.dwVolumeSerialNumber && a.nFileIndexHigh==b.nFileIndexHigh && a.nFileIndexLow==b.nFileIndexLow;
}
bool Exists(const fs::path& path) {
    const auto attributes=GetFileAttributesW(path.c_str());
    if(attributes!=INVALID_FILE_ATTRIBUTES) {
        if(attributes&FILE_ATTRIBUTE_REPARSE_POINT)Fail("MK2 profile linked path rejected");
        return true;
    }
    const auto error=GetLastError();
    if(error!=ERROR_FILE_NOT_FOUND && error!=ERROR_PATH_NOT_FOUND)Fail("MK2 profile path is inaccessible");
    return false;
}
// Pin every traversed directory without delete sharing, including components before '..'.
struct Directory {
    fs::path path;
    std::vector<Handle> pins;
    Directory(const fs::path& requested,bool create) {
        if(requested.empty())Fail("MK2 profile directory must be explicit");
        const auto absolute=fs::absolute(requested);
        path=absolute.root_path();
        auto pin=[&] {
            if(!Exists(path)) {
                if(!create || !CreateDirectoryW(path.c_str(),nullptr))Fail("MK2 profile directory is missing or cannot be created");
            }
            Handle handle(CreateFileW(path.c_str(),FILE_READ_ATTRIBUTES,FILE_SHARE_READ|FILE_SHARE_WRITE,nullptr,
                OPEN_EXISTING,FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
            Info(handle.h,true);pins.push_back(std::move(handle));
        };
        pin();
        for(const auto& component:absolute.relative_path()) {
            if(component==L".")continue;
            if(component==L"..") {path=path.parent_path();continue;}
            path/=component;pin();
        }
    }
};
std::vector<uint8_t> ReadHandle(HANDLE h) {
    Info(h,false);LARGE_INTEGER length{};
    if(!GetFileSizeEx(h,&length) || length.QuadPart!=kSize)Fail("MK2 CMOS image must contain exactly 16384 bytes");
    std::vector<uint8_t> bytes(kSize);DWORD read=0;
    if(!ReadFile(h,bytes.data(),DWORD(bytes.size()),&read,nullptr) || read!=bytes.size())Fail("MK2 CMOS read failed");
    return bytes;
}
std::vector<uint8_t> Read(const fs::path& requested,bool factory=false) {
    const auto absolute=fs::absolute(requested);
    Directory parent(absolute.parent_path(),false);
    const auto path=parent.path/absolute.filename();
    Handle file(CreateFileW(path.c_str(),GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_DELETE,nullptr,
        OPEN_EXISTING,FILE_FLAG_OPEN_REPARSE_POINT|FILE_FLAG_SEQUENTIAL_SCAN,nullptr));
    auto bytes=ReadHandle(file.h);
    if(factory && Sha256(bytes)!=kFactorySha)Fail("MK2 factory CMOS seed SHA-256 differs");
    return bytes;
}
// CREATE_NEW matches Python open('xb'); stale or foreign lock files are never removed.
struct OwnedFile {
    fs::path path;
    Handle file;
    BY_HANDLE_FILE_INFORMATION identity{};
    bool keep=false;
    explicit OwnedFile(const fs::path& name):path(name),file(CreateFileW(path.c_str(),
        GENERIC_WRITE|DELETE|FILE_READ_ATTRIBUTES,0,nullptr,CREATE_NEW,FILE_FLAG_WRITE_THROUGH,nullptr)) {
        if(file.h==INVALID_HANDLE_VALUE)Fail("MK2 profile writer or temporary file already exists or is inaccessible");
        identity=Info(file.h,false);
    }
    ~OwnedFile() {
        if(!keep && file.h!=INVALID_HANDLE_VALUE) {
            BY_HANDLE_FILE_INFORMATION present{};
            // The handle denies rename/delete sharing; dispose this exact owned file, never a pathname successor.
            if(GetFileInformationByHandle(file.h,&present) && Same(identity,present)) {
                FILE_DISPOSITION_INFO disposition{TRUE};
                SetFileInformationByHandle(file.h,FileDispositionInfo,&disposition,sizeof(disposition));
            }
        }
    }
};
BY_HANDLE_FILE_INFORMATION Atomic(const fs::path& target,const std::vector<uint8_t>& bytes,bool must_exist=false) {
    static std::atomic<uint64_t> serial{0};
    const auto temporary=target.parent_path()/(L".cmos-pending-"+std::to_wstring(GetCurrentProcessId())+L"-"+std::to_wstring(++serial));
    OwnedFile pending(temporary);DWORD written=0;
    if(!WriteFile(pending.file.h,bytes.data(),DWORD(bytes.size()),&written,nullptr) || written!=bytes.size() || !FlushFileBuffers(pending.file.h))
        Fail("MK2 CMOS atomic write or flush failed");
    const auto destination=target.native();
    // Win32 converts the name as a NUL-terminated path even though FileNameLength excludes that NUL.
    const size_t size=offsetof(FILE_RENAME_INFO,FileName)+(destination.size()+1)*sizeof(wchar_t);
    std::vector<uint8_t> storage(size);
    auto* rename=reinterpret_cast<FILE_RENAME_INFO*>(storage.data());
    rename->ReplaceIfExists=TRUE;rename->RootDirectory=nullptr;
    rename->FileNameLength=DWORD(destination.size()*sizeof(wchar_t));
    std::copy(destination.begin(),destination.end(),rename->FileName);
    // Brief Win32 contention retries retain the owned handle and game lock.
    for(unsigned attempt=0;;++attempt) {
        if(!Exists(target)&&must_exist)Fail("CMOS edit requires an existing profile image");
        if(SetFileInformationByHandle(pending.file.h,FileRenameInfo,rename,DWORD(size)))break;
        const auto error=GetLastError();
        if(attempt==9 || (error!=ERROR_ACCESS_DENIED && error!=ERROR_SHARING_VIOLATION && error!=ERROR_LOCK_VIOLATION))
            throw std::runtime_error("MK2 CMOS atomic replacement failed: "+std::to_string(error)+" path="+target.u8string()+" length="+std::to_string(destination.size())+" offset="+std::to_string(offsetof(FILE_RENAME_INFO,FileName)));
        Sleep(10);
    }
    pending.keep=true;return pending.identity;
}
void RollBackSeed(const fs::path& seed,const BY_HANDLE_FILE_INFORMATION& created,const std::vector<uint8_t>& expected)noexcept {
    try {
        Handle file(CreateFileW(seed.c_str(),GENERIC_READ|DELETE,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
        if(file.h==INVALID_HANDLE_VALUE || !Same(Info(file.h,false),created) || ReadHandle(file.h)!=expected)return;
        FILE_DISPOSITION_INFO disposition{TRUE};SetFileInformationByHandle(file.h,FileDispositionInfo,&disposition,sizeof(disposition));
    }catch(...){}
}
CmosProfileSnapshot Load(const fs::path& directory) {
    Read(directory/L"factory-seed.bin",true);
    auto bytes=Read(directory/L"cmos.bin");auto sha=Sha256(bytes);
    return {std::move(bytes),std::move(sha)};
}
}
CmosProfileSnapshot LoadCmosFile(const fs::path& file) {
    auto bytes=Read(file);auto sha=Sha256(bytes);return {std::move(bytes),std::move(sha)};
}
std::string CompareAndSwapCmosFile(const fs::path& file,const std::vector<uint8_t>& image,
        const std::string& expected_sha256,CmosLock mode,const std::function<void()>& commit) {
    if(file.filename()!=L"cmos.bin")Fail("CMOS edit may only replace an existing cmos.bin profile");
    if(image.size()!=kSize)Fail("CMOS edit requires exactly 16384 bytes");
    if(mode!=CmosLock::Mk1Session&&mode!=CmosLock::Mk2Profile)Fail("Unknown CMOS writer lock");
    const auto sha=Sha256(image);Directory pinned(fs::absolute(file).parent_path(),false);
    const auto target=pinned.path/file.filename();
    auto swap=[&] {
        const auto previous=LoadCmosFile(target);
        if(previous.sha256!=expected_sha256)Fail("CMOS profile changed since load; edit rejected");
        const bool changed=image!=previous.image;
        if(changed)Atomic(target,image,true);
        try{if(commit)commit();}
        catch(...){if(changed)Atomic(target,previous.image,true);throw;}
        return sha;
    };
    if(mode==CmosLock::Mk1Session) {
        Handle lock(CreateFileW((pinned.path/L"session.lock").c_str(),GENERIC_READ|GENERIC_WRITE,0,nullptr,
            OPEN_ALWAYS,FILE_FLAG_OPEN_REPARSE_POINT,nullptr));
        Info(lock.h,false);return swap();
    }
    OwnedFile lock(pinned.path/L".cmos.lock");return swap();
}
CmosProfileSnapshot LoadCmosProfile(const fs::path& directory) {
    Directory pinned(directory,false);return Load(pinned.path);
}
CmosProfileSnapshot PrepareCmosProfile(const fs::path& directory,const fs::path& authenticated_seed) {
    const auto bytes=Read(authenticated_seed,true); // Authenticate before creating any profile directory or lock.
    Directory pinned(directory,true);
    OwnedFile lock(pinned.path/L".cmos.lock");
    const auto seed=pinned.path/L"factory-seed.bin",current=pinned.path/L"cmos.bin";
    if(Exists(seed))return Load(pinned.path);
    for(const auto& entry:fs::directory_iterator(pinned.path))
        if(entry.path().filename()!=L".cmos.lock")Fail("MK2 CMOS profile directory is not empty or owned");
    const auto created=Atomic(seed,bytes);
    try {Atomic(current,bytes);}
    catch(...) {if(!Exists(current))RollBackSeed(seed,created,bytes);throw;}
    return Load(pinned.path);
}
std::string CompareAndSwapCmosProfile(const fs::path& directory,const std::vector<uint8_t>& image,const std::string& expected_sha256) {
    if(image.size()!=kSize)Fail("MK2 CMOS save requires exactly 16384 bytes");
    const auto sha=Sha256(image);
    Directory pinned(directory,false);OwnedFile lock(pinned.path/L".cmos.lock");
    const auto previous=Load(pinned.path);
    if(previous.sha256!=expected_sha256)Fail("MK2 CMOS profile changed since load; save rejected");
    Atomic(pinned.path/L"cmos.bin",image);return sha;
}
}
