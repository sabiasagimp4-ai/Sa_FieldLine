// P0: 輝度。プリマルチプライ済みの色をそのまま使うので、
// 切り抜き素材ではシルエットがそのまま強い輪郭になる。
#define D2D_ENTRY main
#include <d2d1effecthelpers.hlsli>
#include "FieldLineCommon.hlsli"

D2D_PS_ENTRY(main)
{
    float4 s = D2DGetInput(0);
    float l = dot(s.rgb, float3(0.2126, 0.7152, 0.0722));
    return float4(l, 0.0, 0.0, 1.0);
}
