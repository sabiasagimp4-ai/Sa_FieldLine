using System.Numerics;
using System.Runtime.InteropServices;
using Vortice;
using Vortice.Direct2D1;
using YukkuriMovieMaker.Commons;
using YukkuriMovieMaker.Player.Video;

namespace SaFieldLine;

/// <summary>Post.hlsl のパス。定数バッファは float4 x 6 固定。</summary>
internal sealed class PostPass : D2D1CustomShaderEffectBase
{
    public PostPass(IGraphicsDevicesAndContext devices) : base(Create<Impl>(devices))
    {
        // 中間バッファを 16bit float にする。既定の 8bit では符号つきの値が潰れる。
        // 設定できない環境では、上流の組み込みエフェクトから継承されるのに任せる。
        try
        {
            SetValue(FieldLineGraph.PropertyPrecision, FieldLineGraph.Precision16Float);
        }
        catch
        {
        }
    }

    public Vector4 C0 { set => SetValue((int)Impl.Properties.C0, value); }
    public Vector4 C1 { set => SetValue((int)Impl.Properties.C1, value); }
    public Vector4 C2 { set => SetValue((int)Impl.Properties.C2, value); }
    public Vector4 C3 { set => SetValue((int)Impl.Properties.C3, value); }
    public Vector4 C4 { set => SetValue((int)Impl.Properties.C4, value); }
    public Vector4 C5 { set => SetValue((int)Impl.Properties.C5, value); }

    [CustomEffect(4)]
    internal sealed class Impl : D2D1CustomShaderEffectImplBase<Impl>
    {
        Constants constants;
        RawRect[] sourceRects = [];

        [CustomEffectProperty(PropertyType.Vector4, (int)Properties.C0)]
        public Vector4 C0 { get => constants.C0; set { constants.C0 = value; UpdateConstants(); } }

        [CustomEffectProperty(PropertyType.Vector4, (int)Properties.C1)]
        public Vector4 C1 { get => constants.C1; set { constants.C1 = value; UpdateConstants(); } }

        [CustomEffectProperty(PropertyType.Vector4, (int)Properties.C2)]
        public Vector4 C2 { get => constants.C2; set { constants.C2 = value; UpdateConstants(); } }

        [CustomEffectProperty(PropertyType.Vector4, (int)Properties.C3)]
        public Vector4 C3 { get => constants.C3; set { constants.C3 = value; UpdateConstants(); } }

        [CustomEffectProperty(PropertyType.Vector4, (int)Properties.C4)]
        public Vector4 C4 { get => constants.C4; set { constants.C4 = value; UpdateConstants(); } }

        /// <summary>z = 入力を広げる画素数、w = 「入力全体が要る」入力のビットマスク。</summary>
        [CustomEffectProperty(PropertyType.Vector4, (int)Properties.C5)]
        public Vector4 C5 { get => constants.C5; set { constants.C5 = value; UpdateConstants(); } }

        public Impl() : base(ShaderResourceLoader.Get("Post")) { }

        protected override void UpdateConstants() => drawInformation?.SetPixelShaderConstantBuffer(constants);

        public override void MapInputRectsToOutputRect(RawRect[] inputRects, RawRect[] inputOpaqueSubRects, out RawRect outputRect, out RawRect outputOpaqueSubRect)
        {
            sourceRects = (RawRect[])inputRects.Clone();
            outputRect = inputRects[0];
            outputOpaqueSubRect = default;
        }

        public override void MapOutputRectToInputRects(RawRect outputRect, RawRect[] inputRects)
        {
            var expand = (int)Math.Clamp(constants.C5.Z, 0f, 1_000_000f);
            var whole = (int)Math.Clamp(constants.C5.W, 0f, 255f);
            for (var i = 0; i < inputRects.Length; i++)
            {
                // 解像度の違う入力や、流線が遠くまで走る入力は全体を要求する。
                // 出力矩形を広げるだけでは、座標系が違うので足りない。
                if ((whole & (1 << i)) != 0 && i < sourceRects.Length)
                    inputRects[i] = sourceRects[i];
                else
                    inputRects[i] = FieldLineGraph.Expand(outputRect, expand);
            }
        }

        [StructLayout(LayoutKind.Sequential, Size = 96)]
        struct Constants
        {
            public Vector4 C0;
            public Vector4 C1;
            public Vector4 C2;
            public Vector4 C3;
            public Vector4 C4;
            public Vector4 C5;
        }

        internal enum Properties
        {
            C0 = 0,
            C1 = 1,
            C2 = 2,
            C3 = 3,
            C4 = 4,
            C5 = 5,
        }
    }
}
