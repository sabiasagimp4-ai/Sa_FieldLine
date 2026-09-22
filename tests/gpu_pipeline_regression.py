"""GPU 相当パイプライン (gpu_sim) がリファレンス (fieldline) と同じ絵になるか確かめる。

Direct2D 実装は gpu_sim.py を 1:1 で移植したものなので、ここが合っていれば
HLSL 側の数式も合っている（はず）という位置づけのテスト。
Windows も YMM4 も要らないので CI で回せる。

    python3 tests/gpu_pipeline_regression.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prototype"))

import fieldline as fl          # noqa: E402
import gpu_sim as gs            # noqa: E402


def make_scene(h: int = 360, w: int = 560) -> np.ndarray:
    """輪郭の向きと太さがばらける合成画像。素材の著作権に依存しない。"""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.zeros((h, w, 3), np.float32)
    img[..., 0] = 0.18 + 0.30 * (yy / h)
    img[..., 1] = 0.22 + 0.24 * (xx / w)
    img[..., 2] = 0.40 - 0.18 * (yy / h)

    # 大きい円（太い輪郭）
    disc = ((xx - w * 0.32) ** 2 + (yy - h * 0.45) ** 2) < (h * 0.26) ** 2
    img[disc] = (0.92, 0.86, 0.72)

    # 斜めの帯（直線の輪郭）
    band = np.abs((xx - yy * 0.7) - w * 0.62) < w * 0.045
    img[band] = (0.10, 0.45, 0.52)

    # 細い縞（細かい輪郭）
    stripes = (np.sin(xx * 0.55) > 0.65) & (yy > h * 0.72)
    img[stripes] = (0.95, 0.42, 0.18)

    # 角の矩形（コーナー = 鞍点ができる）
    img[int(h * 0.08):int(h * 0.30), int(w * 0.70):int(w * 0.93)] = (0.06, 0.07, 0.10)

    img = gaussian_filter(img, (0.7, 0.7, 0), mode="nearest")
    return np.clip(img, 0.0, 1.0).astype(np.float32)


CASES = [
    ("drift", dict(strength=0.55, radius=150, flow_length=70, curvature=1.0,
                   smoothness=0.35, edge_threshold=0.10, detail_scale=0.5), 0.10),
    ("magnetic", dict(strength=0.5, radius=150, flow_length=160, swirl=1.0, curvature=1.0,
                      smoothness=0.35, edge_threshold=0.10, detail_scale=0.5), 0.12),
    ("electric", dict(strength=0.45, radius=180, flow_length=170, attract=-0.9, curvature=1.0,
                      smoothness=0.50, edge_threshold=0.13, detail_scale=0.40), 0.12),
    ("fine", dict(strength=0.8, radius=90, flow_length=90, curvature=1.2,
                  smoothness=0.30, edge_threshold=0.08, detail_scale=1.0), 0.12),
    ("coarse", dict(strength=0.9, radius=200, flow_length=150, curvature=1.2,
                    smoothness=0.40, edge_threshold=0.08, detail_scale=0.0), 0.14),
    ("pull", dict(strength=0.0, radius=150, flow_length=140, curvature=1.0,
                  smoothness=0.40, edge_threshold=0.25, detail_scale=0.30,
                  stretch=1.0, stretch_gate=0.35, stretch_pick=3.0), 0.12),
    # 力線は局所コントラスト正規化を解析式に置き換えているので、許容を広めに取る
    # 「近さを優先」と「筆の毛」を使う側。届く距離が優先度で決まる経路を通す。
    ("brush", dict(strength=0.0, radius=150, flow_length=200, curvature=1.0,
                   smoothness=0.40, edge_threshold=0.25, detail_scale=0.30,
                   stretch=1.0, stretch_gate=0.35, stretch_pick=3.0,
                   stretch_decay=0.9, stretch_jitter=0.6), 0.12),
    ("lines", dict(strength=0.25, radius=160, flow_length=110, curvature=1.2,
                   smoothness=0.45, edge_threshold=0.10, detail_scale=0.45,
                   line_draw=0.6, line_grain=1.5, line_density=1.1, steps=48), 0.16),
    ("glow", dict(strength=0.45, radius=150, flow_length=90, curvature=1.0,
                  smoothness=0.40, edge_threshold=0.10, detail_scale=0.5,
                  glow=0.9, steps=48), 0.14),
]


def main() -> int:
    img = make_scene()
    failures = []
    for name, kw, tol in CASES:
        ref_kw = dict(kw)
        ref_kw.pop("steps", None)
        if "stretch" in ref_kw:
            ref_kw.update(stretch_mode="edge", stretch_radial=True, step_px=0.9)
        else:
            ref_kw.update(step_px=1.25)
        ref, _ = fl.render(img, fl.Params(**ref_kw))
        out, _ = gs.render(img, gs.GpuParams(**kw))
        diff = float(np.abs(ref - out).mean())
        ok = diff <= tol
        # 許容の 8 割を超えたら、落ちてはいないが「じわじわ寄っている」ので知らせる。
        # 黙って限界まで近づいて、ある日いきなり落ちるのを防ぐため。
        note = "ok" if ok else "FAILED"
        if ok and diff > tol * 0.8:
            note = f"ok（許容の {diff / tol * 100:.0f}%。寄ってきている）"
        print(f"{name:10s} meanAbsDiff={diff:.4f} (<= {tol:.2f}) {note}")
        if not ok:
            failures.append(name)

    # 引き伸ばしは伝播なので、隣接画素が大きく食い違ってはいけない（櫛状の破線の検出）。
    #
    # 元画像そのものが縞（細い縞のブロック）を持っているので、出力の縞をそのまま
    # 数えると「元の構造が残っているほど悪い」という逆の指標になってしまう。
    # **元が平坦な所に新しく出た縞** だけを数える。
    # 歩幅を粗くすると 0.05 以上に跳ね上がるので、0.02 で十分に分離できる。
    kw = dict(strength=0.0, radius=150, flow_length=140, curvature=1.0, smoothness=0.40,
              edge_threshold=0.25, detail_scale=0.30, stretch=1.0, stretch_gate=0.35,
              stretch_pick=3.0)
    out, _ = gs.render(img, gs.GpuParams(**kw))
    d = np.diff(out.mean(-1), axis=1)
    ds = np.diff(img.mean(-1), axis=1)
    smooth = (np.abs(ds[:, :-1]) <= 0.02) & (np.abs(ds[:, 1:]) <= 0.02)
    bad = (d[:, :-1] * d[:, 1:] < 0) & (np.abs(d[:, :-1]) > 0.02) & smooth
    flips = float(bad.sum() / max(smooth.sum(), 1))
    print(f"comb       flipRatio={flips:.4f} (<= 0.02) {'ok' if flips <= 0.02 else 'FAILED'}")
    if flips > 0.02:
        failures.append("comb")

    if failures:
        print("FAILED:", ", ".join(failures))
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
