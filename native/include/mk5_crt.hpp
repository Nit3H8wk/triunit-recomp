#pragma once
#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <sstream>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>
namespace mk5crt {
struct Settings {
 std::string preset="off";float mode=0,scanline_strength=.85f,beam_min=.22f,beam_max=.40f;
 float mask_strength=.30f,mask_pitch=2,mask_scale=1,horizontal_blend=.12f,halation=.035f;
 float horizontal_sharpness=.65f;
 float gamma_in=2.4f,gamma_out=2.2f,gain=1.28f,curvature=0;
 bool enabled()const{return mode!=0;}
 bool phosphor()const{return mode==4;}
 template<class Read> void load(Read read){
  const auto name=read("MK1_CRT_PRESET");if(!name.empty())preset=name;
  if(preset=="off")mode=0;
  else if(preset=="bvm-1080")mode=1;
  else if(preset=="bvm-4k"){mode=2;mask_pitch=4;mask_scale=2;mask_strength=.24f;}
  else if(preset=="bvm-soft"){mode=1;scanline_strength=.62f;beam_min=.28f;beam_max=.46f;mask_strength=.18f;horizontal_blend=.18f;halation=.055f;gain=1.25f;}
  // Presentation approximation, not calibration against a particular PVM unit.
  else if(preset=="pvm"){mode=1;scanline_strength=.70f;beam_min=.30f;beam_max=.52f;mask_strength=.22f;horizontal_blend=.22f;halation=.07f;gain=1.24f;}
  else if(preset=="energy"){mode=3;beam_min=.18f;beam_max=.60f;mask_strength=0;halation=0;gain=1;gamma_in=gamma_out=2.2f;}
  else if(preset=="phosphor"){
   mode=4;scanline_strength=.60f;beam_min=.23f;beam_max=.43f;
   mask_strength=.22f;mask_pitch=3;halation=0;gain=1;
   return; // The approved SDR profile has fixed coefficients and sRGB transfer.
  }
  else throw std::runtime_error("MK1_CRT_PRESET must be off, bvm-1080, bvm-4k, bvm-soft, energy, pvm or phosphor");
  struct Parameter{const char* name;float* value;double low,high;};
  const Parameter parameters[]={
   {"SCANLINE_STRENGTH",&scanline_strength,0,1},{"BEAM_MIN",&beam_min,.15,.60},{"BEAM_MAX",&beam_max,.15,.60},
   {"MASK_STRENGTH",&mask_strength,0,1},{"MASK_SCALE",&mask_scale,1,4},{"HORIZONTAL_BLEND",&horizontal_blend,0,.5},
   {"HALATION",&halation,0,.15},{"GAMMA_IN",&gamma_in,1,3},{"GAMMA_OUT",&gamma_out,1,3},
   {"GAIN",&gain,mode==3?1.:1.2,1.35},{"CURVATURE",&curvature,0,.12},
   {"SCANLINE_WEIGHT",&scanline_strength,0,1},{"BEAM_MIN_SIGMA",&beam_min,.15,.60},{"BEAM_MAX_SIGMA",&beam_max,.15,.60},
   {"MASK_INTENSITY",&mask_strength,0,1},{"HORIZONTAL_SHARPNESS",&horizontal_sharpness,0,1},{"HALATION_STRENGTH",&halation,0,.15},{"BRIGHTNESS_BOOST",&gain,mode==3?1.:1.2,1.35}};
  for(const auto& p:parameters){const auto key=std::string("MK1_CRT_")+p.name;const auto text=read(key.c_str());if(text.empty())continue;
   bool digit=false,dot=false;double value=0;
   for(char c:text){if(c>='0'&&c<='9'){digit=true;}
    else if(c=='.'&&!dot){dot=true;}else throw std::runtime_error(key+" requires an unsigned decimal");}
   const auto parsed=std::from_chars(text.data(),text.data()+text.size(),value);
   if(!digit||parsed.ec!=std::errc()||parsed.ptr!=text.data()+text.size()||!std::isfinite(value)||value<p.low||value>p.high)throw std::runtime_error(key+" outside validated range");
   *p.value=float(value);
  }
  if(mask_scale!=std::floor(mask_scale) || (mode==2 && (int(mask_scale)%2)))throw std::runtime_error("MK1_CRT_MASK_SCALE requires an integer; RGB-black requires 2 or 4");
  mask_pitch=2*mask_scale;
  if(beam_min>beam_max)throw std::runtime_error("MK1_CRT_BEAM_MIN must be <= MK1_CRT_BEAM_MAX");
 }
 std::string json(bool integer_vertical)const{std::ostringstream s;s<<"\"crt_preset\":\""<<preset<<"\",\"crt_single_pass\":true,\"crt_source\":\"complete-original\",\"crt_integer_vertical\":"<<(integer_vertical?"true":"false")
  <<",\"crt_parameters\":{\"SCANLINE_STRENGTH\":"<<scanline_strength<<",\"BEAM_MIN\":"<<beam_min<<",\"BEAM_MAX\":"<<beam_max<<",\"MASK_STRENGTH\":"<<mask_strength<<",\"MASK_PITCH\":"<<mask_pitch;
  if(phosphor())s<<",\"TRANSFER\":\"sRGB\",\"HORIZONTAL_SIGMA\":0.34";
  else s<<",\"HORIZONTAL_SHARPNESS\":"<<horizontal_sharpness<<",\"MASK_SCALE\":"<<mask_scale<<",\"HORIZONTAL_BLEND\":"<<horizontal_blend<<",\"HALATION\":"<<halation<<",\"GAMMA_IN\":"<<gamma_in<<",\"GAMMA_OUT\":"<<gamma_out<<",\"GAIN\":"<<gain<<",\"CURVATURE\":"<<curvature;
  s<<"}";return s.str();}
};
// Whole source remains visible even below 1x. At small sizes, beam modulation is
// analytically faded to avoid subpixel vertical aliasing; no source row is cropped.
struct Viewport{float x,y,width,height;};
inline Viewport viewport(unsigned width,unsigned height,unsigned source_height,bool crt){
 float h=std::min(float(height),float(width)*.75f);
 if(crt&&source_height&&h>=source_height)h=std::floor(h/source_height)*source_height;
 const float w=h*4/3;return {(width-w)/2,(height-h)/2,w,h};
}
inline Viewport phosphor_viewport(unsigned width,unsigned height,unsigned source_height){
 unsigned h=std::min(height,std::max(1u,width*3/4));
 if(source_height&&h>=source_height)h=h/source_height*source_height;
 const unsigned w=std::min(width,(h*4+1)/3);
 return {float((width-w)/2),float((height-h)/2),float(w),float(h)};
}
inline float srgb_decode(float x){return x<.04045f?x/12.92f:std::pow((x+.055f)/1.055f,2.4f);}
inline float srgb_encode(float x){return x<.0031308f?12.92f*x:1.055f*std::pow(x,1.f/2.4f)-.055f;}

// Reference for the in-memory readback validator. Saturated peaks share their
// excess with the unused headroom in the same scanline or RGB triad.
inline void redistribute(float* group,int size,float budget){
 float sum=0;
 for(int i=0;i<size;++i)sum+=group[i];
 const float gain=sum>0?budget/sum:0;
 float bounded=0;
 for(int i=0;i<size;++i){group[i]=std::min(1.f,group[i]*gain);bounded+=group[i];}
 const float share=bounded<size?std::clamp((budget-bounded)/(size-bounded),0.f,1.f):0;
 for(int i=0;i<size;++i)group[i]+=(1-group[i])*share;
}
// One phosphor beam (vertical scale >= 2): column x of output row y, after the scanline profile, linear light. `du` moves the
// filtered source sample (in output u) for the readback validator's subtexel band; the Gaussian tap path ignores it.
template<class Fetch,class Sample=std::nullptr_t,class Stage=std::nullptr_t>
inline std::array<float,3> phosphor_beam(const Settings& s,int x,int y,int out_width,int out_height,int width,int height,
                                         Fetch fetch,Sample sample=nullptr,Stage stage=nullptr,float du=0){
 const int scale=out_height/height;
 const int source_y=y/scale;
 const float at=(x+.5f)*width/out_width-.5f;
 const int center=int(std::floor(at+.5f));
 std::array<float,3> rgb{};
 const float u=(x+.5f)/out_width+du,v=(source_y+.5f)/height;
 bool staged=false;
 if constexpr(!std::is_same_v<Stage,std::nullptr_t>)staged=stage(u,v,(y+.5f)/out_height,rgb);
 if(!staged){
  if constexpr(std::is_same_v<Sample,std::nullptr_t>){
   float sum=0;
   for(int tap=-2;tap<=2;++tap){
    const int sx=center+tap;
    const float distance=(at-sx)/.34f;
    const float weight=std::exp(-.5f*distance*distance);
    for(unsigned c=0;c<3;++c)rgb[c]+=weight*fetch(sx,source_y,16-8*c);
    sum+=weight;
   }
   for(float& value:rgb)value=std::min(1.f,value/sum);
  }else rgb=sample(u,v);
 }
 const float lum=rgb[0]*.2126f+rgb[1]*.7152f+rgb[2]*.0722f;
 const float sigma=s.beam_min+(s.beam_max-s.beam_min)*std::sqrt(lum);
 std::vector<float> weights(scale),values(scale);
 float average=0;
 for(int i=0;i<scale;++i){
  const float distance=((i+.5f)/scale-.5f)/sigma;
  weights[i]=std::exp(-.5f*distance*distance);
  average+=weights[i]/scale;
 }
 for(float& value:rgb){
  for(int i=0;i<scale;++i)values[i]=value*(1-s.scanline_strength+s.scanline_strength*weights[i]/average);
  redistribute(values.data(),scale,value*scale);
  value=values[y%scale];
 }
 return rgb;
}
// The aperture-grille triad: lane i of the three beams, sRGB encoded.
inline std::array<float,3> phosphor_mask(const Settings& s,const std::array<std::array<float,3>,3>& beams,int lane){
 std::array<float,3> out{};
 for(unsigned c=0;c<3;++c){
  float values[3],budget=0;
  for(unsigned i=0;i<3;++i){
   budget+=beams[i][c];
   values[i]=beams[i][c]*(1+s.mask_strength*(i==c?2.f:-1.f));
  }
  redistribute(values,3,budget);
  out[c]=srgb_encode(values[lane]);
 }
 return out;
}
template<class Fetch,class Sample=std::nullptr_t,class Stage=std::nullptr_t>
inline void phosphor_reference_row(const Settings& s,int left,int y,int out_width,int out_height,
                                  int width,int height,Fetch fetch,std::vector<std::array<float,3>>& row,
                                  Sample sample=nullptr,Stage stage=nullptr){
 const int scale=out_height/height;
 const int source_y=scale>=2?y/scale:(2*y+1)*height/(2*out_height);
 row.resize(out_width);
 if(scale<2){
  for(int x=0;x<out_width;++x){
   const float u=(x+.5f)/out_width,v=(y+.5f)/out_height;
   bool staged=false;
   if constexpr(!std::is_same_v<Stage,std::nullptr_t>)staged=stage(u,v,v,row[x]);
   if(!staged){
    if constexpr(std::is_same_v<Sample,std::nullptr_t>){
     for(unsigned c=0;c<3;++c)row[x][c]=fetch((2*x+1)*width/(2*out_width),source_y,16-8*c);
    }else row[x]=sample(u,v);
   }
   for(float& value:row[x])value=srgb_encode(value);
  }
  return;
 }
 for(int x=0;x<out_width;++x)row[x]=phosphor_beam(s,x,y,out_width,out_height,width,height,fetch,sample,stage);
 for(int first=-(left%3);first<out_width;first+=3){
  const std::array<std::array<float,3>,3> beams{row[std::clamp(first,0,out_width-1)],row[std::clamp(first+1,0,out_width-1)],
                                                row[std::clamp(first+2,0,out_width-1)]};
  for(int i=0;i<3;++i)if(first+i>=0&&first+i<out_width)row[first+i]=phosphor_mask(s,beams,i);
 }
}
// Independent scalar reference used only by the opt-in in-memory GPU validator.
// Match the shader's half-step at 8-bit subtexel precision before selecting a texel.
inline int sample_index(float at){return int(std::floor(at+1.f/512));}
template<class Fetch,class Sample=std::nullptr_t,class Stage=std::nullptr_t>
inline std::array<float,3> reference_rgb(const Settings& s,float u,float v,float screen_x,float scale,unsigned width,unsigned height,
                                         Fetch fetch,unsigned source_scale=1,Sample sample=nullptr,Stage stage=nullptr){
 if(s.curvature>0){const float x=u*2-1,y=v*2-1;u=(x*(1+s.curvature*y*y)+1)*.5f;v=(y*(1+s.curvature*x*x)+1)*.5f;if(u<0||u>1||v<0||v>1)return {};}
 const float position=v*height-.5f;const int center=sample_index(position+.5f);
 auto row=[&](int y,unsigned c){
  if(source_scale>1)return fetch(sample_index(u*width*source_scale),sample_index((y+.5f+(position-center))*source_scale),c);
  const float at=u*width-.5f;const int x=sample_index(at+.5f);const float delta=at-x;
  const float sigma=.15f+.5f*(1-s.horizontal_sharpness);float total=0,weight=0;
  for(int tap=-1;tap<=1;++tap){const float d=delta-tap;const float w=std::exp(-.5f*d*d/(sigma*sigma));total+=fetch(x+tap,y,c)*w;weight+=w;}
  const float center=fetch(x,y,c);return center+(total/weight-center)*s.horizontal_blend;};
 std::array<float,3> beam{},glow{},base{};
 for(int offset=-1;offset<=1;++offset){
  const int y=center+offset;
  const float row_v=(y+.5f+(source_scale>1?position-center:0))/height;
  std::array<float,3> rgb{};
  bool staged=false;
  if constexpr(!std::is_same_v<Stage,std::nullptr_t>)staged=stage(u,row_v,(y+.5f+(position-center))/height,rgb);
  if(!staged){
   if constexpr(std::is_same_v<Sample,std::nullptr_t>)rgb={row(y,16),row(y,8),row(y,0)};
   else rgb=sample(u,row_v);
  }
  if(offset==0)base=rgb;
  const float luminance=rgb[0]*.2126f+rgb[1]*.7152f+rgb[2]*.0722f;
  const float distance=position-y;
  const auto beam_weight=[&](float intensity){
   const float sigma=s.beam_min+(s.beam_max-s.beam_min)*std::sqrt(std::max(0.f,intensity));
   return std::exp(-.5f*distance*distance/(sigma*sigma))/(2.50662827f*sigma);
  };
  const float weight=s.mode==3?0:beam_weight(luminance);
  for(unsigned c=0;c<3;++c){
   beam[c]+=rgb[c]*(s.mode==3?beam_weight(rgb[c]):weight);
   glow[c]+=rgb[c]*(offset==0?.5f:.25f);
  }
 }
 const float blend=s.scanline_strength*std::max(0.f,std::min(1.f,scale-1));
 const float phase=std::fmod(std::floor(screen_x),s.mask_pitch)/s.mask_pitch;
 for(unsigned c=0;c<3;++c){
  float value=base[c]+(beam[c]-base[c])*blend;
  value+=s.halation*glow[c]*std::sqrt(std::max(0.f,base[c]));
  const bool selected=s.mode==3||(s.mode==1?(c!=1)==(phase<.5f):c==unsigned(std::floor(phase*4)));
  value*=s.gain*(1-s.mask_strength+s.mask_strength*float(selected));
  base[c]=std::pow(std::clamp(value,0.f,1.f),1/s.gamma_out);
 }
 return base;
}
template<class Fetch>
inline float reference(const Settings& s,float u,float v,float screen_x,float scale,unsigned width,unsigned height,unsigned component,Fetch fetch,unsigned source_scale=1){
 return 255*reference_rgb(s,u,v,screen_x,scale,width,height,fetch,source_scale)[2-component/8];
}
}
