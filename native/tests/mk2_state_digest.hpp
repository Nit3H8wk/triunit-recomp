#pragma once
// Serialized machine state at an execution boundary and its SHA-256 (compile with -fno-access-control).
// Sections: TMS34010 CPU, CMOS, board/IO, main RAM, video RAM/palette/DMA, ADSP-2105 registers, device,
// execution, memories, DAC ring and domain, DCS link, scheduler clocks and machine domains.
#include "native/mk2/mk2_boot_ops.hpp"
#include "mk5_program.hpp"
#include <string>
#include <utility>
#include <vector>

namespace mk2test {
using Section=std::pair<std::string,std::vector<uint64_t>>;
template<class C> std::vector<uint64_t> Words(const C& c) { return std::vector<uint64_t>(c.begin(),c.end()); }
inline std::vector<Section> StateSections(const mk2::ResetTrace& s,const std::vector<uint16_t>* ram,const mk2::BootVideo* video,
                                          const mk2::DcsBootMachine& m) {
    std::vector<Section> out;
    std::vector<uint64_t> cpu{s.next_pc,s.status,s.cycles,s.instructions};
    for (auto r:s.a) cpu.push_back(r);
    for (auto r:s.b) cpu.push_back(r);
    out.push_back({"cpu",cpu});
    out.push_back({"cmos",Words(s.cmos)});
    out.push_back({"cmos_enable",{uint64_t(s.cmos_write_enabled)}});
    const auto& b=s.board;
    std::vector<uint64_t> board{b.main_horizon_,b.host_inputs_,b.live_host_domain_,b.live_discarded_input_events_,b.live_last_input_tick_,
        b.requested_ports_[0],b.requested_ports_[1],b.requested_ports_[2],b.dma_command,b.video_control,b.dip_switches,b.input0,b.input1,
        b.input2,b.vcount,b.display_address,b.scanline_events,b.active_updates,b.requested_p1_high_punch,b.requested_coin1,
        b.requested_start1,b.protection.Read(),bool(b.host_input_provider_)};
    for (auto x:b.io) board.push_back(x);
    for (auto& e:b.input_events) for (auto x:e) board.push_back(x);
    out.push_back({"board",board});
    if (ram) out.push_back({"ram",Words(*ram)});
    if (video) {
        out.push_back({"palette",Words(video->palette_ram)});
        out.push_back({"vram",Words(video->vram)});
        out.push_back({"shift",Words(video->shift_register)});
        std::vector<uint64_t> dma{video->dma_palette};
        for (auto x:video->dma_registers) dma.push_back(x);
        out.push_back({"video_dma",dma});
    }
    out.push_back({"dsp_registers",m.dsp.Registers()});
    out.push_back({"dsp_device",m.dsp.DeviceState()});
    out.push_back({"dsp_execution",m.dsp.ExecutionState()});
    out.push_back({"dsp_pm",Words(m.dsp.pm)});
    out.push_back({"dsp_dm",Words(m.dsp.dm)});
    out.push_back({"dsp_external_pm",Words(m.dsp.external_pm)});
    out.push_back({"dsp_control",Words(m.dsp.control)});
    out.push_back({"dsp_dac",Words(m.dsp.dac_buffer_)});
    out.push_back({"dsp_domain",{m.dsp.main_horizon_,m.dsp.live_host_domain_,m.dsp.service_irq_domain_,m.dsp.rebooted_,
        m.dsp.reset_pending_,m.dsp.dac_write_sample_,m.dsp.dac_last_ticks_,m.dsp.dac_bufin_,m.dsp.dac_bufout_,m.dsp.dac_enabled_,
        m.dsp.InstructionCount()}});
    out.push_back({"link",m.link.ExecutionState()});
    out.push_back({"scheduler",Words(m.SchedulerClocks())});
    out.push_back({"machine",{m.main_horizon_,m.valid_cmos_host_,m.operator_startup_profile_,m.operator_startup_horizon_,
        m.operator_draw_horizon_,m.operator_dma_start_,m.live_generation_,m.live_host_domain_}});
    return out;
}
// SHA-256 over every section: name, word count, then each word as 8 little-endian bytes.
inline std::string StateDigest(const std::vector<Section>& sections) {
    std::vector<uint8_t> bytes;
    for (const auto& [name,words]:sections) {
        bytes.insert(bytes.end(),name.begin(),name.end());
        bytes.push_back(0);
        const auto put=[&](uint64_t v) { for (unsigned n=0;n<8;++n) bytes.push_back(uint8_t(v>>(8*n))); };
        put(words.size());
        for (uint64_t v:words) put(v);
    }
    return Sha256(bytes);
}
inline std::string StateDigest(const mk2::BootContinuation& c,const mk2::DcsBootMachine& m) {
    return StateDigest(StateSections(c.ready,&c.main_ram,&c.video,m));
}
}
