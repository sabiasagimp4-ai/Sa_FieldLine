// P6: 流線を積分して変位サンプリングする。1 ステップにつき FieldA を 1 回読むだけ。
// 入力 0 = 元画像（等倍） / 1 = FieldA（縮小） / 2 = FieldB（縮小）
#define D2D_ENTRY main
#include <d2d1effecthelpers.hlsli>
#include "FieldLineCommon.hlsli"

#define STEP_G      c0.x
#define HSTEP       c0.y
#define ALIGN       c0.z
#define CURVATURE   c0.w
#define STRENGTH    c1.x
#define CHROMA      c1.y
#define SHADE       c1.z
#define RECT        c2
#define FIELD_RECT  c3
#define FIELD_SCALE c4.x
#define STEP_R      c4.y
#define STEP_B      c4.z

D2D_PS_ENTRY(main)
{
    float2 p = D2DGetScenePosition().xy;

    // 引き伸ばしだけを使う場合、変位は 0 なので流線を追う必要がない。
    if (STRENGTH < 1e-5 && abs(SHADE) < 1e-5)
        return D2DSampleInputAtPosition(0, saClampToRect(p, RECT));

    float2 fp = saClampToRect(p * FIELD_SCALE, FIELD_RECT);
    float ampEff = D2DSampleInputAtPosition(2, fp).r;
    float k = STRENGTH * ampEff;

    int nG = (int)STEP_G;
    int nR = (int)STEP_R;
    int nB = (int)STEP_B;
    int nMax = max(nR, nG);

    float2 cur = p;
    float2 d = -SA_DEC2(D2DSampleInputAtPosition(1, fp).xy);
    float2 pG = p, pR = p, pB = p;

    [loop] for (int i = 0; i < nMax; ++i)
    {
        float4 a = D2DSampleInputAtPosition(1, saClampToRect(cur * FIELD_SCALE, FIELD_RECT));
        float2 f = -SA_DEC2(a.xy);
        // 場が弱いところで向きが暴れないよう、進行方向側の半球へ揃える。
        // これを入れないと場の零線で流線が折り返して破綻する。
        if (dot(f, d) < 0.0)
            f = -f;
        float ang = atan2(d.x * f.y - d.y * f.x, dot(d, f));
        float turn = ALIGN * ang + CURVATURE * SA_DEC6(a.w) * HSTEP * 0.09;
        d = saRotate(d, turn);
        float dl = length(d);
        d = dl > 1e-8 ? d / dl : float2(1.0, 0.0);
        cur += d * (HSTEP * a.z);

        int done = i + 1;
        if (done == nB) pB = cur;
        if (done == nG) pG = cur;
        if (done == nR) pR = cur;
    }

    float2 sg = p + (pG - p) * k;
    float4 col = D2DSampleInputAtPosition(0, saClampToRect(sg, RECT));

    if (CHROMA > 1e-4)
    {
        float2 sr = p + (pR - p) * k;
        float2 sb = p + (pB - p) * k;
        col.r = D2DSampleInputAtPosition(0, saClampToRect(sr, RECT)).r;
        col.b = D2DSampleInputAtPosition(0, saClampToRect(sb, RECT)).b;
    }

    if (abs(SHADE) > 1e-4)
    {
        float a2 = D2DSampleInputAtPosition(2, saClampToRect(sg * FIELD_SCALE, FIELD_RECT)).r;
        col.rgb *= max(1.0 + SHADE * 1.2 * (a2 - ampEff), 0.0);
    }

    return col;
}
