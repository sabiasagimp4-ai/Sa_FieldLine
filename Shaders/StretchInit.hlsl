// P7b: 伝播の初期値。輪郭ちょうどは線画の色なので、上流（面の側）から色を拾う。
//
// 固定距離で拾ってはいけない。conf は輪郭のスケールぶん太い帯になるので、
// 帯の外縁にいる画素は数 px 上流を見ても**背景のまま**で、
// 「背景色を運ぶ強い種」になって本来の輪郭色を塞ぐ。帯が眠くなる原因はこれ。
//
// 代わりに φ（輪郭密度）の尾根まで登り、**登り切った所の色**を拾う。
// すでに尾根にいる画素（＝構造の内側）は自分の色のままになるので、
// 文字や線画の面が背景色で塗り潰されない。
//
// 色はここで**ストレートに戻して**運ぶ。プリマルチプライのまま運ぶと、
// 半透明の縁から拾った色がそのぶん暗くなり、不透明で塗る帯が濁る。
//
// 入力 0 = 変位後の色 / 1 = 放射場（縮小） / 2 = 優先度 / 3 = FieldB（G = φ）
#define D2D_ENTRY main
#include <d2d1effecthelpers.hlsli>
#include "FieldLineCommon.hlsli"

#define PICK         c0.x   // 上流を探す最大距離 [px]
#define FIELD_SCALE  c0.y   // 等倍座標 -> 場の座標
#define RECT         c2
#define FIELD_RECT   c3

D2D_PS_ENTRY(main)
{
    float2 p = D2DGetScenePosition().xy;
    float2 rv = SA_DEC2(D2DSampleInputAtPosition(1, saClampToRect(p * FIELD_SCALE, FIELD_RECT)).xy);
    float prio = D2DGetInput(2).r;

    float4 own = D2DSampleInputAtPosition(0, saClampToRect(p, RECT));
    float phi0 = D2DSampleInputAtPosition(3, saClampToRect(p * FIELD_SCALE, FIELD_RECT)).g;

    // argmax で 1 点を選ぶと、隣接画素で選ばれる点が切り替わって細かい縞が出る。
    // 「自分より φ が高いぶん」で重み付けした平均にすれば空間的に滑らかになり、
    // なおかつ尾根の色が支配的になる。登り先が無ければ自分の色のまま。
    float3 acc = (own.a > 1e-4 ? own.rgb / own.a : own.rgb) * PICK_OWN;
    float wsum = PICK_OWN;

    [unroll] for (int i = 1; i <= 4; ++i)
    {
        float2 q = p - rv * (PICK * (float)i * 0.25);
        float phi = D2DSampleInputAtPosition(3, saClampToRect(q * FIELD_SCALE, FIELD_RECT)).g;
        float w = saturate((phi - phi0) * PICK_GAIN);
        w *= w;
        float4 c = D2DSampleInputAtPosition(0, saClampToRect(q, RECT));
        acc += (c.a > 1e-4 ? c.rgb / c.a : c.rgb) * w;
        wsum += w;
    }

    return float4(acc / wsum, prio);
}
