"""端の条件で NaN や範囲外が出ないか確かめる。

輪郭が 1 本も無い画像、極端に小さい画像、各パラメータの下限・上限を通す。
除算のガード（`max(..., 1e-4)`）が効いているかの確認が主目的。

    python3 tests/edge_cases.py
"""
from __future__ import annotations

import sys

# プロトタイプを import するので、.pyc を残さない。中身を書き換えても
# 大きさが同じで同じ秒に保存されると古いキャッシュが使われ、
# 直したはずの値で落ち続ける（実際に踏んだ）。
sys.dont_write_bytecode = True
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prototype"))

import gpu_sim as gs            # noqa: E402


def flat(h=64, w=96):
    """輪郭が 1 本も無い画像。正規化の分母が全部 0 に近づく。"""
    return np.full((h, w, 3), 0.5, np.float32)


def tiny():
    """縮小連鎖が 1x1 に達する前に潰れる大きさ。"""
    rng = np.random.default_rng(3)
    return rng.random((8, 11, 3)).astype(np.float32)


def normal(h=96, w=128):
    img = np.zeros((h, w, 3), np.float32)
    img[:] = 0.2
    img[20:70, 30:90] = 0.9
    img[40:50, :] = 0.05
    return img


CASES = [
    ("輪郭なし", flat(), dict(stretch=1.0)),
    ("極小の画像", tiny(), dict(stretch=1.0)),
    ("流線の長さ 0", normal(), dict(stretch=1.0, flow_length=0.0)),
    ("流線の長さ 1px", normal(), dict(stretch=1.0, flow_length=1.0)),
    ("流線の長さ 1000px", normal(), dict(stretch=1.0, flow_length=1000.0, stretch_steps=64)),
    ("閾値 0", normal(), dict(stretch=1.0, edge_threshold=0.0)),
    ("閾値 1", normal(), dict(stretch=1.0, edge_threshold=1.0)),
    ("ゲート 0", normal(), dict(stretch=1.0, stretch_gate=0.0)),
    ("ゲート 1", normal(), dict(stretch=1.0, stretch_gate=1.0)),
    ("近さを優先 0", normal(), dict(stretch=1.0, stretch_decay=0.0)),
    ("近さを優先 1", normal(), dict(stretch=1.0, stretch_decay=1.0)),
    ("筆の毛 1", normal(), dict(stretch=1.0, stretch_jitter=1.0)),
    ("近さ 1 + 毛 1", normal(), dict(stretch=1.0, stretch_decay=1.0, stretch_jitter=1.0)),
    ("拾う位置 0", normal(), dict(stretch=1.0, stretch_pick=0.0)),
    ("影響範囲 1px", normal(), dict(stretch=1.0, radius=1.0)),
    ("細かさ 0", normal(), dict(stretch=1.0, detail_scale=0.0)),
    ("細かさ 1", normal(), dict(stretch=1.0, detail_scale=1.0)),
    ("全部盛り", normal(), dict(stretch=1.0, stretch_decay=1.0, stretch_jitter=0.8,
                             swirl=1.0, attract=-1.0, curvature=3.0, glow=1.0,
                             line_draw=1.0, shade=1.0, chroma=1.0, preserve_original=0.5)),
]


def main() -> int:
    failures = []
    for name, img, kw in CASES:
        base = dict(radius=40, flow_length=30, stretch_steps=48, steps=48)
        base.update(kw)
        try:
            out, _ = gs.render(img, gs.GpuParams(**base))
        except Exception as e:                      # noqa: BLE001
            failures.append(f"{name}: 例外 {type(e).__name__}: {e}")
            continue
        bad = []
        if not np.isfinite(out).all():
            bad.append("NaN/Inf")
        if out.min() < -0.01:
            bad.append(f"下限外 {out.min():.3f}")
        if out.max() > 8.0:                          # 発光は 1 を超えるが、桁は超えない
            bad.append(f"上限外 {out.max():.3f}")
        if out.shape != img.shape:
            bad.append(f"形が違う {out.shape} != {img.shape}")
        print(f"{name:16s} min={out.min():+.3f} max={out.max():+.3f} "
              f"{'ok' if not bad else 'FAILED ' + ', '.join(bad)}")
        if bad:
            failures.append(f"{name}: {', '.join(bad)}")

    if len(CASES) < 10:
        failures.append(f"ケースが {len(CASES)} 件しかない")

    if failures:
        print("FAILED:", "; ".join(failures))
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
