"""UI に出したパラメータが、ちゃんと最後まで繋がっているか確かめる。

  1. FieldLineEffect.cs の各プロパティを FieldLineProcessor.cs が読んでいるか
  2. Animation のプロパティが GetAnimatables() に入っているか（入れないとキーフレームが効かない）
  3. UI の Order が重複していないか

C# のコンパイルは通ってしまうので、配線を忘れても気付けない。実際に
「近さを優先」と「筆の毛」を足したのに Processor 側の適用が丸ごと抜けていて、
UI だけあって何も起きない状態で通していた。

    python3 tests/params_wired_check.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 表示だけで処理に渡らないもの（あれば理由つきでここに書く）
NOT_WIRED_OK: dict[str, str] = {}


def main() -> int:
    effect = (ROOT / "FieldLineEffect.cs").read_text(encoding="utf-8")
    processor = (ROOT / "FieldLineProcessor.cs").read_text(encoding="utf-8")
    failures = []

    props = re.findall(
        r"\[Display\(Name = \"([^\"]+)\"[^\]]*Order = (\d+)\)\]"
        r"(?:\s*\[[^\]]*\])*\s*public\s+(\w+)\s+(\w+)\s*\{",
        effect)
    if not props:
        print("NG プロパティを 1 つも拾えなかった（正規表現が古い）")
        return 1

    orders: dict[int, str] = {}
    animatables = re.search(r"GetAnimatables\(\) =>\s*\[(.*?)\];", effect, re.S)
    listed = set(re.findall(r"\w+", animatables.group(1))) if animatables else set()

    for display, order, typ, name in props:
        order_i = int(order)
        bad = []
        if order_i in orders:
            bad.append(f"Order {order_i} が {orders[order_i]} と重複")
        orders[order_i] = name

        if name not in NOT_WIRED_OK and not re.search(r"item\." + re.escape(name) + r"\b", processor):
            bad.append("FieldLineProcessor が読んでいない")

        if typ == "Animation" and name not in listed:
            bad.append("GetAnimatables() に無い＝キーフレームが効かない")

        failures += [f"{name}（{display}）: {b}" for b in bad]
        print(f"{name:20s} order={order_i:<3d} {typ:10s} "
              f"{'ok' if not bad else 'FAILED ' + ', '.join(bad)}")

    gaps = sorted(set(range(len(orders))) - set(orders))
    if gaps:
        failures.append(f"Order に抜けがある: {gaps}")

    for f in failures:
        print("NG", f)
    print(f"params wired: {len(props)} 件 {'ok' if not failures else 'FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
