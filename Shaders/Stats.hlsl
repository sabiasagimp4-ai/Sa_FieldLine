// 正規化用。B チャンネルの二乗とカバレッジを出し、これを Scale(0.5) の連鎖で
// 1x1 まで潰すと画面全体の RMS が得られる。
// 局所ぼかしで正規化してはいけない（平坦な領域ほど分母が小さくなり、
// そこだけ効果が最大になって画面全体がぐにゃぐにゃになる）。
#define D2D_ENTRY main
#include <d2d1effecthelpers.hlsli>
#include "FieldLineCommon.hlsli"

D2D_PS_ENTRY(main)
{
    float v = D2DGetInput(0).b;
    return float4(v * v, 1.0, 0.0, 1.0);
}
