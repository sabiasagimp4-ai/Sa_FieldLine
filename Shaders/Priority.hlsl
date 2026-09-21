// P7a: 引き伸ばしで「どの色を優先して運ぶか」。この後のぼかし σ がストロークの太さになる。
#define D2D_ENTRY main
#include <d2d1effecthelpers.hlsli>
#include "FieldLineCommon.hlsli"

D2D_PS_ENTRY(main)
{
    float conf = D2DGetInput(0).b;
    return float4(pow(max(conf, 0.0), 1.2), 0.0, 0.0, 1.0);
}
