#!/bin/sh
# fxc.exe の代わり。/Fo の指す先に placeholder を書くだけ。
# C# の型検査が目的なので中身は使わない。HLSL は tests/hlsl_syntax_check.sh で見る。
out=""
prev=""
for a in "$@"; do
  [ "$prev" = "/Fo" ] && out="$a"
  prev="$a"
done
[ -n "$out" ] || { echo "fake-fxc: /Fo がありません" >&2; exit 1; }
mkdir -p "$(dirname "$out")"
printf 'not-a-real-cso' > "$out"
