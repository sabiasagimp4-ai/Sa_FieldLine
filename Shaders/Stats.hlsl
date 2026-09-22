// 正規化用。二乗とカバレッジを出し、これを Scale(0.5) の連鎖で
// 1x1 まで潰すと画面全体の RMS が得られる。
// 局所ぼかしで正規化してはいけない（平坦な領域ほど分母が小さくなり、
// そこだけ効果が最大になって画面全体がぐにゃぐにゃになる）。
#define D2D_ENTRY main
#include <d2d1effecthelpers.hlsli>
#include "FieldLineCommon.hlsli"

#define MODE c0.x   // 0 = B チャンネル（mag / phi）、1 = RG の折込ベクトル（|v|）

D2D_PS_ENTRY(main)
{
    float4 s = D2DGetInput(0);
    float sq;
    if (MODE < 0.5)
    {
        sq = s.b * s.b;
    }
    else
    {
        float2 v = SA_DEC4(s.rg);
        sq = dot(v, v);
    }
    return float4(sq, 1.0, 0.0, 1.0);
}
