#pragma once
#include <cstdint>
#include <set>
#include <tuple>
#include <vector>

namespace mk3 {
// Execution profiles of the same generated code (user decision of 10/11/2026, plan 2026-11-10-mk3-jogavel-acelerado.md):
// - Strict: certification and tests. A translated block or device path not yet compared with the Original rejects
//   with its PC, exactly as the measured-only build did.
// - Game: playable preview. Translated-but-unverified blocks and paths run; the first execution of each is recorded
//   here. Untranslated code or behavior rejects in both profiles.
// Nothing is injected, normalized or invented in either profile.
enum class Profile : uint8_t { Strict, Game };

// What a first-execution key names. The id is a PC (TMS bit address / ADSP PM word) or a device path number.
enum class Unverified : uint8_t { TmsBlock, TmsEdge, AdspBlock, AdspEdge, DmaPath, IrqPath, DevicePath };

// Compact first-execution log: one entry per distinct (kind, id, from), in first-seen order with its cycle.
struct FirstExecution {
    struct Entry { Unverified kind; uint32_t id, from; uint64_t cycle; };
    std::vector<Entry> order;
    std::set<std::tuple<uint8_t, uint32_t, uint32_t>> seen;
    // Returns true on the first execution of this key.
    bool Note(Unverified kind, uint32_t id, uint64_t cycle, uint32_t from = 0) {
        if (!seen.emplace(uint8_t(kind), id, from).second) return false;
        order.push_back({kind, id, from, cycle});
        return true;
    }
};

// Route-verified keys (decision 1, plan 2026-11-10-mk3-cobertura-em-ondas.md): the FirstExecution keys of
// tools/mk3/route_verified.json, compiled into the generated units (tools/mk3/generate.py, RouteVerifiedSet). Strict
// accepts a key in this set when the run was given it (Board::SetProfile); without it Strict stays lot-only, as in M2.
// Counted apart from the lot (generate.py states verified_lot / verified_route).
struct RouteVerified {
    std::set<std::tuple<uint8_t, uint32_t, uint32_t>> keys;
    bool Has(Unverified kind, uint32_t id, uint32_t from = 0) const { return keys.count({uint8_t(kind), id, from}) != 0; }
};
inline bool Accepted(const RouteVerified* routes, Unverified kind, uint32_t id, uint32_t from = 0) {
    return routes && routes->Has(kind, id, from);
}
const RouteVerified& RouteVerifiedSet();   // generated: mk3_tms_dispatch.cpp
}
