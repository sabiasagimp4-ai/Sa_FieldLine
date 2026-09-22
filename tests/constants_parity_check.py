"""同じ定数が 3 か所で食い違っていないか確かめる。

  prototype/gpu_sim.py          … 数値の基準（HLSL はこれを移植したもの）
  Shaders/FieldLineCommon.hlsli … シェーダ側
  FieldLineProcessor.cs         … C# 側

片方だけ直すと、絵は出るのに参照実装とずれる。回帰テストは合成画像 1 枚で
見ているので、ずれ方によっては通ってしまう。

    python3 tests/constants_parity_check.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# gpu_sim の名前 -> (hlsli の名前, C# の名前)。無い所は None。
NAMES = {
    "K_MAG": ("K_MAG", None),
    "K_PHI": ("K_PHI", None),
    "K_COH": ("K_COH", None),
    "K_CURL": ("K_CURL", None),
    "K_TURB": ("K_TURB", None),
    "K_GRAD": ("K_GRAD", None),
    "PICK_GAIN": ("PICK_GAIN", None),
    "PICK_OWN": ("PICK_OWN", None),
    "PRIO_W": ("PRIO_W", None),
    "PRIO_K": ("PRIO_K", None),
    "PRIO_SMOOTH": (None, "PrioSmooth"),
    "TIE_BASE": (None, "TieBase"),
    "LINE_SEED_EDGE": (None, "LineSeedEdge"),
    "FIELD_DIV": (None, "FieldDiv"),
    "EDGE_OCTAVES": (None, "EdgeOctaves"),
    "SPREAD_OCTAVES": (None, "SpreadOctaves"),
    "STRETCH_STEP_PX": (None, "StretchStepPx"),
}

# gpu_sim では GpuParams の既定値として持っているもの -> C# の定数名
PARAM_DEFAULTS = {
    "base_sigma": "BaseSigma",
    "align": "Align",
    "amp_gamma": "AmpGamma",
    "falloff": "Falloff",
}


def py_consts(text: str) -> dict[str, float]:
    out = {}
    for m in re.finditer(r"^(\w+)\s*=\s*(-?[\d.]+)\s*(?:#.*)?$", text, re.M):
        out[m.group(1)] = float(m.group(2))
    return out


def py_param_defaults(text: str) -> dict[str, float]:
    out = {}
    for m in re.finditer(r"^\s+(\w+):\s*(?:float|int)\s*=\s*(-?[\d.]+)", text, re.M):
        out.setdefault(m.group(1), float(m.group(2)))
    return out


def hlsl_consts(text: str) -> dict[str, float]:
    return {m.group(1): float(m.group(2))
            for m in re.finditer(r"static const float (\w+)\s*=\s*(-?[\d.]+)", text)}


def cs_consts(text: str) -> dict[str, float]:
    return {m.group(1): float(m.group(2))
            for m in re.finditer(r"const (?:float|double|int) (\w+)\s*=\s*(-?[\d.]+)", text)}


def main() -> int:
    gpu = (ROOT / "prototype" / "gpu_sim.py").read_text(encoding="utf-8")
    py = py_consts(gpu)
    py.update(py_param_defaults(gpu))
    hl = hlsl_consts((ROOT / "Shaders" / "FieldLineCommon.hlsli").read_text(encoding="utf-8"))
    cs = cs_consts((ROOT / "FieldLineProcessor.cs").read_text(encoding="utf-8"))

    failures = []
    for name, (hname, csname) in list(NAMES.items()) + [(k, (None, v)) for k, v in PARAM_DEFAULTS.items()]:
        if name not in py:
            failures.append(f"{name}: gpu_sim.py に無い")
            continue
        base = py[name]
        cells = [f"py={base:g}"]
        if hname is not None:
            if hname not in hl:
                failures.append(f"{name}: FieldLineCommon.hlsli に {hname} が無い")
            else:
                cells.append(f"hlsl={hl[hname]:g}")
                if abs(hl[hname] - base) > 1e-9:
                    failures.append(f"{name}: py={base:g} だが hlsl={hl[hname]:g}")
        if csname is not None:
            if csname not in cs:
                failures.append(f"{name}: FieldLineProcessor.cs に {csname} が無い")
            else:
                cells.append(f"cs={cs[csname]:g}")
                if abs(cs[csname] - base) > 1e-9:
                    failures.append(f"{name}: py={base:g} だが cs={cs[csname]:g}")
        print(f"{name:16s} {'  '.join(cells)}")

    for f in failures:
        print("NG", f)
    print(f"constants parity: {'ok' if not failures else 'FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
