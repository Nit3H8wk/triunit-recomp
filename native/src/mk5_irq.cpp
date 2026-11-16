#include "mk5_irq.hpp"
#include <limits>
#include <stdexcept>

namespace {
constexpr uint32_t ie=0x00200000;
constexpr uint16_t int1=2,int2=4,hi=0x200,di=0x400,wv=0x800;
void aligned(uint32_t pc){if(pc&15)throw std::runtime_error("MK 5.0 IRQ: unaligned translated PC");}
}
void Mk5IrqController::guard()const{
    if(memory_.ram.size()!=262144 || memory_.vram.size()!=524288 || memory_.palette.size()!=32768 || (started_ && ((cpu_.a[15]&15) || cpu_.a[15]<0x01000000 || cpu_.a[15]>0x01400000)))
        throw std::runtime_error("MK 5.0 IRQ: invalid exclusive CPU/buffer state");
}
void Mk5IrqController::guard_advance(uint64_t cycles)const{
    guard();
    constexpr uint64_t max=std::numeric_limits<uint64_t>::max();
    if(cycles>(max-elapsed_)/16 || cycles>max-cpu_.reference_cycles)
        throw std::runtime_error("MK 5.0 IRQ: time overflow");
    uint64_t end=elapsed_+cycles*16;
    if(started_ && end>=next_edge_ && ((end-next_edge_)/line_quanta_>=65536 || end>max-line_quanta_))
        throw std::runtime_error("MK 5.0 IRQ: scanline budget/clock overflow");
}
void Mk5IrqController::guard_frame(bool pushing)const{
    guard();
    if(pushing?cpu_.a[15]<0x01000040:cpu_.a[15]>0x013fffc0)
        throw std::runtime_error("MK 5.0 IRQ: frame outside guest RAM");
}
void Mk5IrqController::push(uint32_t pc,uint32_t value){
    cpu_.a[15]-=32;size_t i=(cpu_.a[15]-0x01000000)/16;
    for(unsigned j=0;j<2;++j){uint16_t w=uint16_t(value>>(j*16));memory_.ram.at(i+j)=w;cpu_.writes.push_back({pc,cpu_.a[15]+16*j,w});}
}
uint32_t Mk5IrqController::pop(){
    size_t i=(cpu_.a[15]-0x01000000)/16;uint32_t value=memory_.ram.at(i)|(uint32_t(memory_.ram.at(i+1))<<16);cpu_.a[15]+=32;return value;
}
Mk5IrqController::Mk5IrqController(const VerifiedMk5Program& p,ResetTrace& c,Mk5MemoryBuffers& m,const Mk5IrqEpoch& epoch)
    :program_(p),cpu_(c),memory_(m),io_(epoch.io),next_scanline_(epoch.next_scanline){
    guard();aligned(cpu_.next_original_pc);
    if(p.bytes.size()!=1048576 || p.sha256!=kMk5ProgramSha256 || Sha256(p.bytes)!=kMk5ProgramSha256)
        throw std::runtime_error("MK 5.0 IRQ: verified ROM required");
    validate_epoch(epoch.quanta_to_next_scanline);
}
Mk5IrqController::Mk5IrqController(const VerifiedMk5Program& p,ResetTrace& c,Mk5MemoryBuffers& m)
    :program_(p),cpu_(c),memory_(m),io_{},next_scanline_(0),started_(false){
    guard();
    if(p.bytes.size()!=1048576 || p.sha256!=kMk5ProgramSha256 || Sha256(p.bytes)!=kMk5ProgramSha256)
        throw std::runtime_error("MK 5.0 IRQ: verified ROM required");
}
void Mk5IrqController::validate_epoch(uint32_t quanta){
    // This first timing contract covers the non-interlaced 34010 master mode.
    if((io_[8]&0x6000)!=0x6000 || io_[3]==0 || io_[7]==0 || io_[7]>4095 || io_[5]>io_[6] || io_[6]>io_[7]+1 || next_scanline_>io_[7])
        throw std::runtime_error("MK 5.0 IRQ: unsupported raster configuration");
    line_quanta_=uint64_t(io_[3]+1)*25;
    if(!quanta || quanta>line_quanta_)
        throw std::runtime_error("MK 5.0 IRQ: explicit raster phase required");
    next_edge_=quanta;
}
void Mk5IrqController::Start(uint16_t pending,uint16_t next,uint32_t quanta){
    if(started_)throw std::runtime_error("MK 5.0 IRQ: raster epoch already started");
    if((requested_&0x0fffffffu)!=0x0fffffffu)throw std::runtime_error("MK 5.0 IRQ: missing prefix IO request");
    if(cpu_.status&ie)throw std::runtime_error("MK 5.0 IRQ: epoch must start with interrupts disabled");
    // DPYADR and VCOUNT were not executed by the prefix. They, pending and
    // phase belong to the declared host epoch rather than physical history.
    std::array<uint16_t,32> io{};for(unsigned i=0;i<28;++i)io[i]=io_[i];
    io[18]=pending;io[30]=io[9];io[29]=next?uint16_t(next-1):io[7];
    io_=io;next_scanline_=next;elapsed_=0;started_=true;guard();aligned(cpu_.next_original_pc);validate_epoch(quanta);
}
void Mk5IrqController::advance(uint64_t cycles){
    cpu_.reference_cycles+=cycles;
    if(!started_)return;
    elapsed_+=cycles*16;
    while(next_edge_<=elapsed_){
        uint16_t v=next_scanline_;io_[29]=v;
        bool match=(io_[8]&0x8000) && v==io_[10];if(match)io_[18]|=di;
        if(v==io_[6])io_[30]=io_[9];
        if(scanline_observer_)scanline_observer_({next_edge_,v,io_[30],match},io_);
        if(v>=io_[5] && v<io_[6]){uint16_t a=io_[30];io_[30]=(a&3)?uint16_t((a&0xfffc)|((a-1)&3)):uint16_t(((a&0xfffc)-(io_[8]&0x3fc))|(io_[9]&3));}
        scanlines_.push_back({next_edge_,v,io_[30],match});
        next_scanline_=v==io_[7]?0:uint16_t(v+1);next_edge_+=line_quanta_;
    }
}
void Mk5IrqController::SetScanlineObserver(std::function<void(const Mk5ScanlineEvent&,const std::array<uint16_t,32>&)> observer){
    if(scanline_observer_ || !observer)throw std::runtime_error("MK5 raster observer already bound or empty");
    scanline_observer_=std::move(observer);
}
void Mk5IrqController::AdvanceCycles(uint64_t cycles){guard_advance(cycles);advance(cycles);}
uint16_t Mk5IrqController::SampleHcount()const{
    if(!started_)throw std::runtime_error("MK 5.0 IRQ: HCOUNT before the raster epoch");
    // Pinned screen clock = 2*pixel clock, width = 2*(HTOTAL+1).
    // io_register_r adds HEBLNK and wraps strictly above HTOTAL+1.
    uint64_t phase=line_quanta_-(next_edge_-elapsed_);
    uint32_t total=uint32_t(io_[3])+1;
    uint32_t value=uint32_t(phase/25)+io_[1];
    if(value>total)value-=total;
    return uint16_t(value);
}
bool Mk5IrqController::CanRunIrqFree(uint64_t cycles)const{
    guard_advance(cycles);
    if(!started_)return !(cpu_.status&ie);
    if(io_[16]&0x8100)return false;
    if(!(cpu_.status&ie))return true;
    if(io_[17]&io_[18])return false;
    if(!(io_[8]&0x8000) || !(io_[17]&di) || io_[10]>io_[7])return true;
    uint64_t lines=(uint64_t(io_[10])+io_[7]+1-next_scanline_)%(io_[7]+1);
    uint64_t due=next_edge_+lines*line_quanta_;
    return cycles*16<due-elapsed_;
}
void Mk5IrqController::AdoptBlockCycles(uint64_t cycles){
    guard_advance(cycles);uint64_t charged=cpu_.reference_cycles;
    if(cycles>charged)throw std::runtime_error("MK 5.0 IRQ: uncharged block cycles");
    advance(cycles);cpu_.reference_cycles=charged;
}
bool Mk5IrqController::CheckBoundary(uint32_t pc){
    guard();aligned(pc);aligned(cpu_.next_original_pc);
    if(!started_){if(cpu_.status&ie)throw std::runtime_error("MK 5.0 IRQ: interrupts enabled before the raster epoch");return false;}
    // execute_run does not execute or take interrupts while HLT is asserted.
    if(io_[16]&0x8000)return false;
    bool nmi=(io_[16]&0x100)!=0;uint16_t mask=0;uint32_t vector=0;int line=-1;
    if(nmi)vector=0xfffffee0;
    else if(cpu_.status&ie){
        uint16_t pending=io_[17]&io_[18];
        if(pending&hi){mask=hi;vector=0xfffffec0;}
        else if(pending&di){mask=di;vector=0xfffffea0;}
        else if(pending&wv){mask=wv;vector=0xfffffe80;}
        else if(pending&int1){mask=int1;vector=0xffffffc0;line=0;}
        else if(pending&int2){mask=int2;vector=0xffffffa0;line=1;}
    }
    if(!vector)return false;
    bool stack=!nmi || !(io_[16]&0x200);if(stack)guard_frame(true);guard_advance(16);
    size_t offset=(vector-0xff800000)/8;uint32_t target=0;
    for(unsigned i=0;i<4;++i)target|=uint32_t(program_.bytes.at(offset+i))<<(8*i);
    uint32_t ret=cpu_.next_original_pc,st=cpu_.status;
    if(nmi)io_[16]&=~uint16_t(0x100);
    if(stack){push(pc,ret);push(pc,st);}
    cpu_.status=0x10;cpu_.next_original_pc=target;
    entries_.push_back({pc,ret,st,vector,target,mask,line,stack,elapsed_});advance(16);return true;
}
bool Mk5IrqController::Eint(uint32_t pc,uint32_t next){
    if(!started_)throw std::runtime_error("MK 5.0 IRQ: EINT before the raster epoch");
    guard_advance(19);aligned(pc);aligned(next);if(cpu_.next_original_pc!=pc)throw std::runtime_error("MK 5.0 IRQ: EINT frontier mismatch");
    // Preflight the possible frame before updating IE/PC.
    if((io_[16]&0x100)?!(io_[16]&0x200):((io_[17]&io_[18])!=0))guard_frame(true);
    cpu_.next_original_pc=next;cpu_.status|=ie;bool taken=CheckBoundary(pc);advance(3);return taken;
}
void Mk5IrqController::Dint(uint32_t pc,uint32_t next){
    guard_advance(3);aligned(pc);aligned(next);if(cpu_.next_original_pc!=pc)throw std::runtime_error("MK 5.0 IRQ: DINT frontier mismatch");
    cpu_.status&=~ie;cpu_.next_original_pc=next;advance(3);
}
bool Mk5IrqController::SetStatus(uint32_t pc,uint32_t status){
    guard();aligned(pc);
    if((io_[16]&0x100)?!(io_[16]&0x200):((status&ie) && (io_[17]&io_[18])))guard_frame(true);
    guard_advance(16);cpu_.status=status;return CheckBoundary(pc);
}
bool Mk5IrqController::Reti(uint32_t pc){
    guard_frame(false);guard_advance(27);aligned(pc);
    uint32_t st=pop(),ret=pop()&0xfffffff0;cpu_.next_original_pc=ret;cpu_.status=st;
    bool taken=CheckBoundary(pc);advance(11);return taken;
}
bool Mk5IrqController::PopStatus(uint32_t pc,uint32_t next){
    guard();guard_advance(24);aligned(pc);aligned(next);
    if(cpu_.a[15]>0x013fffe0)throw std::runtime_error("MK 5.0 IRQ: POPST outside guest RAM");
    if(cpu_.next_original_pc!=pc)throw std::runtime_error("MK 5.0 IRQ: POPST frontier mismatch");
    // One POP followed by possible two PUSHes needs SP>=RAM+32.
    if(cpu_.a[15]<0x01000020)throw std::runtime_error("MK 5.0 IRQ: POPST reentry frame outside RAM");
    cpu_.status=pop();cpu_.next_original_pc=next;bool taken=CheckBoundary(pc);advance(8);return taken;
}
bool Mk5IrqController::WriteEnable(uint32_t pc,uint16_t value){
    guard();aligned(pc);guard_advance(16);
    if((io_[16]&0x100)?!(io_[16]&0x200):((cpu_.status&ie) && (value&io_[18])))guard_frame(true);
    io_[17]=value;return CheckBoundary(pc);
}
bool Mk5IrqController::WriteIo16(uint32_t pc,uint32_t address,uint16_t value){
    guard();aligned(pc);
    if(address<0xc0000000 || address>0xc00001f0 || (address&15))throw std::runtime_error("MK 5.0 IRQ: invalid IO word address");
    unsigned index=(address-0xc0000000)/16;
    if(!started_){io_[index]=value;requested_|=1u<<index;cpu_.writes.push_back({pc,address,value});return false;}
    if(index!=8 && index!=9 && index!=10 && index!=11 && index!=17 && index!=18 && index!=20 && index!=30)throw std::runtime_error("MK 5.0 IRQ: unsupported IO mutation");
    if(index==8 && (value&0x6000)!=0x6000)throw std::runtime_error("MK 5.0 IRQ: unsupported raster mode change");
    bool taken=false;
    if(index==17)taken=WriteEnable(pc,value);
    else if(index==18)WritePending(value);
    else io_[index]=value;
    cpu_.writes.push_back({pc,address,value});return taken;
}
void Mk5IrqController::WritePending(uint16_t value){guard();io_[18]&=uint16_t(value|~uint16_t(wv|di));}
void Mk5IrqController::SetExternalLine(unsigned line,bool asserted){
    guard();
    if(!started_)return; // INTPEND is declared by Start().
    if(line>1)throw std::runtime_error("MK 5.0 IRQ: invalid external line");
    uint16_t bit=line?int2:int1;
    if(asserted)io_[18]|=bit;else io_[18]&=~bit;
}
void Mk5IrqController::LatchInternal(uint16_t mask){
    guard();if(mask&~uint16_t(hi|di|wv))throw std::runtime_error("MK 5.0 IRQ: invalid internal source");io_[18]|=mask;
}
