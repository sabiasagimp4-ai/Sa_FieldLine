// P4c: 効果の「掛かり具合」。
//   R = amp（距離減衰込み、res 済み） / G = phi / B = res
// 入力 0 = 平滑化後の方向場、入力 1 = Spread、入力 2 = phi の全画面 RMS。
#define D2D_ENTRY main
#include <d2d1effecthelpers.hlsli>
#include "FieldLineCommon.hlsli"

#define TURB_STEP c0.x   // 方向場の回り方を測る間隔 [texel]
#define TURB_GAIN c0.y   // ts / FIELD_DIV
#define FALLOFF   c0.z
#define AMP_GAMMA c0.w
#define RECT      c2

// D2D のサンプリングヘルパはエントリポイントのローカルに展開されうるので、
// 自前の関数ではなくマクロで書く。
#define SA_DIR(q, dst) { \
    float2 dv = SA_DEC4(D2DSampleInputAtPosition(0, saClampToRect(q, RECT)).rg); \
    float dm = length(dv); \
    dst = dm > 1e-8 ? dv / dm : float2(1.0, 0.0); }

D2D_PS_ENTRY(main)
{
    float2 p = D2DGetScenePosition().xy;
    float ampRaw = length(SA_DEC4(D2DGetInput(0).rg));
    float coh = saturate(ampRaw / K_COH);

    float phiScale = max(K_PHI * saRms(D2DGetInput(2)), 1e-4);
    float phiN = saturate(D2DGetInput(1).b / phiScale);

    // 輪郭からの距離減衰
    float env = pow(phiN, 0.35 + 1.3 * FALLOFF);
    float amp = pow((0.10 + 0.90 * env) * (0.35 + 0.65 * coh), AMP_GAMMA);

    // 方向場が速く回りすぎる所では流線も力線も解像できない（＝ガサつく）ので抑える
    float r = max(TURB_STEP, 1.0);
    float2 dxp, dxm, dyp, dym;
    SA_DIR(p + float2(r, 0.0), dxp)
    SA_DIR(p - float2(r, 0.0), dxm)
    SA_DIR(p + float2(0.0, r), dyp)
    SA_DIR(p - float2(0.0, r), dym)
    float inv = 1.0 / (2.0 * r);
    float turb = (length(float2(dxp.x - dxm.x, dyp.x - dym.x))
                + length(float2(dxp.y - dxm.y, dyp.y - dym.y))) * inv;
    turb *= TURB_GAIN / K_TURB;
    float res = 1.0 / (1.0 + (0.85 * turb) * (0.85 * turb));

    return float4(amp * (0.55 + 0.45 * res), phiN, res, 1.0);
}
