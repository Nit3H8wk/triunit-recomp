#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
namespace mk5bezel {
// Game frame: a CRT television on a wood-panel wall, drawn in code. Geometry and colors were measured on a 1920x1080
// reference picture chosen by the user; the picture is not read or shipped, and the posters on its wall are left out.
// Units below are reference pixels. The glass is the game's 4:3 opening.
struct Tv {int width=0,height=0,left=0,top=0,right=0,bottom=0;float scale=1,ox=0,oy=0,radius=0;};
inline Tv tv_layout(int width,int height){
 Tv t;t.width=width;t.height=height;t.scale=std::min(float(height)/1080,float(width)/1400);
 t.ox=float(width)*.5f-960*t.scale;t.oy=float(height)*.5f-540*t.scale;
 const int h=std::max(3,int(std::lround(765*t.scale))),w=int(std::lround(float(h)*4/3));
 t.left=(width-w)/2;t.right=t.left+w;t.top=int(std::lround(t.oy+548*t.scale-float(h)*.5f));t.bottom=t.top+h;
 t.radius=16*t.scale;return t;
}
// Signed distance to a rounded rectangle (negative inside).
inline float rounded(float x,float y,float l,float t,float r,float b,float radius){
 const float qx=std::max(l+radius-x,x-(r-radius)),qy=std::max(t+radius-y,y-(b-radius));
 return std::hypot(std::max(qx,0.f),std::max(qy,0.f))+std::min(std::max(qx,qy),0.f)-radius;
}
// The game shows through the glass: the pixel centre inside the rounded opening.
inline bool glass(const Tv& t,int x,int y){
 return rounded(float(x)+.5f,float(y)+.5f,float(t.left),float(t.top),float(t.right),float(t.bottom),t.radius)<0;
}
namespace detail {
using Rgb=std::array<float,3>;
constexpr Rgb hex(uint32_t c){return {float(c>>16&255)/255,float(c>>8&255)/255,float(c&255)/255};}
inline Rgb mix(Rgb a,Rgb b,float k){k=std::clamp(k,0.f,1.f);return {a[0]+(b[0]-a[0])*k,a[1]+(b[1]-a[1])*k,a[2]+(b[2]-a[2])*k};}
inline Rgb scale(Rgb a,float k){return {a[0]*k,a[1]*k,a[2]*k};}
inline float smooth(float a,float b,float x){x=std::clamp((x-a)/(b-a),0.f,1.f);return x*x*(3-2*x);}
inline float hash(int x,int y){uint32_t h=uint32_t(x)*0x8da6b343u^uint32_t(y)*0xd8163841u;h=(h^(h>>13))*0x5bd1e995u;return float((h^(h>>15))&0xffffff)/16777216.f;}
inline float noise(float x,float y){
 const int ix=int(std::floor(x)),iy=int(std::floor(y));const float fx=x-float(ix),fy=y-float(iy);
 const float sx=fx*fx*(3-2*fx),sy=fy*fy*(3-2*fy);
 const float a=hash(ix,iy)+(hash(ix+1,iy)-hash(ix,iy))*sx,b=hash(ix,iy+1)+(hash(ix+1,iy+1)-hash(ix,iy+1))*sx;
 return a+(b-a)*sy;
}
// Vertical wood planks (grooves every 189.75 units), cool shadow on the left, warm light on the right; carved shelf below.
inline Rgb wall(float x,float y){
 if(y>=985){
  Rgb c=mix(hex(0x030103),hex(0x130e0f),smooth(600,1500,x));
  const float wave=std::sin(x*.06f+1.6f*std::sin(y*.13f+x*.011f)+3*noise(x*.01f,y*.05f));
  c=mix(c,scale(hex(0x6a5a50),.2f+.8f*smooth(600,1700,x)),.3f*smooth(.93f,.99f,wave));
  return y<990?mix(c,hex(0x2a2020),.6f):c;
 }
 const Rgb warm=y<400?mix(hex(0x40393f),hex(0x42312a),y/400):mix(hex(0x42312a),hex(0x302520),(y-400)/585);
 const Rgb cool=mix(hex(0x1a1a20),hex(0x141415),smooth(150,300,x));
 const float plank=(x-10.25f)/189.75f;const int k=int(std::floor(plank));const float u=(plank-float(k))*189.75f;
 Rgb c=scale(mix(cool,warm,smooth(700,1400,x)),.9f+.2f*hash(k,7));
 c=scale(c,.86f+.28f*(.65f*noise(x*.45f+float(k)*7.3f,y*.004f)+.35f*noise(x*1.7f,y*.02f)));
 if(u<4)return scale(c,.25f);
 return u<6?scale(c,1.12f):c;
}
// Front of the set: plastic shell, dark groove, recessed inner frame, mitred screen surround, then the glass.
inline Rgb set(const Tv& t,float x,float y,float pixel){
 const float gl=(float(t.left)-t.ox)/t.scale,gt=(float(t.top)-t.oy)/t.scale,gr=(float(t.right)-t.ox)/t.scale,gb=(float(t.bottom)-t.oy)/t.scale;
 const float shell=rounded(x,y,290,6,1636,1200,16);
 if(x>=398&&x<1518&&y>=118&&y<972){
  const float left=(x-398)/std::max(1.f,gl-398),right=(1518-x)/std::max(1.f,1518-gr),top=(y-118)/std::max(1.f,gt-118),bottom=(972-y)/std::max(1.f,972-gb);
  const float m=std::min({left,right,top,bottom});
  if(rounded(x,y,gl,gt,gr,gb,t.radius/t.scale)>-1.5f*pixel&&m>.9f)return hex(0x010413);
  if(m==top)return mix(hex(0x0b1e36),hex(0x1a2745),top);
  if(m==bottom)return mix(hex(0x344459),hex(0x40627f),bottom);
  if(m==left)return mix(hex(0x172c42),hex(0x1d344e),left);
  return mix(hex(0x21273b),hex(0x152443),right);
 }
 if(x>=326&&x<1598&&y>=58&&y<1024){
  Rgb c=y<118?hex(0x23272c):y>=972?hex(0x252a2e):mix(hex(0x1c222b),hex(0x2a262a),(x-326)/1272);
  const float edge=std::min({x-326,1598-x,y-58,1024-y});
  return scale(c,.7f+.3f*smooth(0,8,edge));
 }
 if(x>=320&&x<1606&&y>=52&&y<1032)return hex(0x0b0f12);
 Rgb c;
 if(y<52)c=mix(hex(0x4b535c),hex(0x42484f),(y-6)/46);
 else if(y<1032)c=mix(hex(0x2c3846),hex(0x504c54),(x-290)/1346);
 else c=mix(hex(0x404651),hex(0x4b5969),(x-290)/1346);
 if(y>=1032){
  if(x>=767&&x<1367&&y>=1040){
   c=y<1043?hex(0x14181b):hex(0x252c31);
   for(const float k:{809.f,897.f,987.f,1075.f,1165.f,1253.f}){
    if(std::abs(std::hypot(x-k,y-1059)-4)<.8f)c=hex(0x8a95a0);
    const float d=std::hypot(x-k,y-1086);if(d<12)c=d>10.5f?hex(0x3a4148):hex(0x0d1013);
   }
  }
  if(x>=1418&&x<1520&&y>=1036){c=y<1039?hex(0x6a7480):hex(0x4b5661);if(x>=1455&&x<1478&&y>=1057&&y<1066)c=hex(0xb8283a);}
 }
 if(shell>-3)c=scale(c,x>1500?.8f:1.15f);
 return c;
}
}
// The frame at output pixel (x,y), 0xAARRGGBB: alpha 0 on the glass (the game), 255 elsewhere.
inline uint32_t tv_pixel(const Tv& t,int x,int y){
 if(glass(t,x,y))return 0;
 const float pixel=1/t.scale,rx=(float(x)+.5f-t.ox)*pixel,ry=(float(y)+.5f-t.oy)*pixel;
 const float shell=rounded(rx,ry,290,6,1636,1200,16);
 detail::Rgb c=detail::wall(rx,ry);
 if(shell>0)c=detail::scale(c,1-.55f*std::exp(-shell/22));
 c=detail::mix(c,detail::set(t,rx,ry,pixel),std::clamp(.5f-shell/pixel,0.f,1.f));
 uint32_t out=0xff000000u;
 for(int i=0;i<3;++i)out|=uint32_t(std::lround(std::clamp(c[size_t(i)],0.f,1.f)*255))<<(16-8*i);
 return out;
}
// Launcher window sides (not the game frame): procedural metal/ruby/gold frame, rendered only outside the content rectangle.
// Emit accepts (left, top, right, bottom, red, green, blue). No assets or I/O.
template<class Emit> void draw(int width,int height,int left,int top,int right,int bottom,Emit emit){
 auto rect=[&](int l,int t,int r,int b,float red,float green,float blue){
  l=std::max(0,l);t=std::max(0,t);r=std::min(width,r);b=std::min(height,b);if(l>=r||t>=b)return;
  auto part=[&](int x,int y,int z,int w){if(x<z&&y<w)emit(x,y,z,w,red,green,blue);};
  part(l,t,r,std::min(b,top));part(l,std::max(t,bottom),r,b);
  const int y=std::max(t,top),end=std::min(b,bottom);part(l,y,std::min(r,left),end);part(std::max(l,right),y,r,end);
 };
 rect(0,0,width,height,.018f,.022f,.03f);
 const int unit=std::max(1,height/720);
 for(int y=0;y<height;y+=24*unit){
  rect(0,y,width,y+unit,.026f,.031f,.042f);
  const int reach=std::max(8*unit,left/2);const int step=(y/(24*unit))%5;
  rect(std::max(0,left-reach)+step*unit,y,left-9*unit,y+3*unit,.22f,.025f,.018f);
  rect(right+9*unit,y,std::min(width,right+reach)-step*unit,y+3*unit,.22f,.025f,.018f);
 }
 for(int side:{left-6*unit,right+3*unit})rect(side,0,side+3*unit,height,.46f,.23f,.065f);
 for(int side:{left-2*unit,right})rect(side,top,side+2*unit,bottom,.09f,.008f,.005f);
 rect(left-6*unit,top-4*unit,right+6*unit,top,.46f,.23f,.065f);
 rect(left-6*unit,bottom,right+6*unit,bottom+4*unit,.46f,.23f,.065f);
}
}
