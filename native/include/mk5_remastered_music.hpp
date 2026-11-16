#pragma once
#include <array>
#include <cstdint>
#include <filesystem>
#include <vector>
#include <string>
namespace mk5audio {
// Presentation only. Never sends commands to or modifies the original board.
// Music comes from the user's custom_audio/mk1 slots; a missing or unreadable slot keeps the board's music.
class RemasteredMusic {
 struct Slot {std::vector<int16_t> pcm;uint64_t begin=0,end=0,repeat_begin=0,repeat_end=0;bool loop=true;float gain=.125f;};
 std::vector<Slot> tracks;
 std::array<uint64_t,32> commands{};
 int active=-1;uint64_t position=0,limit=0,starts=0,rendered=0,clipped=0,loops=0,finishes=0;unsigned loaded=0;
public:
 explicit RemasteredMusic(const std::filesystem::path& directory);
 void Command(uint16_t value);
 std::array<int16_t,2> Render(int16_t original,float effects);
 unsigned ActiveCommand()const;
 std::string CommandsJson()const;
 unsigned LoadedSlots()const{return loaded;}
 uint64_t Loops()const{return loops;}uint64_t Finishes()const{return finishes;}
 uint64_t Starts()const{return starts;}uint64_t Rendered()const{return rendered;}
 uint64_t Clipped()const{return clipped;}
};
}
