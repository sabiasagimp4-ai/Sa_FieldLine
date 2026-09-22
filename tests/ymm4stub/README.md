# YMM4 スタブ

Windows と YMM4 の無い環境で **C# の型検査だけ** を通すための置き換え。
`tests/csharp_compile_check.sh` から使う。

## これは何ではないか

- YMM4 の API ドキュメントではない。中身は全部空で、動かすと例外になる。
- 実ビルドには使わない。実ビルドは Windows で `-p:YMM4DirPath=<YMM4 のフォルダ>` を渡す。

## 何を検査できるか

| | 検査される |
| --- | --- |
| Vortice（組み込みエフェクト・列挙・`SetValue` の添字の型） | **本物**（nuget の `Vortice.Direct2D1`） |
| YMM4 の型（`VideoEffectBase` / `D2D1CustomShaderEffectBase` など） | スタブ |
| HLSL | されない（`tests/hlsl_syntax_check.sh`） |
| 入力の本数が csproj / シェーダ / `[CustomEffect(n)]` で揃っているか | されない（`tests/shader_inputs_check.py`） |
| UI のパラメータが Processor まで繋がっているか | されない（`tests/params_wired_check.py`） |

型検査は「書いた C# が通るか」しか見ない。**書き忘れ**（プロパティを読んでいない、
入力の本数を増やし忘れた）は素通りするので、その 2 つは別の検査で見ている。

## シグネチャの根拠

スタブの署名は、実際に YMM4 でビルドが通っているコードから写した。憶測では書かない。

- [manju-summoner/YukkuriMovieMaker4PluginSamples](https://github.com/manju-summoner/YukkuriMovieMaker4PluginSamples)
  — `VideoEffectBase`、`D2D1CustomShaderEffectImplBase<T>`、`MapInputRectsToOutputRect` など
- [manju-summoner/YukkuriMovieMaker.Plugin.Community](https://github.com/manju-summoner/YukkuriMovieMaker.Plugin.Community)
  — `SetInput(int index, ID2D1Image?, RawBool)`（ループ変数を渡している箇所があるので添字は `int`）、
    `[CustomEffect(12)]` / `[CustomEffect(13)]`（多入力が実際に使われている）
- `Sa_chromablur`（リリース済みの自前プラグイン）— `SetValue((int)Properties.X, value)` の形

YMM4 の実装が変わってスタブと食い違ったら、**スタブのほうを直す**。
