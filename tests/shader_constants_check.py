"""シェーダが読む定数スロットを、C# がちゃんと入れているか確かめる。

定数バッファは float4 x 6 固定で、シェーダごとに `#define NAME c0.x` のように
名前を付けている。シェーダに `c1.z` を足したのに C# 側の `xxx.C1 = ...` を
書き忘れても、コンパイルは通るし D2D も何も言わない。**古い値か 0 が読まれる**だけ。

    python3 tests/shader_constants_check.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# シェーダ名 -> FieldLineProcessor.cs での変数名（複数あるものは全部書く）
OWNERS = {
    "Luma": ["luma"],
    "Edge": ["edge"],
    "Stats": ["magStats", "phiStats", "vStats"],
    "Confidence": ["confidence"],
    "Spread": ["spread"],
    "FieldDir": ["fieldDir"],
    "FieldA": ["fieldA"],
    "FieldB": ["fieldB"],
    "Radial": ["radial"],
    "Advect": ["advect"],
    "Priority": ["priority"],
    "StretchInit": ["stretchInit"],
    "StretchStep": ["pass"],          # ループ変数（stretchSteps[i]）
    "Composite": ["composite"],
    "Post": ["post"],
}


def slots_used(text: str) -> set[int]:
    """シェーダが実際に読むスロット番号。

    `#define RECT c2` のように丸ごと別名を付ける書き方があるので、
    `c2.x` の形だけを見ていると取りこぼす。`cN` の出現を全部拾う。
    """
    return {int(m) for m in re.findall(r"\bc([0-5])\b", text)}


def main() -> int:
    processor = (ROOT / "FieldLineProcessor.cs").read_text(encoding="utf-8")
    failures = []
    checked = 0

    for name, owners in OWNERS.items():
        path = ROOT / "Shaders" / f"{name}.hlsl"
        if not path.exists():
            failures.append(f"{name}.hlsl が無い")
            continue
        checked += 1
        used = slots_used(path.read_text(encoding="utf-8"))
        for owner in owners:
            setslots = {int(m) for m in re.findall(re.escape(owner) + r"\.C([0-5])\s*=", processor)}
            missing = sorted(used - setslots)
            if missing:
                failures.append(f"{name}: {owner} が c{', c'.join(map(str, missing))} を入れていない")
            print(f"{name:14s} {owner:12s} シェーダ={sorted(used)} C#={sorted(setslots)} "
                  f"{'ok' if not missing else 'FAILED'}")

    if checked < 10:
        failures.append(f"シェーダを {checked} 本しか見ていない")

    for f in failures:
        print("NG", f)
    print(f"shader constants: {checked} 本 {'ok' if not failures else 'FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
