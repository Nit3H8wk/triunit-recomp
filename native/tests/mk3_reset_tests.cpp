#include "mk3_reset.hpp"
#include "mk3_dcs.hpp"
#include "mk3_cpu.hpp"
#include <fstream>
#include <iterator>
#include <cstdio>
#include <iostream>
#include <stdexcept>

// Prints the native slices as one JSON line for tools/mk3/test_reset.py; rejects altered program bytes.
static void Print(const char* name, const mk3::ResetTrace& s) {
    std::printf("\"%s\":{\"pc\":%u,\"status\":%u,\"cycles\":%llu,\"instructions\":%llu,\"registers\":[", name,
                s.pc, s.status, (unsigned long long)s.cycles, (unsigned long long)s.instructions);
    for (unsigned i = 0; i < 31; ++i) std::printf("%s%u", i ? "," : "", i < 16 ? s.a[i] : s.b[i - 16]);
    for (const auto* list : {&s.writes, &s.reads}) {
        std::printf("],\"%s\":[", list == &s.writes ? "writes" : "reads");
        for (size_t i = 0; i < list->size(); ++i)
            std::printf("%s[%u,%u,%u,%llu]", i ? "," : "", (*list)[i].pc, (*list)[i].address_bit, (*list)[i].value,
                        (unsigned long long)(*list)[i].cycle);
    }
    std::printf("],\"video_control\":%u,\"io\":[%u,%u],\"ram\":{", s.video_control, s.io[0], s.io[1]);
    bool first = true;
    for (const auto& [address, value] : s.ram) { std::printf("%s\"%u\":%u", first ? "" : ",", address, value); first = false; }
    std::printf("}}");
}

int wmain(int argc, wchar_t** argv) {
    if (argc != 4) return 2;
    if (!_wfreopen(argv[3], L"w", stdout)) return 3;  // Full traces exceed the test runner output bound.
    try {
        const auto program = mk3::LoadProgram(argv[1]);
        for (const uint32_t pc : {0xff814a40u, 0xff814ae0u}) {
            auto altered = program;
            altered.bytes[(pc - mk3::kProgramBaseBit) / 8] ^= 1;
            bool rejected = false;
            try { mk3::PowerOn(altered); } catch (const std::runtime_error&) { rejected = true; }
            if (!rejected) throw std::runtime_error("altered program accepted by the reset");
        }
        bool rejected = false;
        try { mk3::VerifyProgramLanes({}, {}); } catch (const std::runtime_error&) { rejected = true; }
        if (!rejected) throw std::runtime_error("empty lanes accepted");
        std::ifstream seed(argv[2], std::ios::binary);
        const std::vector<uint8_t> cmos{std::istreambuf_iterator<char>(seed), std::istreambuf_iterator<char>()};
        std::printf("{");
        Print("prefix", mk3::RunGenerated(program, cmos, 0xff814aa0u));
        std::printf(",");
        Print("cmos", mk3::RunGenerated(program, cmos, 0xffadaf40u));
        std::printf(",");
        Print("cmos_check", mk3::RunCmosCheck(program, cmos));
        std::printf(",");
        Print("pic_check", mk3::RunPicCheck(program, cmos));
        std::printf(",");
        Print("init_text", mk3::RunInitToText(program, cmos));
        std::printf(",");
        Print("serial", mk3::RunToSerial(program, cmos));
        std::printf(",");
        Print("sound_wait", mk3::RunToSoundWait(program, cmos));
        const auto boot = mk3::LoadDcsBoot(argv[1]);
        std::printf(",\"dcs_boot\":[");
        for (size_t i = 0; i < boot.size(); ++i) std::printf("%s%u", i ? "," : "", boot[i]);
        std::printf("]}\n");
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
