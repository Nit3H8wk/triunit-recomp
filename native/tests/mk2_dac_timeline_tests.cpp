#include "../mk2/mk2_adsp.hpp"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wsign-compare"
#include "dmadac.cpp"
#pragma GCC diagnostic pop
#include <cstring>
#include <iostream>
#include <memory>

namespace {
void check(bool condition,const char* message) {
    if (!condition) throw std::runtime_error(message);
}
bool identical(const std::vector<float>& a,const std::vector<float>& b) {
    return a.size()==b.size() && std::memcmp(a.data(),b.data(),a.size()*sizeof(float))==0;
}
struct Capture {
    std::vector<float> samples;
    void Attach(mk2::AdspBoot& dsp) {
        dsp.SetDacObserver([this](uint64_t first,const float* data,size_t count) {
            check(first==samples.size(),"PCM absolute sample index has a gap or overlap");
            check(count && count<=512,"PCM observer exceeds bounded callback storage");
            samples.insert(samples.end(),data,data+count);
        });
    }
};
void configure(mk2::AdspBoot& dsp) {
    dsp.control[31]=0xc10;dsp.control[15]=0xe82;
    dsp.i[7]=0x400;dsp.l[7]=480;dsp.m[5]=1;
    dsp.SetInstructionTicks(1234567);dsp.SportTransmit(0);
}
}
int main() {try {
    {
        auto held=std::make_unique<mk2::DcsBootMachine>(std::vector<uint32_t>(376));
        auto control=std::make_unique<mk2::DcsBootMachine>(std::vector<uint32_t>(376));
        Capture silent;silent.Attach(held->dsp);
        for (auto* machine:{held.get(),control.get()}) {
            machine->link.HostWrite(0x01d01030,0);machine->link.Synchronize();
            machine->MainInstruction(125001);
        }
        check(silent.samples.size()==626 && std::all_of(silent.samples.begin(),silent.samples.end(),[](float value){return value==0;}),
              "disabled DAC must deliver chronological silence at each 50Hz sound deadline");
        check(held->dsp.DeviceState()==control->dsp.DeviceState() && held->dsp.Registers()==control->dsp.Registers() &&
              held->dsp.trace==control->dsp.trace && !held->dsp.InstructionCount(),
              "disabled observer must not execute or change the reset-held DSP");
    }
    machine_config config;
    dmadac_sound_device reference(config,"dac",nullptr);reference.device_start();
    mk2::DcsLink link,plain_link;
    auto dsp=std::make_unique<mk2::AdspBoot>(std::vector<uint32_t>(376),link);
    auto plain=std::make_unique<mk2::AdspBoot>(std::vector<uint32_t>(376),plain_link);
    dsp->main_horizon_=plain->main_horizon_=100091930;
    Capture observed;observed.Attach(*dsp);
    dsp->DacUpdate(0);plain->DacUpdate(0);
    check(observed.samples.empty(),"MAME does not update the stream at time zero");
    configure(*dsp);configure(*plain);reference.enable(1);
    std::vector<float> expected;
    uint64_t written=0;
    auto update=[&](uint64_t ticks) {
        // disound.cpp includes the current sample on the absolute source clock.
        const auto end=ticks/3200+1;
        reference.m_channel->output.assign(size_t(end-written),0.0f);
        reference.sound_stream_update(*reference.m_channel);
        expected.insert(expected.end(),reference.m_channel->output.begin(),reference.m_channel->output.end());
        written=end;dsp->DacUpdate(ticks);plain->DacUpdate(ticks);
        check(identical(observed.samples,expected),"chronological PCM differs from the unchanged upstream DMADAC kernel");
        check(dsp->DeviceState()==plain->DeviceState() && dsp->Registers()==plain->Registers() &&
              dsp->dac_buffer_==plain->dac_buffer_,"observer changed DSP76 or physical DAC state");
        check(dsp->dac_bufin_==reference.m_bufin && dsp->dac_bufout_==reference.m_bufout,
              "native/reference DAC cursors differ");
    };
    // Cold 48 kHz history is zero. Rate conversion reprojects its write index
    // to floor(t*31250), then enable flush includes that current sample.
    update(1234567);update(1235199);update(1235200);update(1235201);
    constexpr uint64_t first_transfer=2002567;
    update(first_transfer);
    const size_t nonzero_begin=observed.samples.size();
    check(nonzero_begin==first_transfer/3200+1,"fractional transfer time lost its absolute phase");
    const int16_t extremes[]={-32768,-32767,-1,0,1,32767};
    uint64_t tick=first_transfer;
    for (unsigned packet=0;packet<180;++packet) {
        if (packet) {tick+=packet%7==0?1152000:768000;update(tick);}
        const auto start=dsp->i[7];
        std::array<int16_t,240> data{};
        for (unsigned n=0;n<data.size();++n) {
            data[n]=packet?int16_t(uint16_t(packet*7919+n*131)):extremes[n%6];
            dsp->external_pm[start+n]=plain->external_pm[start+n]=uint32_t(uint16_t(data[n]))<<8;
        }
        // Same original PCM is independently normalized/enqueued by dmadac.h.
        reference.transfer(0,1,1,240,data.data());
        dsp->imask=plain->imask=packet?0x20:0;
        if (dsp->sport_irq1_asserted) {dsp->ClearSportIrq1(tick);plain->ClearSportIrq1(tick);}
        dsp->SportTransfer(tick);plain->SportTransfer(tick);
    }
    update(tick+768000);update(tick+768001);update(tick+3000000);
    check(observed.samples[nonzero_begin]==float(-32768)*(1.0f/32767.0f) &&
          observed.samples[nonzero_begin+5]==1.0f,"normalization changed sign/full-scale or first nonzero phase");
    check(observed.samples.back()==0.0f,"an empty DMADAC must produce silence");
    check(dsp->dac_bufin_<32768 && dsp->sport_pcm.size()==43200,"ring wrap was not exercised");
    // Disable flushes before clearing both cursors; re-enable must retain the
    // absolute sample phase and discard the disabled queue's remainder.
    tick+=3001000;update(tick);
    dsp->SetInstructionTicks(tick);plain->SetInstructionTicks(tick);
    dsp->WriteControl(0x3fff,0x10);plain->WriteControl(0x3fff,0x10);reference.enable(0);
    update(tick+3199);configure(*dsp);configure(*plain);reference.enable(1);
    update(tick+6400);
    check(dsp->DeviceState()==plain->DeviceState() && identical(observed.samples,expected),"disable/re-enable changed clock or state");
    const auto before=dsp->DeviceState();const auto count=observed.samples.size();
    bool rejected=false;try {dsp->DacUpdate(tick);}catch(const std::runtime_error&) {rejected=true;}
    check(rejected && before==dsp->DeviceState() && count==observed.samples.size(),"backwards time must reject before mutation/output");
    std::cout<<"PASS upstream DMADAC chronological float32: "<<count<<" samples, 180 packets, silence, phase, extrema, wrap, disable/re-enable, observer equality\n";
}catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}}
