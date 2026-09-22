// P7a: 引き伸ばしで「どの色を優先して運ぶか」。この後のぼかし σ がストロークの太さになる。
//
// conf をそのまま優先度にしてはいけない。conf はソフト閾値なので膝を超えた輪郭は
// すべて 1.0 に飽和し、どの輪郭も同点になる。同点だと距離ペナルティで必ず
// 一番近い＝一番外側の輪郭が勝ち、内側の輪郭の色は一歩も外へ出られない
// （内側を画面で一番強い輪郭にしても 1px も出ないことを実測した）。
//
// そこで輪郭の「強さ」を優先度に残す。ただし画素ごとの強さのまま競わせると、
// 隣り合う画素が別の輪郭に当たって櫛状の縞が戻るので、輪郭の帯の幅ぶんだけ
// conf を重みにした平均を取り、「この輪郭の強さ」にしてから使う。
// 単純に平滑化すると帯の山が削れて塗る範囲まで痩せるが、重み付き平均なら山は残る。
//
// 入力 0 = Confidence（.b = conf / .a = 強さ x conf）
//      1 = それを帯の幅でぼかしたもの
//      2 = 同じものを 1x1 まで潰した全画面平均
#define D2D_ENTRY main
#include <d2d1effecthelpers.hlsli>
#include "FieldLineCommon.hlsli"

#define JITTER c0.x   // 筆の毛。優先度をばらつかせて毛先を不揃いにする
#define CELL   c0.y   // 毛の粒 [px]

D2D_PS_ENTRY(main)
{
    float4 c = D2DGetInput(0);
    float4 b = D2DGetInput(1);
    float4 g = D2DGetInput(2);

    float region = b.a / max(b.b, 1e-4);
    float mean = g.a / max(g.b, 1e-4);
    // 強さは絶対値ではなく画面平均との比で持つ。絶対値だと正規化の係数がずれた素材で
    // 強さが丸ごと上下し、届く距離まで変わってしまう。
    float st = region / max(mean, 1e-4);

    float prio = pow(max(c.b, 0.0), 1.2) * (1.0 - PRIO_W + PRIO_W * saturate(st * PRIO_K));

    if (JITTER > 1e-4)
    {
        // 届く距離は優先度で決まるので、優先度をばらつかせると毛先が不揃いになる。
        float2 p = D2DGetScenePosition().xy;
        prio *= 1.0 - JITTER * saValueNoise(p / max(CELL, 1.0));
    }

    return float4(prio, 0.0, 0.0, 1.0);
}
