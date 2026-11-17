#pragma once
#include "mk2_task_batch.hpp"
#include "mk2_valid_cmos_continuation.hpp"
#include "mk2_live_limits.hpp"
#include <utility>
namespace mk2 {
class LiveHostContinuation;
LiveHostContinuation RunValidLiveHost(const Program&,const ValidCmosContinuation&,DcsBootMachine&,
    std::function<uint32_t(uint64_t)>,uint64_t minimum_stop_cycle);
LiveHostContinuation ResumeValidLiveHost(const Program&,LiveHostContinuation&&,DcsBootMachine&,uint64_t minimum_stop_cycle);
// Only this API creates/consumes instruction-boundary live chains; observations span the last bounded chunk.
class LiveHostContinuation {
    friend LiveHostContinuation RunValidLiveHost(const Program&,const ValidCmosContinuation&,DcsBootMachine&,std::function<uint32_t(uint64_t)>,uint64_t);
    friend LiveHostContinuation ResumeValidLiveHost(const Program&,LiveHostContinuation&&,DcsBootMachine&,uint64_t);
    TaskBatchInit state_;
    DcsBootMachine* owner_=nullptr;
    uint64_t generation_=0;
    LiveHostContinuation(TaskBatchInit&& state,DcsBootMachine& owner,uint64_t generation)
        :state_(std::move(state)),owner_(&owner),generation_(generation){}
    // Save-state value fields; the owning machine binding never changes.
    template<class A> friend void Fields(A& a,LiveHostContinuation& c){a(c.state_,c.generation_);}
public:
    LiveHostContinuation(const LiveHostContinuation&)=delete;
    LiveHostContinuation& operator=(const LiveHostContinuation&)=delete;
    LiveHostContinuation(LiveHostContinuation&& other)noexcept
        :state_(std::move(other.state_)),owner_(std::exchange(other.owner_,nullptr)),generation_(std::exchange(other.generation_,0)){}
    LiveHostContinuation& operator=(LiveHostContinuation&& other)noexcept {
        if(this!=&other){state_=std::move(other.state_);owner_=std::exchange(other.owner_,nullptr);generation_=std::exchange(other.generation_,0);}return *this;
    }
    const TaskBatchInit& State() const {
        if(!owner_)throw std::runtime_error("MK2 live continuation was consumed");
        return state_;
    }
    uint64_t Generation() const { return generation_; }
    void ValidateBoundary(const Program&,const DcsBootMachine&) const;
};
}
