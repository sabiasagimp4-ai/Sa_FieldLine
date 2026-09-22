"""入力の本数が 3 か所で食い違っていないか確かめる。

  1. SaFieldLine.csproj の <Inputs>   … fxc に渡す D2D_INPUT_COUNT
  2. シェーダ本体の D2DGetInput(i)    … 実際に読む番号
  3. Effects/*.cs の [CustomEffect(n)] … D2D に申告する本数

ここがずれると、Linux の構文チェック（ヘルパをスタブで代用していて入力を
6 本決め打ちで宣言している）はすり抜けるのに、Windows の実 fxc で
初めて落ちる。実際に Priority を 1 本のまま 3 本読む形にして踏んだ。

    python3 tests/shader_inputs_check.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def csproj_inputs() -> dict[str, int]:
    text = (ROOT / "SaFieldLine.csproj").read_text(encoding="utf-8")
    found = {}
    for m in re.finditer(r'FieldLineShader Include="Shaders\\(\w+)\.hlsl"><Inputs>(\d+)</Inputs>', text):
        found[m.group(1)] = int(m.group(2))
    return found


READ = r"(?:D2DGetInput|D2DSampleInputAtPosition)"


def shader_max_index(path: Path) -> int:
    """そのシェーダが読む入力番号の最大値。マクロ経由の読み出しも辿る。"""
    text = path.read_text(encoding="utf-8")
    idx = [int(m) for m in re.findall(READ + r"\(\s*(\d+)\s*[,)]", text)]

    # #define NAME(a, b, ...) の中で入力を読んでいる場合、番号は引数で渡ってくる。
    # その引数の位置を覚えておいて、呼び出し側のリテラルを拾う。
    for m in re.finditer(r"#define\s+(\w+)\(([^)]*)\)((?:[^\n]*\\\n)*[^\n]*)", text):
        name, params, body = m.group(1), m.group(2), m.group(3)
        names = [q.strip() for q in params.split(",") if q.strip()]
        if not re.search(READ + r"\(", body):
            continue
        for pos, pname in enumerate(names):
            if not re.search(READ + r"\(\s*" + re.escape(pname) + r"\s*[,)]", body):
                continue
            for call in re.finditer(re.escape(name) + r"\(([^)]*)\)", text):
                args = [a.strip() for a in call.group(1).split(",")]
                if pos < len(args) and args[pos].isdigit():
                    idx.append(int(args[pos]))
    return max(idx) if idx else -1


def cs_custom_effect() -> dict[str, int]:
    found = {}
    for cs in sorted((ROOT / "Effects").glob("*.cs")):
        text = cs.read_text(encoding="utf-8")
        shader = re.search(r'ShaderResourceLoader\.Get\("(\w+)"\)', text)
        count = re.search(r"\[CustomEffect\((\d+)\)\]", text)
        if shader and count:
            found[shader.group(1)] = int(count.group(1))
    return found


def main() -> int:
    proj = csproj_inputs()
    cs = cs_custom_effect()
    failures = []

    shaders = sorted(p.stem for p in (ROOT / "Shaders").glob("*.hlsl"))
    for name in shaders:
        used = shader_max_index(ROOT / "Shaders" / f"{name}.hlsl") + 1
        declared = proj.get(name)
        wired = cs.get(name)
        if declared is None:
            failures.append(f"{name}: csproj に <Inputs> が無い")
            continue
        if wired is None:
            failures.append(f"{name}: [CustomEffect(n)] を持つパスクラスが見つからない")
            continue
        note = "ok"
        if used > declared:
            failures.append(f"{name}: D2DGetInput({used - 1}) を読むのに csproj は {declared} 本")
            note = "FAILED"
        elif used < declared:
            # 使っていない入力を宣言してもコンパイルは通るが、配線ミスの兆候。
            failures.append(f"{name}: csproj は {declared} 本だが実際に読むのは {used} 本")
            note = "FAILED"
        if wired != declared:
            failures.append(f"{name}: [CustomEffect({wired})] と csproj の {declared} が違う")
            note = "FAILED"
        print(f"{name:14s} csproj={declared} shader={used} CustomEffect={wired}  {note}")

    missing = sorted(set(proj) - set(shaders))
    if missing:
        failures.append(f"csproj にあるがシェーダが無い: {', '.join(missing)}")

    if failures:
        for f in failures:
            print("NG", f)
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
