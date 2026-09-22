using System.Numerics;
using SharpGen.Runtime;
using Vortice;
using Vortice.Direct2D1;
using YukkuriMovieMaker.Commons;

namespace YukkuriMovieMaker.Player.Video;

public interface IVideoEffectProcessor : IDisposable
{
    ID2D1Image Output { get; }
    void SetInput(ID2D1Image? input);
    void ClearInput();
    DrawDescription Update(EffectDescription effectDescription);
}

/// <summary>Stands in for YMM4's wrapper around a registered custom effect.</summary>
public abstract class D2D1CustomShaderEffectBase : IDisposable
{
    protected D2D1CustomShaderEffectBase(ID2D1Effect effect) { _ = effect; }

    protected static ID2D1Effect Create<T>(IGraphicsDevicesAndContext devices)
        where T : D2D1CustomShaderEffectImplBase<T>, new()
        => throw new NotSupportedException("stub");

    public bool IsEnabled => true;
    public ID2D1Image Output => throw new NotSupportedException("stub");

    // The community plugin passes a loop variable here, so the index really is int.
    public void SetInput(int index, ID2D1Image? input, RawBool invalidate) { _ = index; _ = input; _ = invalidate; }

    public void SetValue(int index, int value) { _ = index; _ = value; }
    public void SetValue(int index, uint value) { _ = index; _ = value; }
    public void SetValue(int index, bool value) { _ = index; _ = value; }
    public void SetValue(int index, float value) { _ = index; _ = value; }
    public void SetValue(int index, Vector2 value) { _ = index; _ = value; }
    public void SetValue(int index, Vector3 value) { _ = index; _ = value; }
    public void SetValue(int index, Vector4 value) { _ = index; _ = value; }

    public bool GetBoolValue(int index) { _ = index; return false; }
    public int GetIntValue(int index) { _ = index; return 0; }
    public float GetFloatValue(int index) { _ = index; return 0f; }
    public Vector2 GetVector2Value(int index) { _ = index; return default; }
    public Vector4 GetVector4Value(int index) { _ = index; return default; }

    public void Dispose() { GC.SuppressFinalize(this); }
}

public abstract class D2D1CustomShaderEffectImplBase<T> : CustomEffectBase
    where T : D2D1CustomShaderEffectImplBase<T>, new()
{
    protected ID2D1DrawInfo? drawInformation;

    protected D2D1CustomShaderEffectImplBase(byte[] shader) { _ = shader; }

    protected virtual void UpdateConstants() { }

    public virtual void MapInputRectsToOutputRect(RawRect[] inputRects, RawRect[] inputOpaqueSubRects, out RawRect outputRect, out RawRect outputOpaqueSubRect)
    {
        _ = inputOpaqueSubRects;
        outputRect = inputRects[0];
        outputOpaqueSubRect = default;
    }

    public virtual void MapOutputRectToInputRects(RawRect outputRect, RawRect[] inputRects)
    {
        for (var i = 0; i < inputRects.Length; i++) inputRects[i] = outputRect;
    }

    public virtual void MapInvalidRect(int inputIndex, RawRect invalidInputRect, out RawRect invalidOutputRect)
    {
        _ = inputIndex;
        invalidOutputRect = invalidInputRect;
    }
}
