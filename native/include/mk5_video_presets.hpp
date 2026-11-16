#pragma once
#include <array>
namespace mk5video {
struct Preset{const wchar_t* label;const wchar_t* scanlines;const wchar_t* crt;};
// IDs 0..7 are persisted by existing profiles; append new entries.
inline constexpr int phosphor_index=9;
inline constexpr std::array<Preset,10> presets{{
 {L"DESATIVADAS",L"0",L"off"},{L"SUAVES / 25%",L"0.25",L"off"},
 {L"MEDIAS / 50%",L"0.5",L"off"},{L"FORTES / 75%",L"0.75",L"off"},
 {L"BVM / 1080p",L"0",L"bvm-1080"},{L"BVM / 4K",L"0",L"bvm-4k"},
 {L"BVM / SUAVE",L"0",L"bvm-soft"},{L"CRT / ENERGIA",L"0",L"energy"},
 {L"PVM / SUAVE",L"0",L"pvm"},
 {L"CRT / F\u00D3SFORO",L"0",L"phosphor"}
}};
}
