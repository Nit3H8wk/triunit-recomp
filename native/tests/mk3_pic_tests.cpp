// MK3 serial PIC simulation: self-checks, then replay of an event file captured from the Original.
// Events: P = power-on (fresh MAME rand + device_reset), S = soft reset (device_reset, next draws),
// D = discard one draw (negative control), R = security read, W v = security_w offset 0 low byte,
// L v = io_w offset 1 (reset_w(v & 0x20)). Prints compact JSON: data per reset, every read with the
// post-read state, the final state and the number of draws.
#include "mk3_pic.hpp"
#include <cstdio>
#include <fstream>
#include <iostream>
#include <string>

namespace {
int failures = 0;
void Check(bool ok, const char* what) { if (!ok) { std::fprintf(stderr, "FAIL %s\n", what); ++failures; } }

void SelfChecks() {
    mk3::MameRand rand;
    Check(rand() == 0x574a3af2u && rand() == 0xde214fbeu, "LCG from the 0x9d14abd7 constructor seed");
    mk3::SerialPic pic;
    mk3::MameRand fresh;
    pic.Reset(fresh);
    Check(pic.data[10] == 0x15 && pic.data[11] == 0xb8 && pic.data[14] == 0 && pic.data[15] == 0, "date bytes for 1994-12-11");
    pic.Write(0x1f); Check(pic.Status() == 1 && pic.buff == 0, "rising clock keeps buff");
    pic.Write(0x0f); Check(pic.Status() == 0 && pic.buff == 0x0f && pic.idx == 0, "self-test nibble does not consume data");
    pic.ResetLine(false); Check(pic.buff == 0x0f, "reset_w(0) is a no-op");
    for (int i = 0; i < 256; ++i) pic.Write(0);
    Check(pic.idx == 0 && pic.buff == pic.data[15], "uint8_t index wraps after 256 clocks");
    pic.Write(0); Check(pic.buff == pic.data[0], "index modulo 16 after the wrap");
    Check(pic.Read() == pic.data[0] && pic.Status() == 1, "read returns buff and sets status");
    pic.ResetLine(true); Check(pic.idx == 0 && pic.buff == 0 && pic.status == 0, "reset_w(1) clears idx/status/buff");
}

std::string Hex(const std::array<uint8_t, 16>& d) {
    static const char* digits = "0123456789abcdef";
    std::string s;
    for (auto b : d) { s += digits[b >> 4]; s += digits[b & 15]; }
    return s;
}
} // namespace

int main(int argc, char** argv) {
    SelfChecks();
    if (failures) return 1;
    if (argc < 2) { std::puts("{\"self_checks\":\"passed\"}"); return 0; }
    std::ifstream events(argv[1]);
    if (!events) { std::fprintf(stderr, "cannot open events\n"); return 2; }
    mk3::MameRand rand;
    mk3::SerialPic pic;
    unsigned draws = 0;
    std::string resets, reads, sep_reset, sep_read;
    char kind;
    while (events >> kind) {
        unsigned value = 0;
        if (kind == 'W' || kind == 'L') events >> value;
        if (kind == 'P' || kind == 'S') {
            if (kind == 'P') { rand = mk3::MameRand(); draws = 0; }
            pic.Reset(rand); draws += 2;
            resets += sep_reset + "\"" + Hex(pic.data) + "\""; sep_reset = ",";
        } else if (kind == 'D') { rand(); ++draws; }
        else if (kind == 'R') {
            const unsigned got = pic.Read();
            reads += sep_read + "[" + std::to_string(got) + "," + std::to_string(pic.idx) + "," + std::to_string(pic.buff) + "," + std::to_string(pic.status) + "]";
            sep_read = ",";
        } else if (kind == 'W') pic.Write(uint8_t(value));
        else if (kind == 'L') pic.ResetLine(value & 0x20);
        else { std::fprintf(stderr, "unknown event %c\n", kind); return 2; }
    }
    std::cout << "{\"self_checks\":\"passed\",\"draws\":" << draws << ",\"resets\":[" << resets << "],\"reads\":[" << reads
              << "],\"final\":[" << unsigned(pic.idx) << "," << unsigned(pic.buff) << "," << unsigned(pic.status) << "]}\n";
    return 0;
}
