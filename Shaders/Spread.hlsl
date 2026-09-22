// P3: 重み ∝ σ のガウスを重ねて ≈1/r の長距離カーネルを作る。
// 入力 0 が最小 σ、入力 5 が最大 σ（= Radius）。
// 法線は符号付きなので、向かい合う輪郭はここで打ち消し合う＝干渉が起きる。
#define D2D_ENTRY main
#include <d2d1effecthelpers.hlsli>
#include "FieldLineCommon.hlsli"

#define W0123 c0
#define W45   c1.xy

D2D_PS_ENTRY(main)
{
    float4 acc = W0123.x * D2DGetInput(0)
               + W0123.y * D2DGetInput(1)
               + W0123.z * D2DGetInput(2)
               + W0123.w * D2DGetInput(3)
               + W45.x   * D2DGetInput(4)
               + W45.y   * D2DGetInput(5);
    float wsum = max(W0123.x + W0123.y + W0123.z + W0123.w + W45.x + W45.y, 1e-6);
    // RG は折り込んだままでよい。重み和 1 の平均はアフィン変換と可換なので、
    // ここで復号しなくても「折り込まれた拡散結果」になっている。
    return float4(acc.rgb / wsum, 1.0);
}
