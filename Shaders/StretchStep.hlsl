// P7c: 1 歩だけ上流を見て、より強い輪郭から来た色を受け継ぐ。これを N 回 ping-pong する。
//
// 1 画素ずつ長い流線を追ってはいけない。鞍点の近くで隣接画素の流線が指数的に離れ、
// 出力が櫛状の破線になる（解像度を上げても消えない。画素のエイリアスではなく実構造のため）。
// 毎パス隣だけを見る形にすると、バイリニア補間が発散を抑えるので縞が出ない。
#define D2D_ENTRY main
#include <d2d1effecthelpers.hlsli>
#include "FieldLineCommon.hlsli"

#define HSTEP        c0.x   // [1/2 texel]
#define RADIAL_SCALE c0.y
#define TIE          c0.z   // 1 歩ぶんの距離ペナルティ。同点なら近い輪郭を採る
#define RECT         c2
#define RADIAL_RECT  c3

D2D_PS_ENTRY(main)
{
    float2 p = D2DGetScenePosition().xy;
    float4 cur = D2DGetInput(0);
    float2 rv = SA_DEC2(D2DSampleInputAtPosition(1, saClampToRect(p * RADIAL_SCALE, RADIAL_RECT)).xy);
    float4 up = D2DSampleInputAtPosition(0, saClampToRect(p - rv * HSTEP, RECT));
    float score = up.a - TIE;
    return score > cur.a ? float4(up.rgb, score) : cur;
}
