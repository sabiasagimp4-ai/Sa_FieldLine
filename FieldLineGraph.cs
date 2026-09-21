using System.Numerics;
using Vortice;
using Vortice.Direct2D1;

namespace SaFieldLine;

/// <summary>
/// Direct2D の組み込みエフェクトを繋ぐための小道具。
///
/// プロパティは Vortice のラッパー名ではなく <c>d2d1effects.h</c> の
/// インデックスで設定する。名前はバインディングのバージョンで変わりうるが、
/// インデックスは Windows の仕様なので変わらない。
/// </summary>
internal static class FieldLineGraph
{
    // d2d1_1.h : D2D1_PROPERTY
    public const int PropertyPrecision = unchecked((int)0x80000007);
    // d2d1_1.h : D2D1_BUFFER_PRECISION_16BPC_FLOAT
    public const int Precision16Float = 4;

    // d2d1effects.h : D2D1_GAUSSIANBLUR_PROP
    const int BlurStandardDeviation = 0;
    const int BlurOptimization = 1;
    const int BlurBorderMode = 2;

    // d2d1effects.h : D2D1_BORDER_PROP
    const int BorderEdgeModeX = 0;
    const int BorderEdgeModeY = 1;
    const int BorderEdgeModeClamp = 0;

    // d2d1effects.h : D2D1_SCALE_PROP
    const int ScaleAmount = 0;
    const int ScaleCenterPoint = 1;
    const int ScaleInterpolationMode = 2;
    const int ScaleBorderMode = 3;
    const int ScaleInterpolationLinear = 1;

    // d2d1effects.h : D2D1_CROP_PROP
    const int CropRect = 0;
    const int CropBorderMode = 1;

    // D2D1_BORDER_MODE_HARD : ぼかしても矩形を広げない（広がると座標の対応が崩れる）
    const int BorderModeHard = 1;
    // D2D1_GAUSSIANBLUR_OPTIMIZATION_BALANCED
    // σ が大きい時は内部で縮小して掛けてくれる。Radius を上げた時の拡散で効く。
    const int BlurOptimizationBalanced = 1;

    public static RawRect Expand(RawRect r, int by)
    {
        static int Shift(int value, long delta)
            => (int)Math.Clamp(value + delta, int.MinValue / 2, int.MaxValue / 2);
        return new RawRect(Shift(r.Left, -by), Shift(r.Top, -by), Shift(r.Right, by), Shift(r.Bottom, by));
    }

    /// <summary>
    /// 中間バッファを 16bit float にする。既定の 8bit では符号つきの法線や
    /// 1 を超える勾配が潰れて場が壊れる。下流のエフェクトは入力から精度を継承するので、
    /// 経路の先頭で立てておけば全体に伝わる。
    /// </summary>
    public static T Float16<T>(this T effect) where T : ID2D1Effect
    {
        try
        {
            effect.SetValue(PropertyPrecision, Precision16Float);
        }
        catch
        {
            // 設定できない環境ではそのまま（見た目が粗くなるだけで動作はする）。
        }
        return effect;
    }

    public static ID2D1Effect CreateBorder(ID2D1DeviceContext context)
    {
        var e = new Vortice.Direct2D1.Effects.Border(context);
        e.SetValue(BorderEdgeModeX, BorderEdgeModeClamp);
        e.SetValue(BorderEdgeModeY, BorderEdgeModeClamp);
        return e.Float16();
    }

    public static ID2D1Effect CreateBlur(ID2D1DeviceContext context)
    {
        var e = new Vortice.Direct2D1.Effects.GaussianBlur(context);
        e.SetValue(BlurBorderMode, BorderModeHard);
        e.SetValue(BlurOptimization, BlurOptimizationBalanced);
        e.SetValue(BlurStandardDeviation, 0f);
        return e.Float16();
    }

    public static void SetBlurSigma(ID2D1Effect blur, float sigma)
        => blur.SetValue(BlurStandardDeviation, Math.Clamp(sigma, 0f, 250f));

    public static ID2D1Effect CreateScale(ID2D1DeviceContext context, float factor)
    {
        var e = new Vortice.Direct2D1.Effects.Scale(context);
        // 原点まわりに拡縮するので、シーン座標 p のテクスチャ上の位置は p * factor になる。
        e.SetValue(ScaleCenterPoint, new Vector2(0f, 0f));
        e.SetValue(ScaleInterpolationMode, ScaleInterpolationLinear);
        e.SetValue(ScaleBorderMode, BorderModeHard);
        e.SetValue(ScaleAmount, new Vector2(factor, factor));
        return e.Float16();
    }

    public static ID2D1Effect CreateCrop(ID2D1DeviceContext context)
    {
        var e = new Vortice.Direct2D1.Effects.Crop(context);
        // Soft だと矩形の縁が半透明になる。場に透明の縁ができると流線が壊れる。
        e.SetValue(CropBorderMode, BorderModeHard);
        return e.Float16();
    }

    public static void SetCropRect(ID2D1Effect crop, Vector4 rect)
        => crop.SetValue(CropRect, rect);
}
