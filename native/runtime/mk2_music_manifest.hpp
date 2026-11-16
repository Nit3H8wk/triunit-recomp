// MK2 Remastered music slots: DCS sound command -> neutral user slot in custom_audio/mk2/.
// Must match tools/mk2/music.json (checked by tools/mk2/check_music_package.py).
#pragma once
#include <array>
namespace mk2 {
inline constexpr std::array<const char*,8> music_slots{{
 "music-01","music-02","music-03","music-04","music-05","music-06","music-07","music-08",
}};
struct MusicCue {unsigned command,slot;};
inline constexpr std::array<MusicCue,18> music_cues{{
 {1,0},{2,0},{3,0},{4,0},
 {5,1},{6,1},
 {9,2},{10,2},
 {13,3},{14,3},
 {17,4},{18,4},
 {21,5},{22,5},
 {25,6},{26,6},
 {66,7},{61,7},
}};
}
