#pragma once
// The only launcher file that names the supported games: the compatibility list and the legal notice.
// Game names are plain text used to identify compatibility; no logo, art or other mark is used. The cabinet marquee
// shows only the board and revision (`marquee`); the name appears in a small "Compatible with" line.
#include <array>
namespace mklauncher {
inline constexpr const wchar_t* productName=L"TriUnit Recomp";
inline constexpr const wchar_t* productTitle=L"TRIUNIT RECOMP";
// Index = launcher game index (0, 1, 2) and the setup id of tools/setup/setup.py. manifest: the versioned ROM manifest
// the setup checks the user's files against (tools/setup/paths.py MANIFESTS). Only games the setup supports are listed.
struct CompatibleGame {const wchar_t* name;const wchar_t* title;const wchar_t* revision;const wchar_t* board;const wchar_t* setupId;
                       const wchar_t* manifest;const wchar_t* marquee;};
inline constexpr std::array<CompatibleGame,3> compatibleGames{{
 {L"MORTAL KOMBAT",L"Mortal Kombat",L"5.0",L"T-Unit (ADPCM sound)",L"mk1",L"tools/mk1/roms-l1.json",L"T-UNIT  /  REV 5.0"},
 {L"MORTAL KOMBAT II",L"Mortal Kombat II",L"L3.1",L"T-Unit",L"mk2",L"tools/mk2/roms-l31.json",L"T-UNIT  /  REV L3.1"},
 {L"MORTAL KOMBAT 3",L"Mortal Kombat 3",L"2.1",L"Wolf Unit",L"mk3",L"tools/mk3/roms-21.json",L"WOLF UNIT  /  REV 2.1"},
}};
inline constexpr std::array<const wchar_t*,3> legalNotice{{
 L"Independent project, not affiliated with or endorsed by Warner Bros. Entertainment Inc. or NetherRealm Studios.",
 L"No game files are included: the game's C++ is generated on this machine from the user's own ROM files.",
 L"Game names are used only to identify compatibility; all marks belong to their respective owners.",
}};
}
