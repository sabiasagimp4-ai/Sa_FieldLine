// glslang で構文チェックするためのスタブ。実ビルドには使わない。
Texture2D<float4> _saTex0; SamplerState _saSmp0;
Texture2D<float4> _saTex1; SamplerState _saSmp1;
Texture2D<float4> _saTex2; SamplerState _saSmp2;
Texture2D<float4> _saTex3; SamplerState _saSmp3;
Texture2D<float4> _saTex4; SamplerState _saSmp4;
Texture2D<float4> _saTex5; SamplerState _saSmp5;

static float4 _saScenePos = float4(0.0, 0.0, 0.0, 0.0);

#define D2D_PS_ENTRY(name) float4 name(float4 saPos : SV_POSITION) : SV_Target
#define D2DGetScenePosition() (_saScenePos)
#define D2DGetInput(i) (_saTex##i.Sample(_saSmp##i, float2(0.5, 0.5)))
#define D2DSampleInputAtPosition(i, p) (_saTex##i.Sample(_saSmp##i, (p) * 0.001))
