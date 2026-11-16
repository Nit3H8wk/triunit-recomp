// MK1 Remastered music slots: sound-board music selector -> neutral user slot in custom_audio/mk1/.
#pragma once
#include <array>
namespace mk5audio {
struct RemasteredSlot {const char* slot;unsigned command;bool loop;};
inline constexpr std::array<RemasteredSlot,13> remastered_slots{{
 {"music-01",19,false},{"music-02",20,true},{"music-03",1,true},{"music-04",3,true},{"music-05",7,true},
 {"music-06",13,true},{"music-07",25,true},{"music-08",27,true},{"music-09",10,true},{"music-10",21,true},
 {"music-11",6,true},{"music-12",2,true},{"music-13",31,true},
}};
}
