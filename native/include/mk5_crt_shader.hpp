#pragma once
// Embedded HLSL. The display pass can select the MK1 backdrop over the source.
//
// The CAS sharpening kernel is adapted from AMD FidelityFX CAS v1.0.1
// https://github.com/GPUOpen-Effects/FidelityFX-CAS/blob/d70012e/ffx-cas/ffx_cas.h
// Copyright (c) 2017-2019 Advanced Micro Devices, Inc. All rights reserved.
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.
namespace mk5crt {
constexpr char shader[]=R"HLSL(
struct V {float4 pos:SV_Position;float2 uv:TEXCOORD0;};
V vs(uint id:SV_VertexID){V o;o.uv=float2((id<<1)&2,id&2);o.pos=float4(o.uv*float2(2,-2)+float2(-1,1),0,1);return o;}
Texture2D image:register(t0);SamplerState imageSampler:register(s0);
Texture2D backdrop:register(t1);
// A session keeps its preset and sampler fixed. Compile away unused kernels.
static const int crtMode=MK5_CRT_MODE,sample_mode=MK5_SAMPLE_MODE;
cbuffer Settings:register(b0){
 float sourceHeight,scanlineStrength,sourceWidth,unused;
 float scanline_weight,beam_min_sigma,beam_max_sigma,mask_intensity;
 float mask_scale,horizontal_blend,halation_strength,gamma_in;
 float gamma_out,brightness_boost,curvature,vertical_scale;
 float horizontal_sharpness,color_mode,brightness,sample_scale;
 float viewport_x,viewport_y,viewport_width,viewport_height;
 float decode_phosphor,cas_strength,bilateral_strength,stage_visible;
 float fighters_visible;
};
int2 sampleSize(){return int2(sourceWidth,sourceHeight)*(int)max(1,sample_scale);}
float3 loadPixel(int2 p,int2 size){return image.Load(int3(clamp(p,int2(0,0),size-1),0)).rgb;}
// Explicit point sampling keeps texel selection stable on subtexel boundaries.
float3 samplePoint(float2 at,int2 size){
 return loadPixel(int2(floor(at+1.0/512.0)),size);
}
float4 stagePixel(float2 uv){
 if(stage_visible==0)return 0;
 int2 size=int2(sourceWidth,sourceHeight)*4;
 int2 p=int2(floor(uv*size+1.0/512.0));
 return backdrop.Load(int3(clamp(p,int2(0,0),size-1),0));
}
float4 beamStage(float u,float v,float fine_v){
 float4 stage=stagePixel(float2(u,v));
 if(fighters_visible!=0){
  float4 fine=stagePixel(float2(u,fine_v));
  if(fine.a>.75 || stage.a>.75)return fine;
 }
 return stage;
}
float3 decodeSrgb(float3 rgb){
 return lerp(rgb/12.92,pow((rgb+.055)/1.055,2.4),step(.04045,rgb));
}
float3 encodeSrgb(float3 rgb){
 rgb=saturate(rgb);
 return lerp(12.92*rgb,1.055*pow(rgb,1.0/2.4)-.055,step(.0031308,rgb));
}
float3 reconstruct(float2 uv){
 float2 size=sampleSize();
 if(sample_mode==0)return samplePoint(uv*size,int2(size));
 if(sample_mode==1)return image.SampleLevel(imageSampler,uv,0).rgb;
 if(sample_mode==2){
  float2 scale=max(1,floor(float2(viewport_width,viewport_height)/size));
  float2 pixel=uv*size,f=frac(pixel),edge=.5/scale;
  float2 at=floor(pixel)+.5+(f-clamp(f,edge,1-edge))*scale;
  return image.SampleLevel(imageSampler,at/size,0).rgb;
 }
 // Catmull-Rom. The two positive center taps share one hardware linear sample.
 float2 pixel=uv*size-.5,base=floor(pixel),f=frac(pixel);
 float2 w0=f*(-.5+f*(1-.5*f)),w1=1+f*f*(-2.5+1.5*f);
 float2 w2=f*(.5+f*(2-1.5*f)),w3=f*f*(-.5+.5*f);
 float2 center=w1+w2,at=base+.5+w2/center;
 float3 xs=float3(base.x-.5,at.x,base.x+2.5)/size.x;
 float3 ys=float3(base.y-.5,at.y,base.y+2.5)/size.y;
 float3 wx=float3(w0.x,center.x,w3.x),wy=float3(w0.y,center.y,w3.y);
 float3 rgb=0;
 [unroll]for(int y=0;y<3;++y)[unroll]for(int x=0;x<3;++x)
  rgb+=wx[x]*wy[y]*image.SampleLevel(imageSampler,float2(xs[x],ys[y]),0).rgb;
 return saturate(rgb);
}
float3 fetch(int2 p){p=clamp(p,int2(0,0),int2(sourceWidth-1,sourceHeight-1));return pow(image.Load(int3(p,0)).rgb,gamma_in);}
float3 sourceRow(float u,float y,float fine_y){
 float4 stage=beamStage(u,(y+.5)/sourceHeight,(fine_y+.5)/sourceHeight);
 if(stage.a>0)return pow(stage.rgb,gamma_in);
 if(sample_mode!=0)return pow(reconstruct(float2(u,(y+.5)/sourceHeight)),gamma_in);
 if(sample_scale>0){
  precise float2 at=float2(u*sourceWidth,y+.5)*sample_scale;
  int2 size=int2(sourceWidth,sourceHeight)*(int)sample_scale;
  return pow(samplePoint(at,size),gamma_in);
 }
 float at=u*sourceWidth-.5;int x=(int)floor(at+.5+1.0/512.0);float delta=at-x;
 float sigma=.15+.5*(1-horizontal_sharpness);float3 total=0;float weight=0;
 [unroll]for(int tap=-1;tap<=1;++tap){float d=delta-tap;float w=exp(-.5*d*d/(sigma*sigma));total+=fetch(int2(x+tap,y))*w;weight+=w;}
 return lerp(fetch(int2(x,y)),total/weight,horizontal_blend);
}
float3 color(float3 rgb){if(color_mode==1){float y=dot(rgb,float3(.2126,.7152,.0722));rgb=(lerp(y.xxx,rgb,1.15)-.5)*1.05+.5;}if(color_mode==2)rgb*=float3(1.025,1,.94);return saturate(rgb*brightness);}
float3 phosphorSource(int2 p){
 float3 rgb=loadPixel(p,int2(sourceWidth,sourceHeight));
 return decode_phosphor!=0?decodeSrgb(rgb):rgb;
}
float3 phosphorSample(float2 uv){
 float3 rgb=reconstruct(uv);
 return decode_phosphor!=0?decodeSrgb(rgb):rgb;
}
float3 restoreEnergy(float3 value,float3 boundedSum,float3 budget,float count){
 float3 spare=count-boundedSum;
 float3 share=saturate((budget-boundedSum)/max(spare,1e-7));
 return value+(1-value)*share;
}
float3 phosphorBeam(int x,int y,int scale){
 float at=(x+.5)*sourceWidth/viewport_width-.5;
 int center=(int)floor(at+.5);
 float3 rgb=0;
 float total=0;
 float4 stage=beamStage((x+.5)/viewport_width,(y/scale+.5)/sourceHeight,(y+.5)/viewport_height);
 if(stage.a>0){
  rgb=decode_phosphor!=0?decodeSrgb(stage.rgb):stage.rgb;
 }else if(sample_mode!=0||sample_scale>0){
  rgb=phosphorSample(float2((x+.5)/viewport_width,(y/scale+.5)/sourceHeight));
 }else{
  [unroll]for(int tap=-2;tap<=2;++tap){
   int sx=center+tap;
   float d=(at-sx)/.34;
   float weight=exp(-.5*d*d);
   rgb+=weight*phosphorSource(int2(sx,y/scale));
   total+=weight;
  }
  rgb=saturate(rgb/total);
 }
 float sigma=lerp(beam_min_sigma,beam_max_sigma,sqrt(dot(rgb,float3(.2126,.7152,.0722))));
 float stepY=1.0/(scale*sigma), first=(.5-.5*scale)*stepY;
 int pairs=scale/2;
 float sum=scale%2;
 [loop]for(int i=0;i<pairs;++i){
  float d=first+i*stepY;
  sum+=2*exp(-.5*d*d);
 }
 float strength=scanline_weight*scale/sum, base=1-scanline_weight;
 float d=first+(y%scale)*stepY;
 float3 level=rgb*(base+strength*exp(-.5*d*d));
 if(max(rgb.r,max(rgb.g,rgb.b))*(base+strength)>1){
  float3 boundedSum=(scale%2)*saturate(rgb*(base+strength));
  [loop]for(int j=0;j<pairs;++j){
   float offset=first+j*stepY;
   boundedSum+=2*saturate(rgb*(base+strength*exp(-.5*offset*offset)));
  }
  level=restoreEnergy(saturate(level),boundedSum,rgb*scale,scale);
 }
 return level;
}
float3 phosphor(float2 pixel){
 int2 p=int2(pixel-float2(viewport_x,viewport_y));
 int scale=(int)vertical_scale;
 if(scale<2){
  float4 stage=stagePixel((p+.5)/float2(viewport_width,viewport_height));
  if(stage.a>0)return encodeSrgb(decode_phosphor!=0?decodeSrgb(stage.rgb):stage.rgb);
  if(sample_mode!=0||sample_scale>0)return encodeSrgb(phosphorSample((p+.5)/float2(viewport_width,viewport_height)));
  int2 texel=(2*p+1)*int2(sourceWidth,sourceHeight)/(2*int2(viewport_width,viewport_height));
  return encodeSrgb(phosphorSource(texel));
 }
 int lane=(int)pixel.x%3;
 int first=p.x-lane;
 float3 beam0=phosphorBeam(max(0,first),p.y,scale);
 float3 beam1=phosphorBeam(clamp(first+1,0,(int)viewport_width-1),p.y,scale);
 float3 beam2=phosphorBeam(min(first+2,(int)viewport_width-1),p.y,scale);
 float3 budget=beam0+beam1+beam2;
 float low=1-mask_intensity, high=1+2*mask_intensity;
 float3 rgb0=beam0*float3(high,low,low);
 float3 rgb1=beam1*float3(low,high,low);
 float3 rgb2=beam2*float3(low,low,high);
 float3 gain=budget/max(rgb0+rgb1+rgb2,1e-7);
 rgb0=saturate(rgb0*gain);rgb1=saturate(rgb1*gain);rgb2=saturate(rgb2*gain);
 float3 value=lane==0?rgb0:lane==1?rgb1:rgb2;
 return encodeSrgb(restoreEnergy(value,rgb0+rgb1+rgb2,budget,3));
}
float4 ps(V v):SV_Target {
 precise float2 uv=(v.pos.xy-float2(viewport_x,viewport_y))/float2(viewport_width,viewport_height);
 if(crtMode==4)return float4(color(phosphor(v.pos.xy)),1);
 if(crtMode==0){
  float3 rgb;
  float4 stage=stagePixel(uv);
  if(stage.a>0)rgb=stage.rgb;
  else if(sample_mode==1)rgb=image.SampleLevel(imageSampler,v.uv,0).rgb;
  else rgb=reconstruct(uv);
  uint row=(uint)floor(uv.y*sourceHeight+1.0/512.0);
  return float4(color(rgb*(1.0-((row&1)?scanlineStrength:0.0))),1);
 }
 if(curvature>0){precise float2 xy=uv*2-1;uv=(xy*(1+curvature*xy.yx*xy.yx)+1)*.5;if(any(uv<0)||any(uv>1))return float4(0,0,0,1);}
 float position=uv.y*sourceHeight-.5;int center=(int)floor(position+.5+1.0/512.0);float phase_y=position-center;float subpixel=sample_scale>0?phase_y:0;float3 beam=0,glow=0;
 [unroll]for(int offset=-1;offset<=1;++offset){int y=center+offset;float3 rgb=sourceRow(uv.x,y+subpixel,y+phase_y);float luminance=dot(rgb,float3(.2126,.7152,.0722));
  float sigma=lerp(beam_min_sigma,beam_max_sigma,sqrt(max(0,luminance)));float distance=position-y;
  float3 widths=crtMode==3?lerp(beam_min_sigma.xxx,beam_max_sigma.xxx,sqrt(max(0,rgb))):sigma.xxx;
  beam+=rgb*exp(-.5*distance*distance/(widths*widths))/(2.50662827*widths);glow+=rgb*(offset==0?.5:.25);
 }
 float3 base=sourceRow(uv.x,center+subpixel,position);float3 rgb=lerp(base,beam,scanline_weight*saturate(vertical_scale-1));
 rgb+=halation_strength*glow*sqrt(max(0,base));
 float phase=fmod(floor(v.pos.x),(2*mask_scale))/(2*mask_scale);float3 selected;
 if(crtMode==3)selected=1;
 else if(crtMode==1)selected=phase<.5?float3(1,0,1):float3(0,1,0);
 else {int slot=(int)floor(phase*4);selected=float3(slot==0,slot==1,slot==2);}
 rgb*=brightness_boost*lerp(float3(1,1,1),selected,mask_intensity);
 return float4(color(pow(saturate(rgb),1/gamma_out)),1);
}

float3 bilateral(int2 p,int2 size){
 float3 center=loadPixel(p,size),sum=center;
 float weights=1;
 [unroll]for(int y=-1;y<=1;++y)[unroll]for(int x=-1;x<=1;++x){
  if(x==0&&y==0)continue;
  float3 tap=loadPixel(p+int2(x,y),size),difference=tap-center;
  float w=exp(-(x*x+y*y)/1.62-dot(difference,difference)/.0288);
  sum+=w*tap;weights+=w;
 }
 return lerp(center,sum/weights,.65*bilateral_strength);
}
float3 cas(int2 p,int2 size){
 float3 a=decodeSrgb(loadPixel(p+int2(-1,-1),size)),b=decodeSrgb(loadPixel(p+int2(0,-1),size));
 float3 c=decodeSrgb(loadPixel(p+int2( 1,-1),size)),d=decodeSrgb(loadPixel(p+int2(-1,0),size));
 float3 e=decodeSrgb(loadPixel(p,size)),f=decodeSrgb(loadPixel(p+int2(1,0),size));
 float3 g=decodeSrgb(loadPixel(p+int2(-1,1),size)),h=decodeSrgb(loadPixel(p+int2(0,1),size));
 float3 i=decodeSrgb(loadPixel(p+int2( 1,1),size));
 float3 lo=min(e,min(min(b,d),min(f,h))),hi=max(e,max(max(b,d),max(f,h)));
 lo+=min(lo,min(min(a,c),min(g,i)));
 hi+=max(hi,max(max(a,c),max(g,i)));
 float3 amp=sqrt(saturate(min(lo,2-hi)/max(hi,1e-7)));
 float3 w=amp*(-cas_strength/lerp(8,5,cas_strength));
 return encodeSrgb((e+w*(b+d+f+h))/(1+4*w));
}
float4 psPrefilter(V v):SV_Target {
 int2 p=int2(v.pos.xy),size=int2(sourceWidth,sourceHeight);
 float3 rgb=cas_strength>0?cas(p,size):bilateral(p,size);
 // Round before writing UNORM8 so the next pass receives the nearest code.
 return float4(floor(saturate(rgb)*255+.5)/255,1);
}
)HLSL";
}
