using YukkuriMovieMaker.Commons;
using YukkuriMovieMaker.Exo;
using YukkuriMovieMaker.Player.Video;

namespace YukkuriMovieMaker.Plugin.Effects;

[AttributeUsage(AttributeTargets.Class)]
public class VideoEffectAttribute : Attribute
{
    public VideoEffectAttribute(string name, string[] categories, string[] keywords) { _ = name; _ = categories; _ = keywords; }
    public bool IsAviUtlSupported { get; set; } = true;
}

public abstract class VideoEffectBase : Animatable
{
    public abstract string Label { get; }
    public bool IsEnabled { get; set; } = true;
    public abstract IEnumerable<string> CreateExoVideoFilters(int keyFrameIndex, ExoOutputDescription exoOutputDescription);
    public abstract IVideoEffectProcessor CreateVideoEffect(IGraphicsDevicesAndContext devices);
    protected abstract IEnumerable<IAnimatable> GetAnimatables();
}
