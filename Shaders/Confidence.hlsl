// P2: エッジ強度を正規化して閾値を掛け、法線に信頼度を乗せる。
// 入力 0 = Edge、入力 1 = Edge の全画面 RMS（定数テクスチャ）。
#define D2D_ENTRY main
#include <d2d1effecthelpers.hlsli>
#include "FieldLineCommon.hlsli"

#define THRESHOLD c0.x

D2D_PS_ENTRY(main)
{
    float4 e = D2DGetInput(0);
    float scale = max(K_MAG * saRms(D2DGetInput(1)), 1e-3);
    float magN = e.b / scale;

    float knee = 0.06 + 0.35 * (1.0 - THRESHOLD);
    float conf = smoothstep(THRESHOLD, THRESHOLD + knee, magN);

    float2 n = SA_DEC2(e.rg);
    return float4(SA_ENC2(conf * n), conf, 1.0);
}
