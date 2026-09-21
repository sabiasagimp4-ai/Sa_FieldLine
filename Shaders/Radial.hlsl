// P5a: 引き伸ばし専用の場。φ の勾配の逆＝輪郭から外向きの放射。
//
// 変位の場をそのまま使ってはいけない。Swirl が掛かっていると流線が輪郭と平行に走り、
// さかのぼっても輪郭の色に辿り着けない。変位が磁力線でも引き伸ばしは放射、という併用が要る。
#define D2D_ENTRY main
#include <d2d1effecthelpers.hlsli>
#include "FieldLineCommon.hlsli"

#define GRAD_STEP c0.x   // 勾配を取る間隔 [texel]
#define SWIRL     c0.y   // 放射をひねる量
#define RECT      c2

D2D_PS_ENTRY(main)
{
    float2 p = D2DGetScenePosition().xy;
    float r = max(GRAD_STEP, 1.0);
    float gx = D2DSampleInputAtPosition(0, saClampToRect(p + float2(r, 0.0), RECT)).g
             - D2DSampleInputAtPosition(0, saClampToRect(p - float2(r, 0.0), RECT)).g;
    float gy = D2DSampleInputAtPosition(0, saClampToRect(p + float2(0.0, r), RECT)).g
             - D2DSampleInputAtPosition(0, saClampToRect(p - float2(0.0, r), RECT)).g;

    float2 v = -float2(gx, gy);
    if (abs(SWIRL) > 1e-4)
        v = saRotate(v, SWIRL * (PI * 0.5));

    float m = length(v);
    return float4(SA_ENC2(m > 1e-8 ? v / m : float2(0.0, 0.0)), 0.0, 1.0);
}
