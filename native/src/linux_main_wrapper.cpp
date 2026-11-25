// Linux main wrapper: converts main() to wmain() for compatibility with Windows-style entry points
#include <string>
#include <vector>
#include <cwchar>

int wmain(int argc, wchar_t** argv);

static std::wstring to_wide(const char* str) {
    std::wstring result;
    while (*str) {
        result.push_back(static_cast<wchar_t>(*str++));
    }
    return result;
}

int main(int argc, char** argv) {
    std::vector<std::wstring> wide_args;
    for (int i = 0; i < argc; i++) {
        wide_args.push_back(to_wide(argv[i]));
    }
    
    std::vector<wchar_t*> wide_argv;
    for (auto& arg : wide_args) {
        wide_argv.push_back(arg.data());
    }
    
    return wmain(argc, wide_argv.data());
}
