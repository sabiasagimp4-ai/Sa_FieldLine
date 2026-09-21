// Sa_FieldLine の全シェーダが共有する定数と小道具。
//
// 定数バッファは float4 x 6 で固定し、シェーダごとに #define で名前を付ける。
// C# 側 (Effects/FieldLinePass.cs) は常に同じ 6 本を送るので、
// パスを足しても C# の定型コードは増えない。

#ifndef SA_FIELDLINE_COMMON
#define SA_FIELDLINE_COMMON

// 明示的な cbuffer にしておく。ばらの global 変数だと、使っていない定数が
// 最適化で落ちた時に $Globals の並びがずれる可能性がある。
// C# 側の Constants 構造体（float4 x 6 = 96 バイト）と 1:1 で対応する。
cbuffer FieldLineConstants
{
    float4 c0;
    float4 c1;
    float4 c2;
    float4 c3;
    float4 c4;
    float4 c5;
};

static const float PI = 3.14159265358979323846;

// 正規化係数。prototype/gpu_sim.py の K_* と一致させること。
// リファレンス実装 (fieldline.py) の percentile 正規化を、
// 画面全体の RMS（1x1 まで縮小して求める）へ置き換えるための倍率。
static const float K_MAG  = 3.50;
static const float K_PHI  = 1.95;
static const float K_COH  = 0.95;
static const float K_CURL = 0.014;
static const float K_TURB = 0.08;
static const float K_GRAD = 0.30;

// 符号つきの値を [0,1] に折り込む。中間バッファが 8bit しか取れない環境でも
// 法線や curl が潰れないようにするための保険で、アフィン変換なので
// ガウスぼかしや箱平均（どちらも重み和が 1 の平均）を通しても壊れない。
#define SA_ENC2(v) (0.5 + 0.5 * (v))
#define SA_DEC2(v) ((v) * 2.0 - 1.0)
#define SA_ENC4(v) (0.5 + 0.25 * (v))
#define SA_DEC4(v) (((v) - 0.5) * 4.0)
#define SA_ENC6(v) (0.5 + (v) * (1.0 / 6.0))
#define SA_DEC6(v) (((v) - 0.5) * 6.0)

float2 saRotate(float2 v, float angle)
{
    float s, c;
    sincos(angle, s, c);
    return float2(v.x * c - v.y * s, v.x * s + v.y * c);
}

// 矩形の内側（画素中心）へ寄せる。境界の外は透明なので、そのまま読むと暗くなる。
float2 saClampToRect(float2 p, float4 rect)
{
    float2 lo = rect.xy + min(0.5, (rect.zw - rect.xy) * 0.5);
    float2 hi = max(lo, rect.zw - 0.5);
    return clamp(p, lo, hi);
}

// (x^2, 1) を 1x1 まで縮小したテクスチャから RMS を復元する。
float saRms(float4 stats)
{
    return sqrt(max(stats.r / max(stats.g, 1e-4), 0.0));
}

#endif
