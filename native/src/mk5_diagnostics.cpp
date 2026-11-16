#include "mk5_task_body.hpp"
#include <algorithm>
#include <stdexcept>
#include <unordered_set>

Mk5DiagnosticTrim Mk5TaskBodyRunner::CompactDiagnostics(){
    guard();
    if(!main_mode || !video)throw std::logic_error("diagnostic trim requires a live visual main loop");
    Mk5DiagnosticTrim dropped;
    if(s.writes.size()>65536){
        const auto before=s.writes.size();
        std::vector<Write16> retained;retained.reserve(before);
        std::unordered_set<uint32_t> seen;
        // RAM has already received every write. Preserve the most recent
        // non-RAM request at every address, including the DMA readback fallback.
        // Keep the original ordering of those requests; never edit their values.
        for(auto it=s.writes.rbegin();it!=s.writes.rend();++it){
            if(it->address_bit>=0x01000000u && it->address_bit<0x01400000u)continue;
            if(seen.insert(it->address_bit).second)retained.push_back(*it);
        }
        std::reverse(retained.begin(),retained.end());s.writes.swap(retained);
        dropped.writes=before-s.writes.size();
    }
    dropped.returns=f.check.returns.size();f.check.returns.clear();
    if(f.byte_writes.size()>16384){
        const auto before=f.byte_writes.size();
        std::vector<CmosBusWrite8> retained;retained.reserve(before);
        std::unordered_set<uint32_t> seen;
        // Preserve address membership used by the original unique-word audit.
        // CMOS writes and write-enable requests occupy disjoint address ranges.
        for(auto it=f.byte_writes.rbegin();it!=f.byte_writes.rend();++it)
            if(seen.insert(it->address_bit).second)retained.push_back(*it);
        std::reverse(retained.begin(),retained.end());f.byte_writes.swap(retained);
        dropped.cmos=before-f.byte_writes.size();
    }
    const auto before_irqs=irq.entries().size();dropped.scanlines=irq.scanlines().size();irq.DiscardDiagnostics();
    dropped.irqs=before_irqs-irq.entries().size();
    dropped.dma=video->commands.size();dropped.completions=video->completions.size();
    video->commands.clear();video->completions.clear();
    return dropped;
}
