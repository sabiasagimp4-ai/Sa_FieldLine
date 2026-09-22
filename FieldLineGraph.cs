using System.Numerics;
using Vortice;
using Vortice.Direct2D1;
using Vortice.Direct2D1.Effects;

namespace SaFieldLine;

/// <summary>
/// Direct2D の組み込みエフェクトを繋ぐための小道具。
///
/// プロパティは Vortice の型つきラッパー越しに設定する。生の添字で
/// <c>SetValue</c> を呼ぶこともできるが、添字の型が Vortice のバージョンで
/// <c>int</c> と <c>uint</c> の間を動いているので、名前で書くほうが移植しやすい。
/// </summary>
internal static class FieldLineGraph
{
    public static RawRect Expand(RawRect r, int by)
    {
        static int Shift(int value, long delta)
            => (int)Math.Clamp(value + delta, int.MinValue / 2, int.MaxValue / 2);
        return new RawRect(Shift(r.Left, -by), Shift(r.Top, -by), Shift(r.Right, by), Shift(r.Bottom, by));
    }

    /// <summary>
    /// 中間バッファを 16bit float にする。既定の 8bit では符号つきの法線や
    /// 1 を超える勾配が潰れて場が壊れる。
    ///
    /// カスタムエフェクト側では設定していない。YMM4 の
    /// <c>D2D1CustomShaderEffectBase.SetValue</c> は <c>int</c> 用で、
    /// 列挙型として渡せないので D2D に弾かれるため。組み込みエフェクトで上げておけば、
    /// 精度は入力から継承されるので下流のカスタムエフェクトにもそのまま伝わる。
    /// </summary>
    static T Float16<T>(this T effect) where T : ID2D1Effect
    {
        try
        {
            // Vortice の SetValue はプロパティ番号と値を int として受ける。
            // D2D1 の precision property は負のプロパティ番号を持つため、uint にしない。
            effect.SetValue(unchecked((int)Property.Precision), (int)BufferPrecision.PerChannel16Float);
        }
        catch
        {
            // 設定できない環境ではそのまま（見た目が粗くなるだけで動作はする）。
        }
        return effect;
    }

    public static Border CreateBorder(ID2D1DeviceContext context)
    {
        var e = new Border(context)
        {
            EdgeModeX = BorderEdgeMode.Clamp,
            EdgeModeY = BorderEdgeMode.Clamp,
        };
        return e.Float16();
    }

    public static GaussianBlur CreateBlur(ID2D1DeviceContext context)
    {
        var e = new GaussianBlur(context)
        {
            // Hard: ぼかしても矩形を広げない（広がると座標の対応が崩れる）
            BorderMode = BorderMode.Hard,
            // σ が大きい時は内部で縮小して掛けてくれる。影響範囲を上げた時の拡散で効く。
            Optimization = GaussianBlurOptimization.Balanced,
            StandardDeviation = 0f,
        };
        return e.Float16();
    }

    public static void SetBlurSigma(ID2D1Effect blur, float sigma)
        => ((GaussianBlur)blur).StandardDeviation = Math.Clamp(sigma, 0f, 250f);

    public static Scale CreateScale(ID2D1DeviceContext context, float factor)
    {
        var e = new Scale(context)
        {
            // 原点まわりに拡縮するので、シーン座標 p のテクスチャ上の位置は p * factor になる。
            CenterPoint = new Vector2(0f, 0f),
            InterpolationMode = ScaleInterpolationMode.Linear,
            BorderMode = BorderMode.Hard,
            Value = new Vector2(factor, factor),
        };
        return e.Float16();
    }

    public static Crop CreateCrop(ID2D1DeviceContext context)
    {
        var e = new Crop(context)
        {
            // Soft だと矩形の縁が半透明になる。場に透明の縁ができると流線が壊れる。
            BorderMode = BorderMode.Hard,
        };
        return e.Float16();
    }

    public static void SetCropRect(ID2D1Effect crop, Vector4 rect)
        => ((Crop)crop).Rectangle = rect;
}
