#!/bin/sh
# Windows と YMM4 の無い環境で C# の型検査をする。
#
# YMM4 の型は tests/ymm4stub のスタブで代用するが、Vortice は nuget の本物を使う。
# 組み込みエフェクトのクラス名・列挙・SetValue の添字の型はここで実際に検査される。
# fxc は tests/ymm4stub/fake-fxc.sh で代用する（.cso の中身は見ない）。
#
#   sudo apt-get install -y dotnet-sdk-10.0
#   sh tests/csharp_compile_check.sh [Debug|Release]

set -e
config=${1:-Release}
root=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1

echo "--- スタブを作る"
for p in YukkuriMovieMaker.Plugin YukkuriMovieMaker.Controls; do
  dotnet build "$root/tests/ymm4stub/$p/$p.csproj" -c Release -v q --nologo \
    -p:BaseIntermediateOutputPath="$work/obj-$p/" -p:BaseOutputPath="$work/bin-$p/"
  cp "$work/bin-$p/Release/net10.0/"*.dll "$work/"
done

echo "--- プラグインをビルドする ($config)"
dotnet build "$root/SaFieldLine.csproj" -c "$config" -v m --nologo \
  -p:EnableWindowsTargeting=true \
  -p:YMM4DirPath="$work/" \
  -p:FxcPath="$root/tests/ymm4stub/fake-fxc.sh" \
  -p:D2DIncludePath="$work" \
  -p:BaseIntermediateOutputPath="$work/obj-plugin/" \
  -p:BaseOutputPath="$work/bin-plugin/"

dll="$work/bin-plugin/$config/net10.0-windows10.0.19041.0/SaFieldLine.dll"
[ -f "$dll" ] || { echo "SaFieldLine.dll ができていない"; exit 1; }

echo "--- 埋め込んだシェーダを確かめる"
want=$(grep -ho 'ShaderResourceLoader\.Get("[A-Za-z]*")' "$root"/Effects/*.cs |
  sed 's/.*Get("//;s/")//' | sort -u)
have=$(strings "$dll" | grep -o 'SaFieldLine\.[A-Za-z]*\.cso' |
  sed 's/SaFieldLine\.//;s/\.cso//' | sort -u)
if [ "$want" != "$have" ]; then
  echo "シェーダのリソース名が合っていない:"
  echo "$want" > "$work/want.txt"
  echo "$have" > "$work/have.txt"
  diff "$work/want.txt" "$work/have.txt" || true
  exit 1
fi
echo "ok  $(echo "$want" | wc -l) 個のシェーダが名前どおりに埋め込まれている"
