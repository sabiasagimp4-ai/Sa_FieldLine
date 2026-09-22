// P4a: 拡散した法線を正規化し、引力/反発と Swirl を掛ける。平滑化はこの後のぼかしで行う。
// 入力 0 = Spread (RG=V, B=phi)、入力 1 = phi の全画面 RMS。
#define D2D_ENTRY main
#include <d2d1effecthelpers.hlsli>
#include "FieldLineCommon.hlsli"

#define ATTRACT   c0.x
#define SWIRL     c0.y
#define GRAD_STEP c0.z     // phi の勾配を取る間隔 [texel]
#define GRAD_GAIN c0.w     // gs（= max(radius*0.16, 2.5) / 場の分母）
#define RECT      c2

D2D_PS_ENTRY(main)
{
    float4 s = D2DGetInput(0);
    float phiScale = max(K_PHI * saRms(D2DGetInput(1)), 1e-4);
    float2 v = SA_DEC2(s.rg) / phiScale;

    if (abs(ATTRACT) > 1e-4)
    {
        float2 p = D2DGetScenePosition().xy;
        float r = max(GRAD_STEP, 1.0);
        float gx = D2DSampleInputAtPosition(0, saClampToRect(p + float2(r, 0.0), RECT)).b
                 - D2DSampleInputAtPosition(0, saClampToRect(p - float2(r, 0.0), RECT)).b;
        float gy = D2DSampleInputAtPosition(0, saClampToRect(p + float2(0.0, r), RECT)).b
                 - D2DSampleInputAtPosition(0, saClampToRect(p - float2(0.0, r), RECT)).b;
        float2 grad = float2(gx, gy) / (2.0 * r);
        v += ATTRACT * grad * (GRAD_GAIN / (phiScale * K_GRAD));
    }

    if (abs(SWIRL) > 1e-4)
        v = saRotate(v, SWIRL * (PI * 0.5));

    return float4(SA_ENC4(clamp(v, -2.0, 2.0)), 0.0, 1.0);
}
