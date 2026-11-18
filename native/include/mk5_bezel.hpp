#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
namespace mk5bezel {
// Game frame: a glossy black CRT television drawn in code, after a reference picture chosen by the user (the picture is
// not read or shipped). Units below are 1920x1080 reference pixels: the set spans x 128..1792, y 2..1078, and the glass is
// the game's exact 4:3 opening, 968 units high (about 90% of the screen height), so the game stays the largest element.
struct Tv {int width=0,height=0,left=0,top=0,right=0,bottom=0;float scale=1,ox=0,oy=0,radius=0;};
constexpr float kGlassHeight=968,kGlassTop=26,kBodyLeft=128,kBodyRight=1792,kBodyTop=2,kBodyBottom=1078,kBodyRadius=110;
inline Tv tv_layout(int width,int height){
 Tv t;t.width=width;t.height=height;t.scale=std::min(float(height)/1080,float(width)/1700);
 t.ox=float(width)*.5f-960*t.scale;t.oy=float(height)*.5f-540*t.scale;
 const int h=std::max(3,int(std::lround(kGlassHeight*t.scale))),w=int(std::lround(float(h)*4/3));
 t.left=(width-w)/2;t.right=t.left+w;t.top=int(std::lround(t.oy+kGlassTop*t.scale));t.bottom=t.top+h;
 t.radius=22*t.scale;return t;
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
// Dark vertical panelling behind the set.
inline Rgb wall(float x,float y){
 const float plank=(x+40)/150.f;const int k=int(std::floor(plank));const float u=(plank-float(k))*150;
 Rgb c=scale(mix(hex(0x141113),hex(0x1d1716),smooth(0,1080,y)),.85f+.25f*hash(k,3));
 c=scale(c,.85f+.3f*noise(x*.4f+float(k)*5.1f,y*.006f));
 if(u<3)return scale(c,.35f);
 return u<5?scale(c,1.25f):c;
}
// Front of the set (sd: distance to the shell edge): glossy shell, recessed screen surround with a lit lip, speaker
// grilles with a red accent, and the control strip under the glass.
inline Rgb set(const Tv& t,float x,float y,float sd){
 const float gl=(float(t.left)-t.ox)/t.scale,gt=(float(t.top)-t.oy)/t.scale,gr=(float(t.right)-t.ox)/t.scale,gb=(float(t.bottom)-t.oy)/t.scale;
 Rgb c=mix(hex(0x1d1e22),hex(0x09090b),smooth(40,620,y));
 c=mix(c,hex(0x2c2e33),.6f*std::exp(-std::min(x-kBodyLeft,kBodyRight-x)/38)*smooth(1000,200,y));
 c=mix(c,hex(0x8a8d94),.7f*std::exp(sd/3.5f)*(1-.75f*smooth(60,700,y)));
 const float glass=rounded(x,y,gl,gt,gr,gb,t.radius/t.scale);
 if(glass<20){
  Rgb b=mix(hex(0x020203),hex(0x0d0d10),glass/20);
  if(y<gt)b=mix(b,hex(0x16171a),.5f*glass/20);
  b=mix(b,hex(0x55585f),.55f*std::exp(-std::abs(glass-18.5f)/1.2f)*(y<gt?1.f:y>gb?.35f:.6f));
  c=mix(c,b,1-smooth(19,20.5f,glass));
 }
 for(const float side:{-1.f,1.f}){
  const float cx=960+side*(gr-960+(kBodyRight-gr)*.5f-2),half=(kBodyRight-gr)*.5f-26;
  if(std::abs(x-cx)>=half)continue;
  const float g=rounded(x,y,cx-half,560,cx+half,960,18);
  if(g<0){
   const Rgb s=std::fmod(y-560,9.f)<4&&g<-6?hex(0x1a1b1e):hex(0x08080a);
   c=mix(c,s,smooth(0,-2,g));
  }
  if(y>=968&&y<972)c=hex(0x8c1a22);
 }
 const float py=(gb+kBodyBottom)*.5f,pill=rounded(x,y,700,py-17,1220,py+17,17);
 if(pill<0){
  Rgb s=mix(hex(0x050506),hex(0x131417),smooth(py-17,py+17,y));
  for(const float k:{752.f,808.f,864.f,926.f}){
   const float r=std::hypot((x-k)*(k==926?.7f:1),y-py);
   if(r<12)s=r>10.5f?hex(0x2b2d32):mix(hex(0x18191c),hex(0x0a0a0c),smooth(py-12,py+12,y));
  }
  if(x>1040&&x<1066&&std::abs(y-py)<2.5f)s=hex(0xe0303c);
  if(rounded(x,y,1090,py-12,1130,py+12,5)<0)s=hex(0x1c1d21);
  c=mix(c,s,smooth(0,-1.5f,pill));
 }
 return c;
}
}
// The frame at output pixel (x,y), 0xAARRGGBB: alpha 0 on the glass (the game), 255 elsewhere.
inline uint32_t tv_pixel(const Tv& t,int x,int y){
 if(glass(t,x,y))return 0;
 const float pixel=1/t.scale,rx=(float(x)+.5f-t.ox)*pixel,ry=(float(y)+.5f-t.oy)*pixel;
 const float shell=rounded(rx,ry,kBodyLeft,kBodyTop,kBodyRight,kBodyBottom,kBodyRadius);
 detail::Rgb c=detail::wall(rx,ry);
 if(shell>0)c=detail::scale(c,1-.6f*std::exp(-shell/30));
 c=detail::mix(c,detail::set(t,rx,ry,shell),std::clamp(.5f-shell/pixel,0.f,1.f));
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
