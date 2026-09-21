// P7b: 伝播の初期値。輪郭ちょうどは線画の色なので、少し上流（面の側）から色を拾う。
// 入力 0 = 変位後の色 / 1 = 放射場（縮小） / 2 = 優先度
//
// a に入れるのは「優先度 - tie * 伝播距離」というスコア。
// 比較にはこの 1 本だけあればよいので、距離を別バッファで運ぶ必要がない。
#define D2D_ENTRY main
#include <d2d1effecthelpers.hlsli>
#include "FieldLineCommon.hlsli"

#define PICK         c0.x   // 色を拾う位置 [px]
#define RADIAL_SCALE c0.y   // 等倍座標 -> 場の座標
#define RECT         c2
#define RADIAL_RECT  c3

D2D_PS_ENTRY(main)
{
    float2 p = D2DGetScenePosition().xy;
    float2 rv = SA_DEC2(D2DSampleInputAtPosition(1, saClampToRect(p * RADIAL_SCALE, RADIAL_RECT)).xy);
    float prio = D2DGetInput(2).r;
    float3 col = D2DSampleInputAtPosition(0, saClampToRect(p - rv * PICK, RECT)).rgb;
    return float4(col, prio);
}
