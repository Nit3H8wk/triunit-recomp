#pragma once
#include <cstdint>
namespace mk5audio {
class WilliamsAudio;
struct AudioDiagnosticCounts {uint64_t commands=0,events=0,samples=0;};
AudioDiagnosticCounts GameAudioDiagnosticCounts();
// Publishes pending samples first. Without a consumer, retains the full history.
bool TrimGameAudioDiagnostics();
// Exclusive scope for one new live history. It never attaches to a replay log.
class GameAudioScope {
 WilliamsAudio* board;
public:
 explicit GameAudioScope(WilliamsAudio&);
 ~GameAudioScope();
 GameAudioScope(const GameAudioScope&)=delete;GameAudioScope& operator=(const GameAudioScope&)=delete;
};
namespace detail {
struct GameAudioHooks {void(*sync)(uint64_t)=nullptr;void(*write)(uint64_t,uint16_t)=nullptr;bool output_clock=false;};
inline thread_local GameAudioHooks hooks;
}
// Header-only null path keeps historical standalone targets independently linkable.
inline void GameAudioWrite(uint64_t tms_cycles,uint16_t value){if(detail::hooks.write)detail::hooks.write(tms_cycles,value);}
inline void GameAudioSync(uint64_t tms_cycles){if(detail::hooks.sync)detail::hooks.sync(tms_cycles);}
inline bool GameAudioUsesOutputClock(){return detail::hooks.output_clock;}
}
