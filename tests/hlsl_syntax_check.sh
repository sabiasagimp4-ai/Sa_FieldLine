#!/bin/sh
# fxc の無い環境（Linux / CI）で HLSL の構文を確かめる。
#
# Direct2D のヘルパは tests/hlslstub/d2d1effecthelpers.hlsli で代用する。
# 出力コードは捨てるので、見るのは構文・未定義の識別子・型の不一致だけ。
# 実ビルドは Windows SDK の fxc（ps_4_0）で行う。
#
#   sudo apt-get install glslang-tools
#   sh tests/hlsl_syntax_check.sh

set -e
root=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

cp "$root"/Shaders/*.hlsl "$root"/Shaders/*.hlsli "$root"/tests/hlslstub/*.hlsli "$work"/
# glslang は HLSL の <> インクルードを解決しないので "" に直す
sed -i 's|#include <d2d1effecthelpers.hlsli>|#include "d2d1effecthelpers.hlsli"|' "$work"/*.hlsl

cd "$work"
status=0
for f in *.hlsl; do
  out=$(glslangValidator -D -V -S frag -e main -I. -o /dev/null "$f" 2>&1 | grep -v -E "^$f\$|^\$" || true)
  if [ -n "$out" ]; then
    printf '=== %s ===\n%s\n' "$f" "$out"
    status=1
  else
    echo "ok  $f"
  fi
done
exit $status
