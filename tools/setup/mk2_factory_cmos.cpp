// Setup tool (tools/setup/mk2.py): runs the generated MK2 program from a cleared CMOS through the cold boot with the
// generated executor (mk2::GeneratedBoot) and writes the 16 KiB CMOS image at its delivery boundary, after the game's
// own factory initialization. No CMOS content is versioned; the setup checks the result against the pinned SHA-256.
// usage: mk2_factory_cmos ROM_DIRECTORY OUTPUT_IMAGE
#include "native/mk2/mk2_cmos_image.hpp"
#include "native/mk2/mk2_dcs.hpp"
#include "native/mk2/mk2_executor.hpp"
#include <fstream>
#include <iostream>
#include <memory>

int main(int argc,char** argv) { try {
    if (argc!=3) throw std::runtime_error("usage: mk2_factory_cmos ROM_DIRECTORY OUTPUT_IMAGE");
    const auto program=mk2::LoadProgram(argv[1]);
    const auto rom=mk2::LoadDcsDataRoms(argv[1]);
    const auto boot=mk2::DecodeDcsBoot({rom.begin(),rom.begin()+0x1000});
    auto machine=std::make_unique<mk2::DcsBootMachine>(boot,rom);
    machine->dsp.SetTraceObservation(false);
    mk2::GeneratedBoot generated(program,*machine,nullptr,0xfc7d);  // cold boot, factory DIP word
    const auto& delivered=generated.Deliver();
    if (!generated.Delivered()) throw std::runtime_error("MK2 cold boot stopped before its delivery boundary");
    const auto image=mk2::EncodeCmosImage(delivered.ready.cmos);
    std::ofstream output(argv[2],std::ios::binary);
    output.write(reinterpret_cast<const char*>(image.data()),std::streamsize(image.size()));
    if (!output.flush()) throw std::runtime_error("cannot write the CMOS image");
    std::cout<<delivered.ready.next_pc<<' '<<delivered.ready.cycles<<'\n';
} catch (const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; } }
