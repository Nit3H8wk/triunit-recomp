
#include "mk5_audio.hpp"
#include "mk5_audio_link.hpp"
#include "mk5_task_body.hpp"
#include "mk5_scanout.hpp"
#include "mk5_live_video.hpp"
#include <fstream>
#include <iostream>
#include <map>

const std::vector<uint32_t>& DiagnosticRawRaster(const Mk5Scanout&);
struct Evidence{
 std::vector<std::string> pcm_chunks;
 uint64_t pcm_samples=0,pit_bottom_frames=0;
 struct Scene {uint64_t frames=0,with_layers=0,first=0,last=0;};
 std::map<std::array<unsigned,3>,Scene> scenes;

 std::array<uint32_t,16> a{};std::array<uint32_t,15> b{};
 uint32_t pc=0,status=0;uint64_t cycles=0,quanta=0,di_count=0;
 std::array<uint16_t,32> io{};std::array<uint16_t,1024> shift{};
 Mk5MemoryBuffers m;std::vector<uint16_t> cmos;
 std::vector<int16_t> pcm;std::vector<uint32_t> rasters;
 std::map<uint16_t,uint64_t> fighter_modes;
 uint64_t layers=0,covered=0,projected=0;
};
static void require(bool value,const char* issue){if(!value)throw std::runtime_error(issue);}
static std::vector<uint8_t> bytes(const std::filesystem::path& p){
 std::ifstream f(p,std::ios::binary);require(bool(f),"cannot open chip ROM");
 return {std::istreambuf_iterator<char>(f),{}};
}
static Evidence run(const std::filesystem::path& root,const std::filesystem::path& tape,
                    unsigned end,bool remastered,const std::filesystem::path& seed){
 using namespace mk5presentation;
 std::ifstream timeline(tape);require(bool(timeline),"missing legal tape");
 std::string header;std::getline(timeline,header);
 std::vector<uint32_t> inputs(end+1);unsigned frame,duration;uint32_t mask;
 while(timeline>>frame>>duration>>mask)
  for(unsigned n=0;n<duration && frame+n<inputs.size();++n)inputs[frame+n]=mask;
 require(timeline.eof(),"invalid legal tape");
 auto program=LoadMk5Program(root/"roms");
 auto rom=root/"roms/mk1";
 mk5audio::WilliamsAudio audio(bytes(rom/"mks-u3.rom"),bytes(rom/"mks-u12.rom"),bytes(rom/"mks-u13.rom"));
 mk5audio::GameAudioScope scope(audio);
 const auto cmos=LoadMk5CmosSnapshot(seed);
 Evidence evidence;
 auto& m=evidence.m;
 Mk5BoardState f;f.cmos=cmos;
 auto& s=f.check.cpu;
 BootDiState di;
 Mk5IrqController irq(program,s,m);
 const BootDiInputs released{0xffffffff,0xfeffffff};
 Mk5TaskBodyRunner runner(program,f,m,irq,di);
 Mk5BootInputs power_on;power_on.ports=released;power_on.pending=0x400;power_on.next_line=1;power_on.quanta_to_next=6325;
 require(runner.Boot(power_on).stop==TaskBodyStop::TaskEntry,"power-on did not reach the first task");
 TaskBodyInputs in;in.dsw=0xfeff;in.main_dsw=0xfeff;in.sound_status=0x80;in.quiet_di=released;
 require(runner.Run(in).stop==TaskBodyStop::MainLoop,"runner did not enter the main loop");
 auto graphics=LoadMk5GlyphBank(root/"roms");
 runner.AttachVideo(graphics,remastered);
 std::cerr<<"video attached"<<std::endl;
 Mk5Scanout screen(irq,m,remastered?&runner.Video():nullptr);
 in.active_di=released;
 in.stop_after_decompression=true;
 TaskBodyResult result;
 for(unsigned i=0;i<100;++i){
  result=runner.ContinueMain(in,64);
  if(result.stop!=TaskBodyStop::Budget && result.stop!=TaskBodyStop::DiLimit)break;
 }
 require(result.stop==TaskBodyStop::DecompressorComplete,"original decompression did not complete");
 in.stop_after_decompression=false;in.instruction_budget=10000;
 
 const size_t stride=end==4000?125:std::max(23u,(end+127)/128);
 const bool exact_pcm=end<=12000;
 const auto flush_pcm=[&]{
  const auto& pcm=audio.Pcm();
  const auto* bytes=reinterpret_cast<const uint8_t*>(pcm.data());
  evidence.pcm_samples+=pcm.size();
  if(exact_pcm)evidence.pcm.insert(evidence.pcm.end(),pcm.begin(),pcm.end());
  else if(!pcm.empty())evidence.pcm_chunks.push_back(Sha256({bytes,bytes+pcm.size()*sizeof(int16_t)}));
  audio.DiscardDiagnostics();
 };
 const size_t area=size_t(screen.width())*screen.height();
 for(unsigned n=0;screen.frames()<end && n<end*250;++n){
  const auto before=screen.frames();
  in.active_di=BootDiInputs{0xffffffffu&~inputs.at(before),0xfeffffff};
  result=runner.ContinueMain(in,64);
  if(result.stop!=TaskBodyStop::Budget && result.stop!=TaskBodyStop::DiLimit){
   std::cerr<<"first frontier "<<std::hex<<result.pc<<std::dec<<" frame "<<screen.frames()<<'\n';
   throw std::runtime_error("MK1 replay left the native route");
  }
  if(screen.frames()==before)continue;
  
  if(screen.frames()%1000==0)std::cerr<<"frame "<<screen.frames()<<std::endl;
  if(screen.frames()%250==0)flush_pcm();
  runner.CompactDiagnostics();
  require(screen.frames()==before+1,"observer missed a raster frame");
  const auto& pixels=screen.pixels();
  const auto& fighter=screen.fighter_frame();
  const auto mode=m.ram[(0x01051190-0x01000000)/16];

  if(mode==2 || mode==3 || mode==4 || mode==5 || mode==6 || mode==9 || mode==11 || mode==13){
   const auto word=[&](unsigned address){return m.ram[(address-0x01000000)/16];};
   if(word(0x01051820)==3 && int16_t(word(0x0104f660))>=752 && fighter.serial)
     ++evidence.pit_bottom_frames;
   const unsigned p1=mode==2 || mode==5 ? word(0x01051290) : 0;
   const unsigned p2=mode==2 || mode==5 ? word(0x01051570) : 0;
   auto& scene=evidence.scenes[{mode,p1,p2}];
   if(!scene.frames)scene.first=screen.frames();
   ++scene.frames;scene.last=screen.frames();
   if(fighter.serial)++scene.with_layers;
  }
  if(screen.frames()%stride==0 || screen.frames()==end){
   const auto& raw=DiagnosticRawRaster(screen);
   require(raw.size()==area,"diagnostic raw raster size differs");
   evidence.rasters.insert(evidence.rasters.end(),raw.begin(),raw.end());
  }
  if(!fighter.serial)continue;
  require(remastered && fighter.serial==screen.frames(),"mixed MK1 frame serial");
  ++evidence.fighter_modes[mode];evidence.layers+=fighter.layers.size();
  evidence.covered+=std::count(fighter.covered.begin(),fighter.covered.end(),uint8_t(1));
  if(screen.frames()%stride==0 || screen.frames()==end){
   auto projected=fighter.underlay;
   for(const auto& layer:fighter.layers)for(unsigned y=0;y<layer.height;++y)for(unsigned x=0;x<layer.width;++x){
    const auto pen=layer.pixels[y*layer.width+x];const int sx=layer.x+int(x);
    if(sx<0 || sx>=int(screen.width()))continue;
    const auto pos=(layer.y+y)*screen.width()+unsigned(sx);
    if((pen>>24) && layer.order>fighter.opaque_order[pos])projected[pos]=pen&0xffffff;
   }

   require(projected.size()==area,"native projection geometry differs");
   unsigned shown=0;
   for(size_t p=0;p<area;++p)if(projected[p]!=pixels[p] && shown++<12){
    std::cerr<<"PROJECTION "<<screen.frames()<<' '<<mode<<' '<<p%screen.width()<<' '<<p/screen.width()
             <<std::hex<<" game="<<pixels[p]<<" raw="<<DiagnosticRawRaster(screen)[p]<<" projected="<<projected[p]
             <<" underlay="<<fighter.underlay[p]<<std::dec<<" covered="<<unsigned(fighter.covered[p])
             <<" opaque="<<fighter.opaque_order[p]<<'\n';
   }
   require(!shown,"native projection of observed fighter layers differs");
   evidence.projected+=area;
  }
 }
 flush_pcm();
 require(screen.frames()==end,"legal tape endpoint not reached");
 evidence.a=s.a;evidence.b=s.b;evidence.pc=s.next_original_pc;evidence.status=s.status;
 evidence.cycles=s.reference_cycles;evidence.quanta=irq.elapsed_quanta();evidence.di_count=di.completed_handlers;
 evidence.io=irq.io();evidence.shift=di.shiftreg;evidence.cmos=f.cmos;
 return evidence;
}
int wmain(int argc,wchar_t** argv){
 try{
  require(argc==6,"root tape scratch end seed");
  const unsigned end=std::stoul(argv[4]);
  std::cerr<<"starting Original"<<std::endl;
  const auto original=run(argv[1],argv[2],end,false,argv[5]);
  std::cerr<<"starting Remaster"<<std::endl;
  const auto fighter=run(argv[1],argv[2],end,true,argv[5]);
  const bool state=original.a==fighter.a && original.b==fighter.b && original.pc==fighter.pc &&
   original.status==fighter.status && original.cycles==fighter.cycles && original.quanta==fighter.quanta &&
   original.di_count==fighter.di_count && original.io==fighter.io && original.shift==fighter.shift &&
   original.cmos==fighter.cmos && original.m.ram==fighter.m.ram && original.m.vram==fighter.m.vram &&
   original.m.palette==fighter.m.palette;
  
  const bool raster=original.rasters==fighter.rasters;
  const bool pcm=original.pcm_samples==fighter.pcm_samples && original.pcm==fighter.pcm && original.pcm_chunks==fighter.pcm_chunks;
  std::cout<<"{\"terminal_state_equal\":"<<(state?"true":"false")<<",\"raster_equal\":"<<(raster?"true":"false")
   <<",\"pcm_equal\":"<<(pcm?"true":"false")<<",\"raster_pixels\":"<<fighter.rasters.size()
   <<",\"pcm_samples\":"<<fighter.pcm_samples<<",\"native_projection_pixels\":"<<fighter.projected
   <<",\"terminal_cycles\":"<<fighter.cycles<<",\"layers\":"<<fighter.layers<<",\"covered\":"<<fighter.covered
   <<",\"modes\":{";
  bool comma=false;
  for(const auto& [mode,count]:fighter.fighter_modes){if(comma)std::cout<<',';comma=true;std::cout<<'\"'<<mode<<"\":"<<count;}
  
  std::cout<<"},\"pcm_compared_exactly\":"<<(fighter.pcm_chunks.empty()?"true":"false")
           <<",\"pcm_chunks_hashed\":"<<fighter.pcm_chunks.size()
           <<",\"pit_bottom_frames\":"<<fighter.pit_bottom_frames<<",\"scenes\":[";
  comma=false;
  for(const auto& [key,scene]:fighter.scenes){
   if(comma)std::cout<<',';
   comma=true;
   std::cout<<'['<<key[0]<<','<<key[1]<<','<<key[2]<<','<<scene.frames<<','
            <<scene.with_layers<<','<<scene.first<<','<<scene.last<<']';
  }
  std::cout<<"]}\n";
  return state&&raster&&pcm&&fighter.covered?0:1;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
