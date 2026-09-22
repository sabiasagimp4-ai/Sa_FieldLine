// Compile-check stub of the slice of the YMM4 plugin API that Sa_FieldLine uses.
// Every signature is copied from code known to build against the real YMM4 assemblies:
// the official samples (manju-summoner/YukkuriMovieMaker4PluginSamples) and the official
// community plugin (manju-summoner/YukkuriMovieMaker.Plugin.Community). Nothing runs here.
using System.Runtime.CompilerServices;
using Vortice.Direct2D1;

namespace YukkuriMovieMaker.Commons;

public interface IAnimatable { }

public class Animation : IAnimatable
{
    public Animation(double defaultValue, double min, double max) { _ = defaultValue; _ = min; _ = max; }
    public double GetValue(int frame, int length, int fps) => 0d;
    public string ToExoString(int keyFrameIndex, string format, int fps) => string.Empty;
}

public interface IGraphicsDevicesAndContext
{
    ID2D1DeviceContext DeviceContext { get; }
}

public readonly struct TimelinePosition
{
    public int Frame => 0;
}

public class DrawDescription { }

public class EffectDescription
{
    public TimelinePosition ItemPosition => default;
    public TimelinePosition ItemDuration => default;
    public int FPS => 60;
    public DrawDescription DrawDescription => new();
}

public abstract class Animatable
{
    protected bool Set<T>(ref T field, T value, [CallerMemberName] string? propertyName = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return false;
        field = value;
        _ = propertyName;
        return true;
    }
}
