#pragma once

namespace mk5smaa::upstream {
// iryoku/smaa, MIT license, commit 71c806a838bdd7d517df19192a20f0c61b3ca29d.
// https://github.com/iryoku/smaa/tree/71c806a838bdd7d517df19192a20f0c61b3ca29d
// The LUT declarations are inline constexpr for embedding in C++17.
#include "mk5_smaa_upstream/AreaTex.h"
#include "mk5_smaa_upstream/SearchTex.h"
inline constexpr unsigned area_width = AREATEX_WIDTH, area_height = AREATEX_HEIGHT, area_pitch = AREATEX_PITCH;
inline constexpr unsigned search_width = SEARCHTEX_WIDTH, search_height = SEARCHTEX_HEIGHT, search_pitch = SEARCHTEX_PITCH;
static_assert(sizeof(areaTexBytes) == AREATEX_SIZE);
static_assert(sizeof(searchTexBytes) == SEARCHTEX_SIZE);
#undef AREATEX_WIDTH
#undef AREATEX_HEIGHT
#undef AREATEX_PITCH
#undef AREATEX_SIZE
#undef SEARCHTEX_WIDTH
#undef SEARCHTEX_HEIGHT
#undef SEARCHTEX_PITCH
#undef SEARCHTEX_SIZE
}

namespace mk5smaa {
inline constexpr char shader[] = R"SMAA(
cbuffer Settings : register(b0) { float4 metrics; }
#define SMAA_RT_METRICS metrics
#define SMAA_HLSL_4 1
#define SMAA_PRESET_HIGH 1
)SMAA"
// Upstream HLSL with explicit sampler registers for the D3D12 root signature.
#include "mk5_smaa_upstream/SMAA.hlsl.h"
R"SMAA(
Texture2D input0 : register(t0);
Texture2D input1 : register(t1);
Texture2D input2 : register(t2);

struct Vertex {
    float4 position : SV_POSITION;
    float2 uv : TEXCOORD0;
    float2 pixel : TEXCOORD1;
    float4 offsets[3] : TEXCOORD2;
};

Vertex fullscreen(uint id) {
    Vertex v = (Vertex)0;
    v.uv = float2((id << 1) & 2, id & 2);
    v.position = float4(v.uv * float2(2, -2) + float2(-1, 1), 0, 1);
    return v;
}

Vertex edgeVS(uint id : SV_VertexID) {
    Vertex v = fullscreen(id);
    SMAAEdgeDetectionVS(v.uv, v.offsets);
    return v;
}

Vertex weightsVS(uint id : SV_VertexID) {
    Vertex v = fullscreen(id);
    SMAABlendingWeightCalculationVS(v.uv, v.pixel, v.offsets);
    return v;
}

Vertex neighborhoodVS(uint id : SV_VertexID) {
    Vertex v = fullscreen(id);
    SMAANeighborhoodBlendingVS(v.uv, v.offsets[0]);
    return v;
}

float2 edgePS(Vertex v) : SV_TARGET {
    return SMAAColorEdgeDetectionPS(v.uv, v.offsets, input0);
}

float4 weightsPS(Vertex v) : SV_TARGET {
    return SMAABlendingWeightCalculationPS(v.uv, v.pixel, v.offsets, input0, input1, input2, float4(0, 0, 0, 0));
}

float4 neighborhoodPS(Vertex v) : SV_TARGET {
    return SMAANeighborhoodBlendingPS(v.uv, v.offsets[0], input0, input1);
}
)SMAA";
}
