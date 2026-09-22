// P8: 発展要素（発光 / 力線描画 / 元画像を残す）と最終クランプ。
// 入力 0 = ここまでの色 / 1 = FieldA（縮小） / 2 = FieldB（縮小） / 3 = 元画像
//
// D2D のサンプリングヘルパはエントリポイントのローカル（走査座標）に展開されうるので、
// 自前の関数の中からは呼ばない。流線をたどる部分はマクロで展開する。
#define D2D_ENTRY main
#include <d2d1effecthelpers.hlsli>
#include "FieldLineCommon.hlsli"

#define GLOW         c0.x
#define LINE_DRAW    c0.y
#define LINE_DENSITY c0.z
#define LINE_GRAIN   c0.w
#define LINE_SEED    c1.x
#define PRESERVE     c1.y
#define ALIGN        c1.z
#define CURVATURE    c1.w
#define RECT         c2
#define FIELD_RECT   c3
#define FIELD_SCALE  c4.x
#define GLOW_STEPS   c4.y
#define GLOW_HSTEP   c4.z
#define LINE_STEPS   c4.w
#define LINE_HSTEP   c5.x
#define LINE_LENGTH  c5.y

// ノイズを輪郭の近くへ寄せて撒くと、砂鉄のように「輪郭から生えて遠くで疎になる」線になる。
float saLineNoise(float2 q, float phiN, float grain, float seedEdge)
{
    float cell = max(grain, 0.6);
    float z = (saValueNoise(q / cell) - 0.5) / 0.19;   // 値ノイズの標準偏差 ~0.19
    float seed = pow(saturate(phiN), 0.7);
    z *= (1.0 - seedEdge) + seedEdge * (0.25 + 0.75 * seed);
    return z * 0.5 + 0.5;
}

#define SA_HIGHLIGHT(q, dst) { \
    float4 hc = D2DSampleInputAtPosition(0, saClampToRect(q, RECT)); \
    float hl = dot(hc.rgb, float3(0.2126, 0.7152, 0.0722)); \
    dst = saturate((hl - 0.55) / 0.45) * hc.rgb; }

#define SA_PHI(q, dst) \
    dst = D2DSampleInputAtPosition(2, saClampToRect((q) * FIELD_SCALE, FIELD_RECT)).g;

// 流線に沿って payload を平均する。MODE 0 = 発光（明部を集める）、1 = 力線（LIC）。
// OUT_LEN には実際に歩いた距離が入る。歩幅は場の強さでゲートされるので、
// 公称の長さとは大きく変わる。LIC の正規化にはこちらを使う。
#define SA_WALK(SGN, N, HSTEP, MODE, OUT_RGB, OUT_LIC, OUT_LEN) { \
    float2 wd = (SGN) * SA_DEC2(D2DSampleInputAtPosition(1, saClampToRect(p * FIELD_SCALE, FIELD_RECT)).xy); \
    float2 wp = p; \
    float3 wacc = float3(0.0, 0.0, 0.0); \
    float wlic = 0.0; \
    float wsum = 1.0; \
    float wlen = 0.0; \
    if ((MODE) == 0) { float3 h0 = float3(0.0, 0.0, 0.0); SA_HIGHLIGHT(p, h0) wacc = h0; } \
    else { float p0 = 0.0; SA_PHI(p, p0) wlic = saLineNoise(p, p0, LINE_GRAIN, LINE_SEED); } \
    [loop] for (int wi = 0; wi < (N); ++wi) { \
        float4 wa = D2DSampleInputAtPosition(1, saClampToRect(wp * FIELD_SCALE, FIELD_RECT)); \
        float2 wf = (SGN) * SA_DEC2(wa.xy); \
        if (dot(wf, wd) < 0.0) wf = -wf; \
        float wang = atan2(wd.x * wf.y - wd.y * wf.x, dot(wd, wf)); \
        wd = saRotate(wd, ALIGN * wang + CURVATURE * SA_DEC6(wa.w) * (HSTEP) * 0.09); \
        float wdl = length(wd); \
        wd = wdl > 1e-8 ? wd / wdl : float2(1.0, 0.0); \
        float wstep = (HSTEP) * wa.z; \
        wp += wd * wstep; \
        wlen += wstep; \
        float wt = (float)(wi + 1) / (float)(N); \
        float wg = 0.5 + 0.5 * cos(PI * wt); \
        if ((MODE) == 0) { float3 hs = float3(0.0, 0.0, 0.0); SA_HIGHLIGHT(wp, hs) wacc += hs * wg; } \
        else { float ps = 0.0; SA_PHI(wp, ps) wlic += saLineNoise(wp, ps, LINE_GRAIN, LINE_SEED) * wg; } \
        wsum += wg; } \
    OUT_RGB = wacc / wsum; \
    OUT_LIC = wlic / wsum; \
    OUT_LEN = wlen; }

