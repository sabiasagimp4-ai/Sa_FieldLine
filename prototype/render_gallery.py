#!/usr/bin/env python3
"""Sa_FieldLine プロトタイプのサンプル生成。

    python3 render_gallery.py <input.jpg> <outdir>
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fieldline as fl  # noqa: E402


# ------------------------------------------------------------------ presets
PRESETS: list[tuple[str, str, dict]] = [
    ("03_drift", "ドリフト（変位のみ・控えめ）", dict(
        strength=0.55, radius=150, flow_length=70, curvature=1.0,
        smoothness=0.35, edge_threshold=0.10, detail_scale=0.5)),

    ("04_flow", "フロー（変位のみ・強）", dict(
        strength=1.0, radius=150, flow_length=120, curvature=1.5,
        smoothness=0.30, edge_threshold=0.10, detail_scale=0.5)),

    ("05_magnetic", "磁力線（Swirl 1.0 / 輪郭に巻き付く）", dict(
        strength=0.5, radius=150, flow_length=160, swirl=1.0, curvature=1.0,
        smoothness=0.35, edge_threshold=0.10, detail_scale=0.5,
        line_draw=0.45, line_grain=1.6, line_density=1.0)),

    ("06_electric", "電気力線（Repel / 輪郭から放射）", dict(
        strength=0.45, radius=180, flow_length=170, attract=-0.9, curvature=1.0,
        smoothness=0.50, edge_threshold=0.13, detail_scale=0.40,
        line_draw=0.50, line_grain=1.8)),

    ("07_lines", "力線描画（強）", dict(
        strength=0.25, radius=160, flow_length=170, curvature=1.2,
        smoothness=0.45, edge_threshold=0.10, detail_scale=0.45,
        line_draw=0.75, line_grain=1.5, line_density=1.15)),

    ("08_lines_soft", "力線描画（実用・控えめ）", dict(
        strength=0.3, radius=170, flow_length=140, curvature=1.0,
        smoothness=0.65, edge_threshold=0.14, detail_scale=0.35,
        line_draw=0.32, line_grain=2.0, line_density=0.85, preserve_original=0.15)),

    ("09_glow", "発光（流線に沿って光が伸びる）", dict(
        strength=0.45, radius=150, flow_length=120, curvature=1.0,
        smoothness=0.40, edge_threshold=0.10, detail_scale=0.5,
        glow=0.9, streamer=0.5, streamer_split=0.8)),

    ("10_chroma", "色収差（流線方向に RGB がずれる）", dict(
        strength=0.8, radius=150, flow_length=110, curvature=1.2,
        smoothness=0.35, edge_threshold=0.10, detail_scale=0.5,
        chroma=1.0)),

    ("11_curl", "Curvature 4.0（干渉で大きく巻く）", dict(
        strength=0.9, radius=150, flow_length=150, curvature=4.0,
        smoothness=0.30, edge_threshold=0.10, detail_scale=0.5,
        line_draw=0.35, line_grain=1.6)),

    ("12_fine", "Detail Scale 1.0（細かい輪郭だけ）", dict(
        strength=0.8, radius=90, flow_length=90, curvature=1.2,
        smoothness=0.30, edge_threshold=0.08, detail_scale=1.0,
        line_draw=0.35, line_grain=1.3)),

    ("13_coarse", "Detail Scale 0.0（大きい輪郭だけ）", dict(
        strength=0.9, radius=200, flow_length=150, curvature=1.2,
        smoothness=0.40, edge_threshold=0.08, detail_scale=0.0,
        line_draw=0.35, line_grain=1.8)),

    ("15_stretch_soft", "引き伸ばし（控えめ）", dict(
        strength=0.0, radius=120, flow_length=90, curvature=1.0, swirl=1.0,
        smoothness=0.30, edge_threshold=0.08, detail_scale=0.55, falloff=0.0, step_px=1.5,
        stretch=0.7, stretch_mode="contrast", stretch_scale=12, stretch_drag=0.3,
        stretch_decay=3.0, stretch_jitter=0.6, stretch_jitter_scale=9)),

    ("16_stretch", "引き伸ばし（標準・帯のまま伸びる）", dict(
        strength=0.0, radius=120, flow_length=150, curvature=1.0, swirl=1.0,
        smoothness=0.30, edge_threshold=0.08, detail_scale=0.55, falloff=0.0, step_px=1.5,
        stretch=1.0, stretch_mode="contrast", stretch_scale=16, stretch_drag=0.3,
        stretch_decay=3.0, stretch_jitter=0.6, stretch_jitter_scale=9)),

    ("17_stretch_mosh", "引き伸ばし＋グリッチ（粗い歩幅・色収差・階調丸め）", dict(
        strength=0.0, radius=120, flow_length=150, curvature=1.0, swirl=1.0,
        smoothness=0.30, edge_threshold=0.08, detail_scale=0.55, falloff=0.0, step_px=7.0,
        stretch=1.0, stretch_mode="contrast", stretch_scale=16, stretch_drag=0.3,
        stretch_decay=2.0, stretch_jitter=0.5, stretch_jitter_scale=9,
        chroma=0.9, posterize=14)),

    ("18_pull_near", "端の色を引き伸ばす（近い / 元が残る）", dict(
        strength=0.0, radius=150, flow_length=60, curvature=1.0,
        smoothness=0.40, edge_threshold=0.25, detail_scale=0.30, step_px=1.25,
        stretch=1.0, stretch_mode="edge", stretch_radial=True,
        stretch_decay=0.0, stretch_gate=0.35, stretch_pick=3.0, bidirectional=False)),

    ("19_pull", "端の色を引き伸ばす（標準）", dict(
        strength=0.0, radius=150, flow_length=140, curvature=1.0,
        smoothness=0.40, edge_threshold=0.25, detail_scale=0.30, step_px=1.25,
        stretch=1.0, stretch_mode="edge", stretch_radial=True,
        stretch_decay=0.0, stretch_gate=0.35, stretch_pick=3.0, bidirectional=False)),

    ("20_pull_far", "端の色を引き伸ばす（遠い / ほぼ全面が塗り替わる）", dict(
        strength=0.0, radius=150, flow_length=280, curvature=1.0,
        smoothness=0.40, edge_threshold=0.25, detail_scale=0.30, step_px=1.25,
        stretch=1.0, stretch_mode="edge", stretch_radial=True,
        stretch_decay=0.0, stretch_gate=0.35, stretch_pick=3.0, bidirectional=False)),

    ("21_pull_magnetic", "放射の引き伸ばし ＋ 磁力線の変位（場を分離）", dict(
        strength=0.5, radius=150, flow_length=140, curvature=1.0, swirl=1.0,
        smoothness=0.40, edge_threshold=0.25, detail_scale=0.30, step_px=1.25,
        line_draw=0.35, line_grain=1.6,
        stretch=1.0, stretch_mode="edge", stretch_radial=True,
        stretch_decay=0.0, stretch_gate=0.35, stretch_pick=3.0, bidirectional=False)),

    ("14_preserve", "Preserve Original 0.5（強い設定を半分残す）", dict(
        strength=1.0, radius=160, flow_length=170, curvature=2.0, swirl=0.35,
        smoothness=0.35, edge_threshold=0.10, detail_scale=0.5,
        line_draw=0.6, glow=0.5, preserve_original=0.5)),
]


def save(path, arr):
    a = np.clip(arr, 0, 1)
    if a.ndim == 2:
        a = np.stack([a] * 3, -1)
    Image.fromarray((a * 255 + 0.5).astype(np.uint8)).save(path, quality=95)


def main(src: str, outdir: str):
    os.makedirs(outdir, exist_ok=True)
    img = np.asarray(Image.open(src).convert("RGB"), np.float32) / 255.0
    h, w = img.shape[:2]
    print(f"input {w}x{h}")

    save(f"{outdir}/00_original.png", img)

    # --- 中間結果（仕組みが見えるように） ---
    diag_p = fl.Params(radius=150, smoothness=0.35, edge_threshold=0.10,
                       detail_scale=0.5, flow_length=160)
    fs = fl.build_field(img, diag_p)
    save(f"{outdir}/01_edges.png", fs["mag_n"])
    save(f"{outdir}/02_field.png", fl.field_lines(fs, (h, w), diag_p, length=260))
    ang = (np.arctan2(fs["dy"], fs["dx"]) + np.pi) / (2 * np.pi)
    from matplotlib.colors import hsv_to_rgb
    save(f"{outdir}/02b_field_dir.png",
         hsv_to_rgb(np.stack([ang, np.full_like(ang, 0.8), fs["amp"] ** 0.7], -1)))
    save(f"{outdir}/02c_falloff.png", fs["phi"])

    rows = [("00_original", "元画像", {})]
    for name, label, kw in PRESETS:
        t0 = time.time()
        out, _ = fl.render(img, fl.Params(**kw))
        save(f"{outdir}/{name}.png", out)
        rows.append((name, label, kw))
        print(f"{name:16s} {time.time() - t0:5.1f}s  {label}")

    # --- contact sheet ---
    cols, tw = 3, 520
    th = int(tw * h / w)
    n = len(rows)
    r_ = (n + cols - 1) // cols
    sheet = Image.new("RGB", (tw * cols, th * r_), (16, 16, 20))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/fonts-japanese-gothic.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
    for i, (name, label, _) in enumerate(rows):
        im = Image.open(f"{outdir}/{name}.png").resize((tw, th), Image.LANCZOS)
        x, y = (i % cols) * tw, (i // cols) * th
        sheet.paste(im, (x, y))
        d.rectangle([x, y + th - 23, x + tw, y + th], fill=(0, 0, 0))
        d.text((x + 7, y + th - 19), f"{name}  {label}", fill=(255, 220, 60), font=font)
    sheet.save(f"{outdir}/_gallery.jpg", quality=92)
    print("gallery ->", f"{outdir}/_gallery.jpg")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
