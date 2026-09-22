"""サンプル生成スクリプトのプリセットが、今のパラメータ定義で通るか確かめる。

描画はしない（数秒で終わる）。パラメータを消したり名前を変えたりした時に、
`render_gallery.py` / `render_text_demo.py` が黙って壊れるのを防ぐためのもの。
実際にそれをやって 3 プリセットを壊したことがある。

    python3 tests/preset_smoke.py
"""
from __future__ import annotations

import dataclasses
import sys

# プロトタイプを import するので、.pyc を残さない。中身を書き換えても
# 大きさが同じで同じ秒に保存されると古いキャッシュが使われ、
# 直したはずの値で落ち続ける（実際に踏んだ）。
sys.dont_write_bytecode = True
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prototype"))

import fieldline as fl          # noqa: E402
import gpu_sim as gs            # noqa: E402
import render_gallery as gallery  # noqa: E402
import render_text_demo as text   # noqa: E402


def main() -> int:
    failures: list[str] = []
    checked = 0

    for name, _desc, kw in gallery.PRESETS:
        checked += 1
        try:
            fl.Params(**kw)
        except TypeError as e:
            failures.append(f"render_gallery {name}: {e}")

    for name, kw in text.CASES:
        checked += 1
        try:
            fl.Params(**kw)
        except TypeError as e:
            failures.append(f"render_text_demo {name}: {e}")

    for name, kw in text.PULLS:
        checked += 1
        try:
            gs.GpuParams(**kw)
        except TypeError as e:
            failures.append(f"render_text_demo {name}: {e}")

    # 両実装で名前が食い違っていないか。gpu_sim 側にしか無くてよいのは
    # 「GPU の都合そのもの」だけで、それ以外はリファレンスに対応が要る。
    gpu_only_ok = {"field_div", "stretch_div", "stretch_steps", "steps", "step_px", "base_sigma"}
    ref_names = {f.name for f in dataclasses.fields(fl.Params)}
    gpu_names = {f.name for f in dataclasses.fields(gs.GpuParams)}
    stray = sorted(gpu_names - ref_names - gpu_only_ok)
    if stray:
        failures.append(f"gpu_sim にしか無いパラメータ: {', '.join(stray)}")

    # プリセットの取り出しに失敗して「0 件 ok」を返すのが一番まずい。
    if checked < 10:
        failures.append(f"プリセットを {checked} 件しか拾えていない（取り出し方が古い）")

    for f in failures:
        print("NG", f)
    print(f"preset smoke: {checked} 件 {'ok' if not failures else 'FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
