#pragma once
// mk5_win_compat.hpp — Minimal Windows type stand-ins for Linux (Phase 1).
// Included instead of <windows.h> on non-Windows platforms so the existing
// public APIs compile unchanged. Phase 2/3 replace these with real SDL3/Vulkan
// backends; until then they provide headless no-op behavior.
#ifndef _WIN32
using DWORD=unsigned;
using ULONGLONG=unsigned long long;
using WORD=unsigned short;
using BYTE=unsigned char;
using UINT=unsigned;
using ULONG=unsigned;
using USHORT=unsigned short;
using USAGE=USHORT;
using BOOL=int;
#define TRUE 1
#define FALSE 0
using HMODULE=void*;
using HANDLE=void*;
using HWND=void*;
using HRAWINPUT=void*;
using WPARAM=unsigned long long;
using LPARAM=long long;
using NTSTATUS=int;
using NTAPI=int;
using PHIDP_PREPARSED_DATA=void*;
using PHIDP_CAPS=void*;
using PHIDP_VALUE_CAPS=void*;
using PUSAGE=USHORT*;
using PUSHORT=USHORT*;
using PCHAR=char*;
#define ERROR_SUCCESS 0
using WINAPI=int;
using NTAPI=int;
#define HIDP_STATUS_SUCCESS 0
#define HidP_Input 0
// File I/O constants and stubs for portable compilation.
#define INVALID_HANDLE_VALUE ((HANDLE)-1)
#define GENERIC_WRITE 0x40000000u
#define CREATE_NEW 1
#define FILE_ATTRIBUTE_NORMAL 0x80u
#define FILE_SHARE_READ 0x1u
#define MAXDWORD 0xFFFFFFFFu
inline HANDLE CreateFileW(const char*,unsigned,int,const void*,int,unsigned,const void*){return INVALID_HANDLE_VALUE;}
inline BOOL WriteFile(HANDLE,const void*,unsigned,unsigned*,void*){return FALSE;}
inline BOOL CloseHandle(HANDLE){return TRUE;}
inline BOOL DeleteFileW(const char*){return TRUE;}
struct LARGE_INTEGER{long long QuadPart;};
#define FILE_BEGIN 0
inline BOOL SetFilePointerEx(HANDLE,LARGE_INTEGER,LARGE_INTEGER*,unsigned){return FALSE;}
inline BOOL SetEndOfFile(HANDLE){return FALSE;}
#define MOVEFILE_REPLACE_EXISTING 0x1u
#define MOVEFILE_WRITE_THROUGH 0x2u
inline BOOL MoveFileExW(const char*,const char*,unsigned){return FALSE;}
// Timing and error stubs.
inline ULONGLONG GetTickCount64(){return 0;}
inline DWORD GetTickCount(){return 0;}
inline void Sleep(unsigned){}
inline DWORD GetLastError(){return 0;}
// Wide environment and file-info stubs.
inline const wchar_t* _wgetenv(const wchar_t*){return nullptr;}
struct FILETIME{unsigned long long dwLowDateTime,dwHighDateTime;};
struct BY_HANDLE_FILE_INFORMATION{DWORD dwFileAttributes;FILETIME ftCreationTime,ftLastAccessTime,ftLastWriteTime;unsigned long long nFileSizeHigh,nFileSizeLow;DWORD dwVolumeSerialNumber,nFileIndexHigh,nFileIndexLow;};
inline BOOL GetFileInformationByHandle(HANDLE,BY_HANDLE_FILE_INFORMATION*){return FALSE;}
#define FILE_TYPE_DISK 3
inline DWORD GetFileType(HANDLE){return 0;}
inline BOOL IsWindow(HWND){return FALSE;}
#define FILE_ATTRIBUTE_REPARSE_POINT 0x400u
#define FILE_ATTRIBUTE_DIRECTORY 0x10u
inline DWORD GetWindowThreadProcessId(HWND,DWORD*){return 0;}
inline DWORD GetCurrentProcessId(){return 0;}
inline int GetClassNameW(HWND,wchar_t*,int){return 0;}
typedef BOOL(*EnumWindowsProc)(HWND,LPARAM);
inline BOOL EnumWindows(EnumWindowsProc,LPARAM){return FALSE;}
// Virtual-key codes used by the keyboard input map.
#define VK_BACK 0x08
#define VK_F2 0x71
#define VK_OEM_MINUS 0x2D
#define VK_OEM_PLUS 0x2B
// XInput button masks (match xinput.h).
#define XINPUT_GAMEPAD_A 0x0004
#define XINPUT_GAMEPAD_B 0x0008
#define XINPUT_GAMEPAD_X 0x0010
#define XINPUT_GAMEPAD_Y 0x0020
#define XINPUT_GAMEPAD_LEFT_SHOULDER 0x0040
#define XINPUT_GAMEPAD_RIGHT_SHOULDER 0x0080
#define XINPUT_GAMEPAD_BACK 0x0100
#define XINPUT_GAMEPAD_START 0x0200
#define XINPUT_GAMEPAD_LEFT_THUMB 0x0400
#define XINPUT_GAMEPAD_RIGHT_THUMB 0x0800
// More file and environment stubs.
#define INVALID_FILE_ATTRIBUTES 0xFFFFFFFFu
#define ERROR_FILE_NOT_FOUND 2
#define ERROR_PATH_NOT_FOUND 3
#define FILE_READ_ATTRIBUTES 0x80u
inline DWORD GetFileAttributesW(const char*){return INVALID_FILE_ATTRIBUTES;}
inline BOOL CreateDirectoryW(const char*,const void*){return FALSE;}
inline DWORD GetEnvironmentVariableA(const char*,char*,DWORD){return 0;}
inline HWND GetForegroundWindow(){return nullptr;}
#define FILE_SHARE_WRITE 0x2u
#define OPEN_EXISTING 3
#define FILE_FLAG_BACKUP_SEMANTICS 0x20000000u
#define FILE_FLAG_OPEN_REPARSE_POINT 0x00200000u
#define FILE_FLAG_DELETE_ON_CLOSE 0x04000000u
#define GENERIC_READ 0x80000000u
inline BOOL GetFileSizeEx(HANDLE,LARGE_INTEGER*){return FALSE;}
inline BOOL ReadFile(HANDLE,void*,unsigned,unsigned*,void*){return FALSE;}
inline short GetAsyncKeyState(int){return 0;}
#define FILE_SHARE_DELETE 0x4u
#define FILE_FLAG_SEQUENTIAL_SCAN 0x8000000u
#define DELETE 0x10000u
#define FILE_FLAG_WRITE_THROUGH 0x80000000u
#define CREATE_ALWAYS 2
#define CP_UTF8 65001
struct FILE_DISPOSITION_INFO{BOOL DeleteFile;};
#define FileDispositionInfo 0
inline BOOL FlushFileBuffers(HANDLE){return FALSE;}
inline BOOL SetWindowTextW(HWND,const wchar_t*){return FALSE;}
inline UINT MultiByteToWideChar(unsigned,int,const char*,int,wchar_t*,int){return 0;}
inline UINT WideCharToMultiByte(unsigned,int,const wchar_t*,int,char*,int,const char*,const char*){return 0;}
struct FILE_RENAME_INFO{BOOL ReplaceIfExists;HANDLE RootDirectory;wchar_t* FileName;unsigned long FileNameLength;};
#define FileRenameInfo 2
#define ERROR_ACCESS_DENIED 5
#define ERROR_SHARING_VIOLATION 32
#define ERROR_LOCK_VIOLATION 33
#define OPEN_ALWAYS 4
inline BOOL SetFileInformationByHandle(HANDLE,unsigned,const void*,unsigned){return FALSE;}
#endif
