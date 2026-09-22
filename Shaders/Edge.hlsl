// P1: 多重スケールのガウス微分。入力 0..4 は σ, 2σ, 4σ, 8σ, 16σ でぼかした輝度。
// Lindeberg の γ 正規化 (σ を掛ける) を入れないと、粗いスケールが不当に弱くなる。
#define D2D_ENTRY main
#include <d2d1effecthelpers.hlsli>
#include "FieldLineCommon.hlsli"

#define WEIGHTS   c0        // detail_scale から作ったオクターブ重み w0..w3
#define WEIGHT4   c1.x
#define BASE_SIGMA c1.y
#define RECT      c2

#define SA_OCTAVE(IDX, WI, SI) { \
    float xp = D2DSampleInputAtPosition(IDX, saClampToRect(p + float2(1.0, 0.0), RECT)).r; \
    float xm = D2DSampleInputAtPosition(IDX, saClampToRect(p - float2(1.0, 0.0), RECT)).r; \
    float yp = D2DSampleInputAtPosition(IDX, saClampToRect(p + float2(0.0, 1.0), RECT)).r; \
    float ym = D2DSampleInputAtPosition(IDX, saClampToRect(p - float2(0.0, 1.0), RECT)).r; \
    float2 e = float2(xp - xm, yp - ym) * (0.5 * (SI)); \
    g += (WI) * e; \
    m += (WI) * length(e); }

D2D_PS_ENTRY(main)
{
    float2 p = D2DGetScenePosition().xy;
    float2 g = float2(0.0, 0.0);
    float m = 0.0;

    SA_OCTAVE(0, WEIGHTS.x, BASE_SIGMA)
    SA_OCTAVE(1, WEIGHTS.y, BASE_SIGMA * 2.0)
    SA_OCTAVE(2, WEIGHTS.z, BASE_SIGMA * 4.0)
    SA_OCTAVE(3, WEIGHTS.w, BASE_SIGMA * 8.0)
    SA_OCTAVE(4, WEIGHT4,   BASE_SIGMA * 16.0)

    // 法線の向きしか使わないので、ここで単位ベクトルにしてから折り込む。
    float len = length(g);
    float2 n = len > 1e-8 ? g / len : float2(0.0, 0.0);
    return float4(SA_ENC2(n), m, 1.0);
}
