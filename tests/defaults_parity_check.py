"""GPU 相当シミュレーションの既定値が、プラグインの UI の既定値と揃っているか。

`gs.GpuParams()` を引数なしで作ったものが、YMM4 でエフェクトを掛けた直後と
同じ絵になるようにしておく。ここがずれていると、プロトタイプで見た絵と
実際に出る絵が違う（それに気付くのはたいてい動画を書き出した後）。

リファレンス実装 (`fieldline.py`) の既定値は研究用の出発点なので揃えない。

    python3 tests/defaults_parity_check.py
"""
from __future__ import annotations

import dataclasses
import re
import sys

# プロトタイプを import するので、.pyc を残さない。中身を書き換えても
# 大きさが同じで同じ秒に保存されると古いキャッシュが使われ、
# 直したはずの値で落ち続ける（実際に踏んだ）。
sys.dont_write_bytecode = True
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "prototype"))

import gpu_sim as gs            # noqa: E402

# C# のプロパティ名 -> (GpuParams の名前, UI の単位を割る数)
PAIRS = {
    "Strength": ("strength", 100), "Radius": ("radius", 1), "FlowLength": ("flow_length", 1),
    "Curvature": ("curvature", 100), "Swirl": ("swirl", 100), "Attract": ("attract", 100),
    "EdgeThreshold": ("edge_threshold", 100), "Smoothness": ("smoothness", 100),
    "DetailScale": ("detail_scale", 100), "Stretch": ("stretch", 100),
    "StretchGate": ("stretch_gate", 100), "StretchWidth": ("stretch_scale", 1),
    "StretchPick": ("stretch_pick", 1), "StretchSwirl": ("stretch_swirl", 100),
    "StretchDecay": ("stretch_decay", 100), "StretchJitter": ("stretch_jitter", 100),
    "LineDraw": ("line_draw", 100), "LineGrain": ("line_grain", 1),
    "LineDensity": ("line_density", 100), "Glow": ("glow", 100), "Shade": ("shade", 100),
    "Chroma": ("chroma", 100), "PreserveOriginal": ("preserve_original", 100),
}


def main() -> int:
    effect = (ROOT / "FieldLineEffect.cs").read_text(encoding="utf-8")
    ui = {m.group(1): float(m.group(2)) for m in re.finditer(
        r"public\s+Animation\s+(\w+)\s*\{[^}]*\}\s*=\s*new\((-?[\d.]+)", effect)}
    proto = {f.name: f.default for f in dataclasses.fields(gs.GpuParams)}

    failures = []
    for cs, (py, scale) in PAIRS.items():
        if cs not in ui:
            failures.append(f"{cs}: FieldLineEffect.cs に既定値が見つからない")
            continue
        if py not in proto:
            failures.append(f"{py}: GpuParams に無い")
            continue
        want, got = ui[cs] / scale, proto[py]
        ok = abs(want - got) < 1e-9
        if not ok:
            failures.append(f"{cs}: プラグイン={want:g} だが gpu_sim.{py}={got:g}")
        print(f"{cs:20s} プラグイン={want:<8g} gpu_sim={got:<8g} {'ok' if ok else 'FAILED'}")

    # UI にあるのにここへ書き忘れた（＝突き合わせから漏れた）ものを拾う
    for name in ui:
        if name not in PAIRS:
            failures.append(f"{name}: PAIRS に書かれていない（突き合わせから漏れる）")

    if len(PAIRS) < 15:
        failures.append(f"突き合わせが {len(PAIRS)} 件しかない")

    for f in failures:
        print("NG", f)
    print(f"defaults parity: {len(PAIRS)} 件 {'ok' if not failures else 'FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
