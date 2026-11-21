#define NOMINMAX
#include <windows.h>
#include "mk5_window.hpp"
#include "mk5_controls.hpp"
#include "mk5_audio_link.hpp"
#include "mk5_stage_bicubic.hpp"
#include "mk5_fighter_bicubic.hpp"
#include "mk5_crt.hpp"
#include "mk5_hdr.hpp"
#include <wincodec.h>
#include <wrl/client.h>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <stdexcept>
int main(int argc,char** argv){try{
 const std::string group=argc==2?argv[1]:"";
 if(group!="effects"&&group!="crt"&&group!="stage"&&group!="fighter"&&group!="hdr"&&group!="frame"&&group!="training"&&group!="wide")
  throw std::runtime_error("Choose the effects, crt, stage, fighter, hdr, frame, training or wide test group");
 mk5audio::detail::hooks.output_clock=true;
 SetEnvironmentVariableA("MK1_GRAPHICS_VALIDATE","1");SetEnvironmentVariableA("MK1_FULLSCREEN","0");SetEnvironmentVariableA("MK1_BEZEL","1");
 SetEnvironmentVariableA("MK1_FILTER","nearest");SetEnvironmentVariableA("MK1_COLOR","warm");SetEnvironmentVariableA("MK1_BRIGHTNESS","110");
 std::vector<uint32_t> image(400*254);for(unsigned y=0;y<254;++y)for(unsigned x=0;x<400;++x)
  image[y*400+x]=(((x/13+(y+x/5)/11)&1)?0x00c04080:0x00205090)+(x%7)*0x00020101;
 const auto original=image;
 if(group=="frame"){
  // The user's own frame: a PNG, opaque gray with a transparent 4:3 screen, written here with WIC.
  using Microsoft::WRL::ComPtr;
  const auto ok=[](HRESULT hr,const char* what){if(FAILED(hr))throw std::runtime_error(what);};
  ok(CoInitializeEx(nullptr,COINIT_MULTITHREADED),"COM");
  const auto path=std::filesystem::temp_directory_path()/("mk5-frame-"+std::to_string(GetCurrentProcessId())+".png");
  {
   ComPtr<IWICImagingFactory> wic;ok(CoCreateInstance(CLSID_WICImagingFactory,nullptr,CLSCTX_INPROC_SERVER,IID_PPV_ARGS(&wic)),"WIC");
   ComPtr<IWICStream> stream;ok(wic->CreateStream(&stream),"WIC stream");ok(stream->InitializeFromFilename(path.c_str(),GENERIC_WRITE),"frame file");
   ComPtr<IWICBitmapEncoder> encoder;ok(wic->CreateEncoder(GUID_ContainerFormatPng,nullptr,&encoder),"PNG encoder");ok(encoder->Initialize(stream.Get(),WICBitmapEncoderNoCache),"PNG init");
   ComPtr<IWICBitmapFrameEncode> frame;ok(encoder->CreateNewFrame(&frame,nullptr),"PNG frame");ok(frame->Initialize(nullptr),"PNG frame init");
   ok(frame->SetSize(160,90),"PNG size");WICPixelFormatGUID format=GUID_WICPixelFormat32bppBGRA;ok(frame->SetPixelFormat(&format),"PNG format");
   std::vector<uint32_t> art(160*90);
   for(unsigned y=0;y<90;++y)for(unsigned x=0;x<160;++x)art[y*160+x]=x>=40&&x<120&&y>=15&&y<75?0:0xff808080u-((x+y)%9)*0x10101;
   ok(frame->WritePixels(90,160*4,UINT(art.size()*4),reinterpret_cast<BYTE*>(art.data())),"PNG pixels");ok(frame->Commit(),"PNG commit");ok(encoder->Commit(),"PNG file");
  }
  SetEnvironmentVariableW(L"MK1_BEZEL_IMAGE",path.c_str());
  std::string report;
  {
   Mk5Window window;window.Present(image,400,254);const auto deadline=GetTickCount64()+5000;
   do{window.Pump();report=window.presentation_json();Sleep(5);}while(report.find("\"gpu_validation_frames\":1")==std::string::npos&&GetTickCount64()<deadline);
  }
  std::filesystem::remove(path);
  const auto number=[&](const char* key){const auto at=report.find(key);return at==std::string::npos?-1ll:std::stoll(report.substr(at+std::string(key).size()));};
  const auto w=number("\"viewport_width\":"),h=number("\"viewport_height\":");
  if(number("\"gpu_validation_frames\":")!=1||number("\"gpu_validation_mismatches\":")!=0||number("\"gpu_validation_bezel_pixels\":")<=0||w<390||w*3!=h*4)
   throw std::runtime_error("custom frame presentation differs: "+report);
  std::cout<<"PASS DX12 user frame PNG: transparent screen holds the 4:3 game ("<<w<<"x"<<h<<")\n";
  return 0;
 }
 if(group=="hdr"){
  // CPU reference: ST 2084 anchors, SDR white at paper white, full highlights put SDR white at the peak.
  const auto close=[](float a,float b){return std::fabs(a-b)<2e-4f;};
  if(!close(mk5hdr::pq(100),.508078f)||!close(mk5hdr::pq(1000),.751827f)||!close(mk5hdr::pq(10000),1)||mk5hdr::pq(0)>1e-6f)
   throw std::runtime_error("PQ curve differs from SMPTE ST 2084");
  const auto gray=[](float nits){const uint32_t c=uint32_t(std::lround(mk5hdr::pq(nits)*1023));return 3u<<30|c<<20|c<<10|c;};
  if(mk5hdr::encode(0xffffff,{203,1000,0})!=gray(203)||mk5hdr::encode(0xffffff,{203,1000,1})!=gray(1000)||mk5hdr::encode(0,{203,1000,1})!=3u<<30)
   throw std::runtime_error("HDR10 paper white or peak mapping differs");
  SetEnvironmentVariableA("MK1_HDR","force");SetEnvironmentVariableA("MK1_HDR_PAPER_WHITE","203");
  SetEnvironmentVariableA("MK1_HDR_PEAK","1000");SetEnvironmentVariableA("MK1_HDR_HIGHLIGHTS","60");
  Mk5Window window;window.Present(image,400,254);
  const auto deadline=GetTickCount64()+10000;std::string report;
  do{window.Pump();report=window.presentation_json();Sleep(5);}
  while(report.find("\"hdr_validation_frames\":1")==std::string::npos&&GetTickCount64()<deadline);
  for(const auto* field:{"\"hdr\":\"hdr10\"","\"hdr_validation_frames\":1","\"hdr_validation_mismatches\":0",
                         "\"gpu_validation_mismatches\":0","\"hdr_paper_nits\":203","\"hdr_peak_nits\":1000","\"hdr_highlights\":0.6"})
   if(report.find(field)==std::string::npos)throw std::runtime_error("HDR10 presentation differs: "+report);
  std::cout<<"PASS DX12 HDR10 encode matches the CPU reference\n";
  return 0;
 }
 if(group=="wide"){
  // A widescreen MK2 frame: 512 columns at 4:3 x 512/400 (128:75), no TV frame even with MK1_BEZEL=1, aspect-correct
  // scaling, the stage and a fighter layer past the 400th column composed and read back equal to the CPU reference.
  using namespace mk5presentation;
  SetEnvironmentVariableA("MK1_SCANLINES","0");SetEnvironmentVariableA("MK1_COLOR","original");SetEnvironmentVariableA("MK1_BRIGHTNESS","100");
  SetEnvironmentVariableA("MK1_CRT_PRESET","off");SetEnvironmentVariableA("MK1_SCALEFX","0");SetEnvironmentVariableA("MK1_CAS","0");
  SetEnvironmentVariableA("MK1_BILATERAL","0");SetEnvironmentVariableA("MK1_SMAA","0");SetEnvironmentVariableA("MK1_SCALE_MODE","5");
  std::vector<uint32_t> wide(512*254);
  for(unsigned y=0;y<254;++y)for(unsigned x=0;x<512;++x)wide[y*512+x]=(((x/13+(y+x/5)/11)&1)?0x00c04080:0x00205090)+(x%7)*0x00020101;
  FighterFrame frame;frame.serial=1;frame.underlay=wide;frame.backdrop=wide;
  frame.covered.resize(wide.size());frame.opaque_order.resize(wide.size());
  for(unsigned y=60;y<200;++y)for(unsigned x=8;x<504;++x)frame.backdrop[y*512+x]|=mk5stage::scenery;
  frame.layers.push_back({470,170,3,2,true,{0xff130b02,0xff104fbb,0,0,0xfffefefe,0xff9ea104},2});
  for(unsigned y=0;y<2;++y)for(unsigned x=0;x<3;++x){
   const auto index=(170+y)*512+470+x;const auto pen=frame.layers.front().pixels[y*3+x];
   if(pen){frame.covered[index]=1;wide[index]=pen&0xffffff;}
  }
  Mk5Window window(false,128,75);window.Present(wide,512,254,{},frame);
  const std::array<const char*,8> fields{"\"bicubic_fighter_validation_frames\":1","\"bicubic_stage_frames\":1","\"gpu_validation_frames\":1",
                         "\"gpu_validation_mismatches\":0","\"bezel\":false","\"viewport_width\":867","\"viewport_height\":508",
                         "\"physical_aspect\":\"wide\""};
  const auto complete=[&](const std::string& report){
   return std::all_of(fields.begin(),fields.end(),[&](const char* field){return report.find(field)!=std::string::npos;});};
  const auto deadline=GetTickCount64()+5000;std::string report;
  do{window.Pump();report=window.presentation_json();Sleep(5);}while(!complete(report)&&GetTickCount64()<deadline);
  if(!complete(report))throw std::runtime_error("Widescreen presentation differs: "+report);
  std::cout<<"PASS widescreen 512-column frame at 128:75\n";return 0;
 }
 if(group=="fighter"){
  using namespace mk5presentation;
  const auto fetch=[](int,int,unsigned){return 0.f;};
  const mk5crt::Settings phosphor{};
  std::vector<std::array<float,3>> beam;
  const auto sample_phase=[](float,float coarse,float fine,std::array<float,3>& rgb){
   if(coarse!=.25f || fine!=.1875f)
    throw std::runtime_error("CRT discarded the fighter's vertical subpixel");
   rgb={.2f,.2f,.2f};
   return true;
  };
  mk5crt::phosphor_reference_row(phosphor,0,1,16,8,4,2,fetch,beam,nullptr,sample_phase);
  SetEnvironmentVariableA("MK1_BEZEL","0");SetEnvironmentVariableA("MK1_SCANLINES","0");
  SetEnvironmentVariableA("MK1_COLOR","original");SetEnvironmentVariableA("MK1_BRIGHTNESS","100");
  SetEnvironmentVariableA("MK1_CRT_PRESET","off");SetEnvironmentVariableA("MK1_SCALEFX","0");
  SetEnvironmentVariableA("MK1_CAS","0");SetEnvironmentVariableA("MK1_BILATERAL","0");
  SetEnvironmentVariableA("MK1_SMAA","0");
  SetEnvironmentVariableA("MK1_SCALE_MODE","4");
  FighterFrame frame;
  frame.serial=1;frame.underlay=image;
  frame.covered.resize(image.size());frame.opaque_order.resize(image.size());
  frame.layers.push_back({185,170,3,2,true,{0xff130b02,0xff104fbb,0,0,0xfffefefe,0xff9ea104},2});
  for(unsigned y=0;y<2;++y)for(unsigned x=0;x<3;++x){
   const auto index=(170+y)*400+185+x;
   const auto pen=frame.layers.front().pixels[y*3+x];
   if(pen){frame.covered[index]=1;image[index]=pen&0xffffff;}
  }
  const auto wait_for=[](Mk5Window& window,const char* metric){
   const auto deadline=GetTickCount64()+5000;
   std::string report;
   do{
    window.Pump();report=window.presentation_json();
    if(report.find(metric)!=std::string::npos &&
       report.find("\"gpu_validation_mismatches\":0")!=std::string::npos)return report;
    Sleep(5);
   }while(GetTickCount64()<deadline);
   throw std::runtime_error("Fighter DX12 validation incomplete: "+report);
  };
  {
   Mk5Window window;
   HWND hwnd=nullptr;
   EnumWindows([](HWND h,LPARAM output)->BOOL{
    DWORD pid=0;GetWindowThreadProcessId(h,&pid);wchar_t cls[64]{};GetClassNameW(h,cls,64);
    if(pid!=GetCurrentProcessId()||std::wstring(cls)!=L"Mk5TemporalScanout")return TRUE;
    *reinterpret_cast<HWND*>(output)=h;return FALSE;
   },reinterpret_cast<LPARAM>(&hwnd));
   RECT client{},outer{};
   if(!hwnd||!GetClientRect(hwnd,&client)||!GetWindowRect(hwnd,&outer)||
      !SetWindowPos(hwnd,nullptr,0,0,1600+(outer.right-outer.left)-client.right,
                    1016+(outer.bottom-outer.top)-client.bottom,SWP_NOMOVE|SWP_NOZORDER|SWP_NOACTIVATE))
    throw std::runtime_error("Fighter 4x contract window resize failed");
   window.Present(image,400,254,{},frame);
   const auto report=wait_for(window,"\"bicubic_fighter_frames\":1");
   for(const auto* field:{"\"bicubic_stage_frames\":0","\"bicubic_stage_validation_frames\":0",
                         "\"bicubic_fighter_validation_frames\":1","\"gpu_validation_frames\":1",
                         "\"gpu_validation_tolerance\":0",
                         "\"viewport_width\":1600","\"viewport_height\":1016"})
    if(report.find(field)==std::string::npos)throw std::runtime_error("Fighter DX12 4x readback differs: "+report);
   window.Present(image,400,254);
   wait_for(window,"\"gpu_validation_frames\":2");
   auto stage=frame.underlay;
   stage[0]|=mk5stage::scenery;
   window.Present(image,400,254,stage);
   const auto stage_report=wait_for(window,"\"bicubic_stage_validation_frames\":1");
   if(stage_report.find("\"gpu_validation_frames\":3")==std::string::npos)
    throw std::runtime_error("Fighter validation replaced the scenery control: "+stage_report);
   if(!ShowWindowAsync(hwnd,SW_MINIMIZE))throw std::runtime_error("Fighter window minimize failed");
   const auto minimized_deadline=GetTickCount64()+5000;
   while(!IsIconic(hwnd) && GetTickCount64()<minimized_deadline){window.Pump();Sleep(5);}
   if(!IsIconic(hwnd))throw std::runtime_error("Fighter window did not minimize");
   window.Present(original,400,254);
   frame.serial=2;
   window.Present(image,400,254,{},frame);
   if(!ShowWindowAsync(hwnd,SW_RESTORE))throw std::runtime_error("Fighter window restore failed");
   const auto restored=wait_for(window,"\"bicubic_fighter_frames\":2");
   if(restored.find("\"submitted_frames\":5")==std::string::npos ||
      restored.find("\"coalesced_host_frames\":1")==std::string::npos ||
      restored.find("\"viewport_width\":1600")==std::string::npos || IsIconic(hwnd))
    throw std::runtime_error("Fighter window lost the latest frame or geometry after restoring: "+restored);
  }
  SetEnvironmentVariableA("MK1_FULLSCREEN","1");SetEnvironmentVariableA("MK1_SCALE_MODE","5");
  SetEnvironmentVariableA("MK1_CRT_PRESET","phosphor");
  SetEnvironmentVariableA("MK1_SCALEFX","37");SetEnvironmentVariableA("MK1_CAS","28");
  SetEnvironmentVariableA("MK1_BILATERAL","35");SetEnvironmentVariableA("MK1_SMAA","1");
  frame.backdrop=frame.underlay;
  for(unsigned y=80;y<190;++y)for(unsigned x=80;x<250;++x)frame.backdrop[y*400+x]|=mk5stage::scenery;
  {
   Mk5Window window;
   window.Present(image,400,254,{},frame);
   const auto report=wait_for(window,"\"bicubic_fighter_frames\":1");
   if(report.find("\"bicubic_stage_frames\":1")==std::string::npos ||
      report.find("\"fullscreen_start\":true")==std::string::npos ||
      report.find("\"physical_aspect\":\"4:3\"")==std::string::npos)
    throw std::runtime_error("Fighter and stage were not composed together: "+report);
  }
  std::cout<<"PASS DX12 fighter at native 4x, layer removal and effects with scenery\n";
  return 0;
 }
 if(group=="stage"){
  SetEnvironmentVariableA("MK1_BEZEL","0");SetEnvironmentVariableA("MK1_SCANLINES","0");
  SetEnvironmentVariableA("MK1_COLOR","original");SetEnvironmentVariableA("MK1_BRIGHTNESS","100");
  SetEnvironmentVariableA("MK1_CRT_PRESET","off");SetEnvironmentVariableA("MK1_SCALEFX","37");
  std::vector<uint32_t> backdrop=image;
  for(size_t i=0;i<image.size();++i){
   if(i%61<15)image[i]=0xf035a5;
   else backdrop[i]|=mk5stage::scenery;
  }
  const auto wait_for=[&](Mk5Window& window,const char* metric){
   const auto deadline=GetTickCount64()+5000;
   while(GetTickCount64()<deadline){
    window.Pump();
    const auto report=window.presentation_json();
    if(report.find(metric)!=std::string::npos){
     if(report.find("\"gpu_validation_mismatches\":0")==std::string::npos)
      throw std::runtime_error("stage readback mismatch: "+report);
     return;
    }
    Sleep(5);
   }
   throw std::runtime_error("stage presentation timed out: "+window.presentation_json());
  };
  {
   Mk5Window window;
   window.Present(image,400,254,backdrop);
   wait_for(window,"\"bicubic_stage_frames\":1");
   window.Present(image,400,254);
   wait_for(window,"\"gpu_validation_frames\":2");
   window.Present(image,400,254,backdrop);
   wait_for(window,"\"bicubic_stage_frames\":2");
  }
  SetEnvironmentVariableA("MK1_CRT_PRESET","phosphor");SetEnvironmentVariableA("MK1_SCALEFX","50");
  SetEnvironmentVariableA("MK1_BEZEL","1");
  Mk5Window window;
  window.Present(image,400,254,backdrop);
  wait_for(window,"\"bicubic_stage_frames\":1");
  std::cout<<"PASS DX12 bicubic stage, foreground and ScaleFX transition\n";
  return 0;
 }
 const auto verify=[&](const char* preset,const char* amount,bool bezel,bool wide=false,
                       const char* filter="nearest",const char* scale="0",const char* cas="0",
                       const char* bilateral="0",const char* smaa="0",
                       const std::vector<uint32_t>* raster=nullptr){
  SetEnvironmentVariableA("MK1_BEZEL",bezel?"1":"0");
  SetEnvironmentVariableA("MK1_FILTER",filter);SetEnvironmentVariableA("MK1_SCALE_MODE",scale);
  SetEnvironmentVariableA("MK1_CAS",cas);SetEnvironmentVariableA("MK1_BILATERAL",bilateral);
  SetEnvironmentVariableA("MK1_SMAA",smaa);
  SetEnvironmentVariableA("MK1_CRT_PRESET",preset);SetEnvironmentVariableA("MK1_SCALEFX",amount);
  Mk5Window window;
  if(wide){
   HWND hwnd=nullptr;
   EnumWindows([](HWND h,LPARAM result)->BOOL{
    DWORD pid=0;GetWindowThreadProcessId(h,&pid);wchar_t name[64]{};GetClassNameW(h,name,64);
    if(pid!=GetCurrentProcessId()||std::wstring(name)!=L"Mk5TemporalScanout")return TRUE;
    *reinterpret_cast<HWND*>(result)=h;return FALSE;
   },reinterpret_cast<LPARAM>(&hwnd));
   RECT client{},outer{};
   if(!hwnd||!GetClientRect(hwnd,&client)||!GetWindowRect(hwnd,&outer)||
      !SetWindowPos(hwnd,nullptr,0,0,1280+(outer.right-outer.left)-client.right,
                    720+(outer.bottom-outer.top)-client.bottom,SWP_NOMOVE|SWP_NOZORDER|SWP_NOACTIVATE))
    throw std::runtime_error("16:9 contract window resize failed");
   if(!GetClientRect(hwnd,&client)||client.right!=1280||client.bottom!=720)
    throw std::runtime_error("16:9 contract client dimensions differ");
  }
  window.Present(raster?*raster:image,400,254);const auto until=GetTickCount64()+5000;std::string report;
  while(GetTickCount64()<until){window.Pump();report=window.presentation_json();if(report.find("\"gpu_validation_frames\":1")!=std::string::npos)break;Sleep(5);}
  if(report.find("\"gpu_validation_frames\":1")==std::string::npos||report.find("\"gpu_validation_mismatches\":0")==std::string::npos)throw std::runtime_error("ScaleFX window validation incomplete: "+report);
  const std::string bezel_pixels="\"gpu_validation_bezel_pixels\":";
  const auto bezel_at=report.find(bezel_pixels);
  if(bezel_at==std::string::npos||(std::stoull(report.substr(bezel_at+bezel_pixels.size()))>0)!=bezel)throw std::runtime_error("Neon bezel pixels were not verified");
  if(report.find(std::string("\"scalefx_amount\":")+amount)==std::string::npos)throw std::runtime_error("ScaleFX amount did not reach presenter");
  if(wide&&bezel&&std::string(scale)=="0"&&report.find("\"crt_integer_vertical\":false")==std::string::npos)throw std::runtime_error("CRT must fit the 16:9 bezel aperture");
  if(report.find(std::string("\"filter\":\"")+filter+"\"")==std::string::npos)throw std::runtime_error("Sampling filter did not reach presenter: "+report);
  if(report.find(std::string("\"cas_amount\":")+cas+",\"bilateral_amount\":"+bilateral+",\"smaa\":"+(std::string(smaa)=="1"?"true":"false"))==std::string::npos)
   throw std::runtime_error("Video effects did not reach presenter: "+report);
  if(image!=original)throw std::runtime_error("guest raster modified");
  std::cout<<"PASS DX12 "<<preset<<" ScaleFX "<<amount<<" "<<filter<<" scale "<<scale<<" CAS "<<cas<<" bilateral "<<bilateral<<" SMAA "<<smaa<<" bezel "<<(bezel?"on":"off")<<std::endl;
  return report;
 };
 if(group=="training"){
  // Training mode (F8): the overlay (input history and boxes) blended over the game area, checked against the CPU
  // reference of the overlay pass, with and without the television frame.
  mk5controls::Config controls;controls.training=1;SetEnvironmentVariableA("MK1_CONTROLS",mk5controls::format(controls).c_str());
  mk5training::held[0]=1u<<mk5controls::Right|1u<<mk5controls::HighPunch;mk5training::held[1]=1u<<mk5controls::Down;
  SetEnvironmentVariableA("MK1_SCANLINES","0");
  for(const bool bezel:{false,true}){
   SetEnvironmentVariableA("MK1_BEZEL",bezel?"1":"0");SetEnvironmentVariableA("MK1_CRT_PRESET","off");SetEnvironmentVariableA("MK1_SCALEFX","0");
   Mk5Window window;window.Present(image,400,254,{},{},{{100,60,80,120,mk5training::Body},{170,90,40,20,mk5training::Strike}});
   std::string report;const auto until=GetTickCount64()+5000;
   while(GetTickCount64()<until){window.Pump();report=window.presentation_json();if(report.find("\"gpu_validation_frames\":1")!=std::string::npos)break;Sleep(5);}
   if(report.find("\"gpu_validation_frames\":1")==std::string::npos||report.find("\"gpu_validation_mismatches\":0")==std::string::npos)
    throw std::runtime_error("Training overlay validation failed: "+report);
  }
  std::cout<<"PASS training overlay window\n";return 0;
 }
 if(group=="effects"){
  const auto verify_scale=[&](const char* mode,unsigned width,unsigned height){
   const auto report=verify("off","0",false,true,"nearest",mode);
   const auto expected="\"viewport_width\":"+std::to_string(width)+",\"viewport_height\":"+std::to_string(height);
   if(report.find(expected)==std::string::npos)throw std::runtime_error("Scaling mode produced unexpected geometry: "+report);
   return report;
  };
  const auto hash=[](const std::string& report){
   const std::string key="\"gpu_validation_image_hash\":";
   const auto pos=report.find(key);
   if(pos==std::string::npos)throw std::runtime_error("Readback hash missing");
   return std::stoull(report.substr(pos+key.size()));
  };
  // Reproduce the dark transitions that amplify prefilter quantization in Phosphor.
  std::vector<uint32_t> rounding_raster(400*254);
  for(unsigned y=0;y<254;++y)for(unsigned x=0;x<400;++x){
   auto& pixel=rounding_raster[y*400+x];
   if(y<35)pixel=((x/4+y/4)&1)?0x00303030:0x00b8b8b8;
   else if(x<100)pixel=((x+2*y)%29<14?0x006e5067:0x005e4863)+(x%11)*0x00010101;
   else if(x<250)pixel=image[y*400+x];
   else pixel=((x+y/3)%31<5)?0x00f0e0d0:0x00182620;
  }
  SetEnvironmentVariableA("MK1_SCANLINES","0");SetEnvironmentVariableA("MK1_COLOR","original");SetEnvironmentVariableA("MK1_BRIGHTNESS","100");
  verify("phosphor","0",false,true,"nearest","0","50","50","1",&rounding_raster);
  SetEnvironmentVariableA("MK1_BRIGHTNESS","90");
  const auto color_report=verify("off","0",false,true,"nearest","0","0","0","0",&rounding_raster);
  if(color_report.find("\"gpu_validation_tolerance\":1,")==std::string::npos)
   throw std::runtime_error("Readback metrics must report the rounded error ceiling for color conversion");
  SetEnvironmentVariableA("MK1_SCANLINES","0.5");SetEnvironmentVariableA("MK1_COLOR","warm");SetEnvironmentVariableA("MK1_BRIGHTNESS","110");
  const auto nearest=hash(verify_scale("0",960,720));
  const auto linear=hash(verify("off","0",false,true,"linear"));
  const auto sharp=hash(verify("off","0",false,true,"sharp-bilinear"));
  const auto cubic=hash(verify("off","0",false,true,"bicubic"));
  if(nearest==linear||nearest==sharp||nearest==cubic||sharp==linear||sharp==cubic||linear==cubic)
   throw std::runtime_error("Sampling modes did not produce distinct raster pixels");
  verify_scale("1",800,508);verify_scale("2",800,508);
  verify_scale("3",800,508);verify_scale("4",800,508);verify_scale("5",677,508);
  if(hash(verify("off","0",false,true,"nearest","0","100"))==nearest)throw std::runtime_error("CAS did not change the raster");
  if(hash(verify("off","0",false,true,"nearest","0","0","100"))==nearest)throw std::runtime_error("Bilateral did not change the raster");
  if(hash(verify("off","0",false,true,"nearest","0","0","0","1"))==nearest)throw std::runtime_error("SMAA did not change the raster");
  verify("bvm-1080","37",true,true,"bicubic","5","47","38","1");
  verify("phosphor","37",true,true,"sharp-bilinear","1","40","35","1");
  return 0;
 }
 SetEnvironmentVariableA("MK1_SCANLINES","0.5");
 for(const char* preset:{"off","bvm-1080","bvm-4k","bvm-soft","energy","pvm"})for(const char* amount:{"0","37","100"})verify(preset,amount,true);
 verify("off","0",false);
 verify("off","0",true,true);
 verify("off","37",true,true);
 verify("bvm-1080","0",true,true);
 verify("bvm-1080","37",true,true);
 verify("phosphor","0",false,true);
 const auto reject=[&](const char* key,const char* invalid,const char* restored){
  SetEnvironmentVariableA(key,invalid);bool rejected=false;
  try{Mk5Window window;}catch(const std::runtime_error&){rejected=true;}
  SetEnvironmentVariableA(key,restored);
  if(!rejected)throw std::runtime_error(std::string("invalid setting accepted: ")+key);
 };
 for(const char* invalid:{"101","-1","NaN","37.5",""})reject("MK1_SCALEFX",invalid,"0");
 reject("MK1_CAS","101","0");reject("MK1_BILATERAL","-1","0");
 reject("MK1_SCALE_MODE","6","0");reject("MK1_SMAA","2","0");reject("MK1_FILTER","cubic","nearest");
 return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
