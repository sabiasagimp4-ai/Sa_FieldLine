// glslang で構文チェックするためのスタブ。実ビルドには使わない。
//
// 入力は D2D_INPUT_COUNT の本数だけ宣言する。6 本決め打ちにしていると、
// 「csproj に書いた本数より大きい番号を読んでいる」バグを素通りさせてしまう
// （実 fxc では落ちる）。実際に Priority で踏んだので、本数で切るようにした。
#if D2D_INPUT_COUNT > 0
Texture2D<float4> _saTex0; SamplerState _saSmp0;
#endif
#if D2D_INPUT_COUNT > 1
Texture2D<float4> _saTex1; SamplerState _saSmp1;
#endif
#if D2D_INPUT_COUNT > 2
Texture2D<float4> _saTex2; SamplerState _saSmp2;
#endif
#if D2D_INPUT_COUNT > 3
Texture2D<float4> _saTex3; SamplerState _saSmp3;
#endif
#if D2D_INPUT_COUNT > 4
Texture2D<float4> _saTex4; SamplerState _saSmp4;
#endif
#if D2D_INPUT_COUNT > 5
Texture2D<float4> _saTex5; SamplerState _saSmp5;
#endif

static float4 _saScenePos = float4(0.0, 0.0, 0.0, 0.0);

#define D2D_PS_ENTRY(name) float4 name(float4 saPos : SV_POSITION) : SV_Target
#define D2DGetScenePosition() (_saScenePos)
#define D2DGetInput(i) (_saTex##i.Sample(_saSmp##i, float2(0.5, 0.5)))
#define D2DSampleInputAtPosition(i, p) (_saTex##i.Sample(_saSmp##i, (p) * 0.001))
