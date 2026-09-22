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
  # 入力の本数は csproj（実ビルドで fxc に渡すのと同じ値）から取る。
  # スタブがその本数だけ入力を宣言するので、番号がはみ出していればここで落ちる。
  name=${f%.hlsl}
  n=$(sed -n "s|.*Shaders.$name\.hlsl\"><Inputs>\([0-9]*\)</Inputs>.*|\1|p" "$root/SaFieldLine.csproj")
  if [ -z "$n" ]; then
    printf '=== %s ===\n%s\n' "$f" "csproj に <Inputs> がありません"
    status=1
    continue
  fi
  out=$(glslangValidator -D -V -S frag -e main "-DD2D_INPUT_COUNT=$n" -I. -o /dev/null "$f" 2>&1 | grep -v -E "^$f\$|^\$" || true)
  if [ -n "$out" ]; then
    printf '=== %s ===\n%s\n' "$f" "$out"
    status=1
  else
    echo "ok  $f"
  fi
done
exit $status
