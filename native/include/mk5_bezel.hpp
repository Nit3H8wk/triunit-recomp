#pragma once
#include <algorithm>
namespace mk5bezel {
// Procedural metal/ruby/gold frame, rendered only outside the content rectangle.
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
