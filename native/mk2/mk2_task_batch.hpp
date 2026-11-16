#pragma once
#include "mk2_boot_ops.hpp"
#include <functional>

namespace mk2 {
inline constexpr unsigned kPreStartWindowCount=16;
inline constexpr unsigned kSelectionWindowCount=6;
inline constexpr unsigned kFirstFightWindowCount=97;
enum class HostOrigin { none, cold_first_fight, valid_cmos_draw, valid_cmos_live };
struct TaskBatchInit : BootContinuation {
    HostOrigin host_origin=HostOrigin::none;
    std::vector<std::array<uint64_t, 34>> cpu_trace;
    uint64_t executed_instructions = 0;
};
TaskBatchInit RunTaskBatchInit(const Program& program, const BootContinuation& prefix,
                              DcsBootMachine& machine, bool extended = false, bool next_batch = false);
void WriteTaskBatchObservations(const Program&, const BootContinuation&, DcsBootMachine&, bool extended = false, bool next_batch = false, bool larger_batch = false, bool coin_queue = false, bool coin_accounting = false, bool coin_pair = false, bool start_wait = false, bool next_wait = false, int prestart_window = -1, bool start_input = false, bool start_release = false, int selection_window = -1, int first_fight_window = -1, bool first_fight_high_punch = false);
TaskBatchInit RunCoinPairInit(const Program&, const TaskBatchInit&, DcsBootMachine&);
TaskBatchInit RunStartWaitInit(const Program&, const TaskBatchInit&, DcsBootMachine&);
TaskBatchInit RunNextWaitInit(const Program&, const TaskBatchInit&, DcsBootMachine&);
TaskBatchInit RunTranslatedContinuation(const Program&, const BootContinuation&, DcsBootMachine&,
                                       int first_fight_window = -1, bool observe_history = false);
struct HostControlBounds {
    unsigned start_window;
    uint64_t start_cycle, minimum_stop_cycle, maximum_cycle;
};
HostControlBounds HostControlRange(unsigned start_window = 85, int stop_window = -1);
// Defaults preserve the short measured replay; the CLI selects the longer translated range.
TaskBatchInit RunHostContinuation(const Program&, const TaskBatchInit&, DcsBootMachine&,
                                 std::function<uint32_t(uint64_t)> input_provider,
                                 unsigned start_window = 85, int stop_window = -1);
// Resume the same host session at a cooperative boundary, retaining its provider and device clocks.
TaskBatchInit ResumeHostContinuation(const Program&, const TaskBatchInit&, DcsBootMachine&,
                                    uint64_t minimum_stop_cycle);
struct ValidCmosContinuation;
ResetTrace RunTestSwitch(const Program&,ValidCmosContinuation,DcsBootMachine&,
                         std::function<uint32_t(uint64_t)>,const std::function<bool()>&);
struct ValidHostControlBounds { uint64_t start_cycle, maximum_stop_cycle, maximum_cycle; };
ValidHostControlBounds ValidHostControlRange();
TaskBatchInit RunValidHostContinuation(const Program&, const ValidCmosContinuation&, DcsBootMachine&,
                                      std::function<uint32_t(uint64_t)>, uint64_t minimum_stop_cycle);
TaskBatchInit ResumeValidHostContinuation(const Program&, const TaskBatchInit&, DcsBootMachine&,
                                         uint64_t minimum_stop_cycle);
}
