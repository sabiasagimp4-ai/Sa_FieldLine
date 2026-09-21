// P4b: 流線を追うのに必要な量だけを 1 枚にまとめる。
//   RG = 進行方向（単位ベクトル） / B = 歩幅ゲート / A = curl
// 変位パスは 1 ステップにつきこのテクスチャを 1 回読むだけで済む。
#define D2D_ENTRY main
#include <d2d1effecthelpers.hlsli>
#include "FieldLineCommon.hlsli"

#define CURL_STEP c0.x   // curl を取る間隔 [texel]
#define CURL_GAIN c0.y   // cs = max(1.5, radius*0.05) / 場の分母
#define RECT      c2

D2D_PS_ENTRY(main)
{
    float2 p = D2DGetScenePosition().xy;
    float2 v = SA_DEC4(D2DGetInput(0).rg);

    float ampRaw = length(v);
    float coh = saturate(ampRaw / K_COH);
    float2 dir = ampRaw > 1e-8 ? v / ampRaw : float2(1.0, 0.0);

    // 流線が「どれだけ進むか」。打ち消し合う点で暴れないように抑えるだけで、
    // 効果の強さ（amp）とは別に持つ。ここを混ぜると輪郭から離れた所で止まってしまう。
    float flow = 0.30 + 0.70 * sqrt(coh);

    // curl: 場同士の干渉によるねじれ。ノイズではなくこれで曲げるのがこのエフェクトの肝。
    float r = max(CURL_STEP, 1.0);
    float vyp = D2DSampleInputAtPosition(0, saClampToRect(p + float2(r, 0.0), RECT)).g;
    float vym = D2DSampleInputAtPosition(0, saClampToRect(p - float2(r, 0.0), RECT)).g;
    float vxp = D2DSampleInputAtPosition(0, saClampToRect(p + float2(0.0, r), RECT)).r;
    float vxm = D2DSampleInputAtPosition(0, saClampToRect(p - float2(0.0, r), RECT)).r;
    float curl = ((vyp - vym) - (vxp - vxm)) * 4.0 / (2.0 * r);   // *4 は SA_DEC4 の傾き
    curl = clamp(curl * (CURL_GAIN / K_CURL), -3.0, 3.0);

    return float4(SA_ENC2(dir), flow, SA_ENC6(curl));
}
