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
    // .a は空いていたので、輪郭の「強さ」を conf で重み付けして載せておく。
    // 引き伸ばしの優先度が「この輪郭の強さ」を必要とする（conf は飽和して使えない）。
    // このテクスチャは拡散側でもぼかされるが、.a は誰も読まないので害はない。
    //
    // 1/4 に縮めて [0,1] に収めるのは、中間バッファが 8bit しか取れない環境でも
    // 強い輪郭どうしの差が潰れないようにするため（magN は実測で 1.5 程度まで伸びる）。
    // 優先度は「画面平均との比」で使うので、この 1/4 は約分されて消える。
    return float4(SA_ENC2(conf * n), conf, saturate(magN * 0.25) * conf);
}
