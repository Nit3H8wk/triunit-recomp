#pragma once
#include "mk2_boot_ops.hpp"
namespace mk2 {
struct ValidCmosContinuation : BootContinuation {
    std::vector<std::array<uint64_t,34>> cpu_trace;
    uint64_t executed_instructions=0;
};
}