D2D_PS_ENTRY(main)
{
    float2 p = D2DGetScenePosition().xy;
    float4 col = D2DGetInput(0);
    float2 ar = D2DSampleInputAtPosition(2, saClampToRect(p * FIELD_SCALE, FIELD_RECT)).rb;
    float amp = ar.x;
    float res = ar.y;

    if (GLOW > 1e-4)
    {
        int gn = max((int)GLOW_STEPS, 1);
        float3 gf = float3(0.0, 0.0, 0.0);
        float3 gb = float3(0.0, 0.0, 0.0);
        float unusedF = 0.0;
        float unusedB = 0.0;
        float unusedLF = 0.0;
        float unusedLB = 0.0;
        SA_WALK(-1.0, gn, GLOW_HSTEP, 0, gf, unusedF, unusedLF)
        SA_WALK( 1.0, gn, GLOW_HSTEP, 0, gb, unusedB, unusedLB)
        float3 g = 0.5 * (gf + gb) * (GLOW * 2.0 * amp);
        col.rgb = 1.0 - (1.0 - saturate(col.rgb)) * (1.0 - saturate(g));   // screen
    }

    if (LINE_DRAW > 1e-4)
    {
        int ln = max((int)LINE_STEPS, 1);
        float3 unusedC = float3(0.0, 0.0, 0.0);
        float3 unusedD = float3(0.0, 0.0, 0.0);
        float lf = 0.0;
        float lb = 0.0;
        float lenF = 0.0;
        float lenB = 0.0;
        SA_WALK(-1.0, ln, LINE_HSTEP, 1, unusedC, lf, lenF)
        SA_WALK( 1.0, ln, LINE_HSTEP, 1, unusedD, lb, lenB)
        float lic = 0.5 * (lf + lb);

        // 局所コントラスト正規化の代わりに、LIC の標準偏差を解析的に求めて割る。
        // 平均される有効本数 ~ 経路長 / ノイズの粒。
        // 公称の長さではなく**実際に歩いた距離**を使う。場が強くコヒーレントな所ほど
        // 長く歩き、平均される本数が増えて LIC の分散が下がるので、そこで線が薄くなる。
        float gEff = max(LINE_GRAIN, 0.6);
        float plen = 0.5 * (lenF + lenB);
        float sd = 0.5 * sqrt(gEff / max(plen, gEff)) + 0.030;
        // 0.36 は実測合わせ。リファレンスの局所正規化に対してコントラストが
        // 2 割ほど足りなかったぶんを埋める。
        float tex = saturate((lic - 0.5) / sd * 0.36 * LINE_DENSITY + 0.5);
        // 力線は解像できない所（場が速く回る所）を強く抑える
        float t = (tex - 0.5) * (LINE_DRAW * amp * res) * 1.7;
        float3 base = saturate(col.rgb);
        // soft light 風: 明部では明るく、暗部では暗く乗る
        col.rgb = max(base + t * (0.35 + 0.65 * (1.0 - abs(2.0 * base - 1.0))), 0.0);
    }

    if (PRESERVE > 1e-4)
        col = lerp(col, D2DGetInput(3), PRESERVE);

    col.rgb = clamp(col.rgb, 0.0, max(col.a, 0.0));
    return col;
}
