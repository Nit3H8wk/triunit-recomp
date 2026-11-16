#pragma once
#include "mk2_boot_ops.hpp"
#include <functional>

namespace mk2 {
// Executes the generated whole-program closure from the reset vector. Game behaviour comes only from
// ExecuteFirstFightStatic (tools/mk2/generate_architectural.py); this file holds the route: the legal input
// timeline, the qualified DcsBootMachine admissions and the delivery boundary, each at an exact (PC, cycle).
enum class BootRoute { factory, valid_cmos, test_switch };
enum class BootEvent { video_ready, press_p1_high_punch, release_p1_high_punch, admit_delay, admit_startup, admit_draw, deliver };
struct BootBoundary {
    BootEvent event;
    uint32_t pc;
    uint64_t cycle; // 0: first arrival at pc after the previous boundary.
};
// Executed by the generated closure (mk2_task_batch.cpp), one instruction.
bool ExecuteGeneratedInstruction(BootOps& o);

class GeneratedBoot {
    const Program& program_;
    DcsBootMachine& machine_;
    BootContinuation state_;
    BootRoute route_;
    std::vector<BootBoundary> boundaries_;
    size_t next_ = 0;
    std::function<void(BootVideo&)> video_ready_;
    void Apply(const BootBoundary&);
    void Step(BootOps&);
public:
    // cmos: the loaded 16 KiB NVRAM image (valid CMOS and Test Switch routes); nullptr is the cold factory boot.
    GeneratedBoot(const Program&, DcsBootMachine&, const std::vector<uint8_t>* cmos, uint16_t dsw);
    BootRoute Route() const { return route_; }
    const std::vector<BootBoundary>& Boundaries() const { return boundaries_; }
    // Hook at the end of the original video initialization (remastered presentation layers only).
    void OnVideoReady(std::function<void(BootVideo&)> hook) { video_ready_ = std::move(hook); }
    // Runs until next_pc==pc and cycles==cycle, before that instruction (route boundaries on the way apply).
    void RunTo(uint32_t pc, uint64_t cycle);
    // Runs to the next arrival at pc (now included), before that instruction.
    void RunToPc(uint32_t pc);
    // Runs to the route's delivery boundary, where the generated continuations take over.
    BootContinuation& Deliver();
    BootContinuation& State() { return state_; }
    bool Delivered() const { return next_ == boundaries_.size(); }
    // Runs to the boundary of `event` and stops before applying it.
    BootContinuation& RunToBoundary(BootEvent event);
};
// The delivered state as a continuation type (TaskBatchInit, ValidCmosContinuation).
template<class Continuation> Continuation DeliverAs(GeneratedBoot& boot) {
    Continuation out; static_cast<BootContinuation&>(out)=std::move(boot.Deliver()); return out;
}
}
