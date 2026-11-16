#pragma once
// Expected Original states are versioned only as SHA-256 digests (plan 2026-11-15-conformidade-legal.md, 2.3).
// Each digest covers the values as consecutive 8-byte little-endian words, exactly as the local oracle
// (pinned MAME + the user's ROMs) serializes them (tools/mk2/oracle_digest.py). No raw observation is kept.
#include "mk2_reset.hpp"
#include "../include/mk5_program.hpp"
#include <array>
#include <cstring>
#include <initializer_list>
#include <string>
#include <vector>

namespace mk2 {
inline std::string WordsDigest(const uint64_t* words, size_t count) {
    std::vector<uint8_t> bytes(count*8);
    for (size_t n=0;n<count;++n) for (unsigned k=0;k<8;++k) bytes[n*8+k]=uint8_t(words[n]>>(8*k));
    return Sha256(bytes);
}
inline std::string WordsDigest(const std::vector<uint64_t>& words) { return WordsDigest(words.data(),words.size()); }
inline std::string WordsDigest(std::initializer_list<uint64_t> words) { return WordsDigest(words.begin(),words.size()); }
template<class T, size_t N> std::string WordsDigest(const std::array<T,N>& values) {
    std::array<uint64_t,N> words{};
    for (size_t n=0;n<N;++n) words[n]=uint64_t(values[n]);
    return WordsDigest(words.data(),N);
}
// Flattened rows (input events, DMA tuples): row after row, word after word.
template<class T, size_t N> std::string RowsDigest(const std::vector<std::array<T,N>>& rows) {
    std::vector<uint64_t> words;
    for (const auto& row:rows) for (auto value:row) words.push_back(uint64_t(value));
    return WordsDigest(words);
}
template<size_t N> bool DigestIn(const std::string& digest, const char* const (&set)[N]) {
    for (const char* entry:set) if (digest==entry) return true;
    return false;
}
// CPU34: next PC, ST, executed cycles, A0..A15, B0..B14 (B15 is SP).
inline std::array<uint64_t,34> Cpu34(const ResetTrace& s) {
    std::array<uint64_t,34> row{s.next_pc,s.status,s.cycles};
    for (unsigned n=0;n<16;++n) row[3+n]=s.a[n];
    for (unsigned n=0;n<15;++n) row[19+n]=s.b[n];
    return row;
}
inline std::string Cpu34Digest(const ResetTrace& s) { const auto row=Cpu34(s); return WordsDigest(row.data(),row.size()); }
inline bool Cpu34Is(const ResetTrace& s, const char* digest) { return Cpu34Digest(s)==digest; }
inline bool Cpu34Is(const std::array<uint64_t,34>& row, const char* digest) { return WordsDigest(row.data(),row.size())==digest; }
// DSP76: AdspBoot::Registers(); `native_clock` removes the executed-instruction cycle the MAME cache lags by one.
inline std::string Dsp76Digest(std::vector<uint64_t> registers, bool native_clock=false) {
    if (native_clock && registers.size()>1) --registers[1];
    return WordsDigest(registers);
}
}
