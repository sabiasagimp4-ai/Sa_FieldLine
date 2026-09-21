// P7d: 輪郭を掴めた画素は完全不透明で塗り替える。掴めなかった画素だけ元のまま。
// 減衰も距離ブレンドも掛けない。
#define D2D_ENTRY main
#include <d2d1effecthelpers.hlsli>
#include "FieldLineCommon.hlsli"

#define GATE   c0.x
#define AMOUNT c0.y

D2D_PS_ENTRY(main)
{
    float4 base = D2DGetInput(0);
    float4 st = D2DGetInput(1);
    float k = st.a >= GATE ? AMOUNT : 0.0;
    return float4(lerp(base.rgb, st.rgb, k), lerp(base.a, 1.0, k));
}
