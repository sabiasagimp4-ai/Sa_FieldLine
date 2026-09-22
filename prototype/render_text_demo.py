#!/usr/bin/env python3
"""文字に掛けたときの検証（仕様の「文字の周囲に磁力線のような構造ができる」）。

    python3 render_text_demo.py <outdir>
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fieldline as fl  # noqa: E402
import gpu_sim as gs  # noqa: E402

JP_FONT = "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"


def make_text(w=900, h=506):
    im = Image.new("RGB", (w, h), (8, 10, 16))
    d = ImageDraw.Draw(im)
    for y in range(h):  # うっすら背景グラデ
        d.line([(0, y), (w, y)], fill=(8 + y * 12 // h, 10 + y * 14 // h, 16 + y * 26 // h))
    f1 = ImageFont.truetype(JP_FONT, 150)
    f2 = ImageFont.truetype(JP_FONT, 44)
    d.text((w // 2, h // 2 - 30), "力線", font=f1, fill=(255, 250, 235), anchor="mm")
    d.text((w // 2, h // 2 + 80), "Sa_FieldLine", font=f2, fill=(180, 220, 255), anchor="mm")
    return np.asarray(im, np.float32) / 255.0


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    img = make_text()
    Image.fromarray((img * 255).astype(np.uint8)).save(f"{outdir}/20_text_original.png")

    # 文字は線が細いので、変位を強くすると字そのものが潰れる。
    # 「字は残して、周囲に力線を出す」のが狙いなので strength は小さめにする。
    cases = [
        ("21_text_magnetic", dict(strength=0.12, radius=150, flow_length=180, swirl=1.0,
                                  curvature=1.0, smoothness=0.35, edge_threshold=0.08,
                                  detail_scale=0.4, line_draw=0.6, line_grain=1.6,
                                  line_density=1.1, glow=0.7)),
        ("22_text_electric", dict(strength=0.10, radius=180, flow_length=190, attract=-0.9,
                                  curvature=1.0, smoothness=0.45, edge_threshold=0.10,
                                  detail_scale=0.4, line_draw=0.65, line_grain=1.7,
                                  line_density=1.1, glow=0.8)),
        ("23_text_flow", dict(strength=0.6, radius=140, flow_length=140, curvature=2.5,
                              smoothness=0.30, edge_threshold=0.08, detail_scale=0.5,
                              glow=0.5, chroma=0.7, preserve_original=0.1)),
    ]
    for name, kw in cases:
        out, _ = fl.render(img, fl.Params(**kw))
        Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)).save(f"{outdir}/{name}.png")
        print("saved", name, flush=True)

    # 引き伸ばしは **プラグインと同じ演算だけ** のパイプラインで描く。
    #
    # 「近さを優先」を 0 にすると、どの流線も「流線の長さ」いっぱいまで届くので、
    # 塗った範囲が被写体を中心にした円盤になり、放射の束＝集中線になる。
    # 上げると弱い輪郭ほど手前で止まり、文字の形に沿った厚みとして残る。
    # 「筆の毛」で流線ごとの長さをばらつかせると、縁が円弧ではなくなる。
    pulls = [
        ("25_text_pull", dict(strength=0.0, radius=150, flow_length=170, edge_threshold=0.25,
                              detail_scale=0.30, smoothness=0.40, step_px=0.9,
                              stretch=1.0, stretch_gate=0.60, stretch_pick=4.0,
                              stretch_decay=0.75, stretch_jitter=0.55, stretch_swirl=0.2)),
        ("26_text_pull_lines", dict(strength=0.06, radius=150, flow_length=170, swirl=1.0,
                                    curvature=1.0, edge_threshold=0.25, detail_scale=0.30,
                                    smoothness=0.40, step_px=0.9, line_draw=0.55, line_grain=1.6,
                                    line_density=1.1,
                                    stretch=1.0, stretch_gate=0.60, stretch_pick=4.0,
                                    stretch_decay=0.75, stretch_jitter=0.55, stretch_swirl=0.2)),
    ]
    for name, kw in pulls:
        out, _ = gs.render(img, gs.GpuParams(**kw))
        Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)).save(f"{outdir}/{name}.png")
        print("saved", name, flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
