using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using YukkuriMovieMaker.Commons;
using YukkuriMovieMaker.Controls;
using YukkuriMovieMaker.Exo;
using YukkuriMovieMaker.Player.Video;
using YukkuriMovieMaker.Plugin.Effects;

namespace SaFieldLine;

/// <summary>
/// エッジを線ではなく「力場の発生源」として扱う映像エフェクト。
///
/// 輪郭を検出 → 法線を周囲へ拡散 → 場同士の干渉で向きを曲げる → 流線に沿って画素を運ぶ。
/// ノイズではなく輪郭同士の干渉で曲げるのが肝で、ここを雑にすると単なるぐにゃぐにゃ変形になる。
/// </summary>
[VideoEffect("Sa_FieldLine", ["フィルタ"],
    ["Sa_FieldLine", "力線", "field line", "ベクトル場", "流線", "引き伸ばし", "磁力線", "電気力線"],
    IsAviUtlSupported = false)]
public sealed class FieldLineEffect : VideoEffectBase
{
    public override string Label => "Sa_FieldLine";

    [Display(Name = "強さ", Description = "流線に沿って画素をどれだけ動かすか", Order = 0)]
    [AnimationSlider("F1", "%", 0, 200)]
    public Animation Strength { get; } = new(60, 0, 1000);

    [Display(Name = "影響範囲", Description = "輪郭の力がどこまで届くか。大きいほど場が滑らかで大きなうねりになります", Order = 1)]
    [AnimationSlider("F1", "px", 8, 600)]
    public Animation Radius { get; } = new(150, 1, 4000);

    [Display(Name = "流線の長さ", Description = "画素をどこまで運ぶか。引き伸ばしの到達距離もこれで決まります", Order = 2)]
    [AnimationSlider("F1", "px", 0, 600)]
    public Animation FlowLength { get; } = new(140, 0, 4000);

    [Display(Name = "曲がり", Description = "場同士の干渉（curl）でどれだけ流れを曲げるか", Order = 3)]
    [AnimationSlider("F1", "%", 0, 500)]
    public Animation Curvature { get; } = new(100, 0, 2000);

    [Display(Name = "回転", Description = "100%で流れが輪郭に巻き付き、磁力線のようになります", Order = 4)]
    [AnimationSlider("F1", "%", -100, 100)]
    public Animation Swirl { get; } = new(0, -100, 100);

    [Display(Name = "引力/反発", Description = "正で輪郭へ吸い寄せ、負で輪郭から放射します", Order = 5)]
    [AnimationSlider("F1", "%", -100, 100)]
    public Animation Attract { get; } = new(0, -100, 100);

    [Display(Name = "エッジ閾値", Description = "これより弱い輪郭は使いません。上げると細かい輪郭が消えます", Order = 6)]
    [AnimationSlider("F1", "%", 0, 100)]
    public Animation EdgeThreshold { get; } = new(10, 0, 100);

    [Display(Name = "滑らかさ", Description = "ベクトル場をどれだけ均すか。動画では高め(50%前後)が安全です", Order = 7)]
    [AnimationSlider("F1", "%", 0, 100)]
    public Animation Smoothness { get; } = new(40, 0, 100);

    [Display(Name = "輪郭の細かさ", Description = "0%で大きい輪郭だけ、100%で細かい輪郭だけを使います", Order = 8)]
    [AnimationSlider("F1", "%", 0, 100)]
    public Animation DetailScale { get; } = new(50, 0, 100);

    [Display(Name = "引き伸ばし", Description = "輪郭の色を外向きに引き伸ばします。届いた画素は完全不透明で塗り替わります", Order = 9)]
    [AnimationSlider("F1", "%", 0, 100)]
    public Animation Stretch { get; } = new(0, 0, 100);

    [Display(Name = "引き伸ばし閾値", Description = "これ未満しか輪郭を掴めなかった画素は元のまま残ります", Order = 10)]
    [AnimationSlider("F1", "%", 0, 100)]
    public Animation StretchGate { get; } = new(35, 0, 100);

    [Display(Name = "引き伸ばしの太さ", Description = "運ぶ色のストローク幅。優先度マップのぼかし量です", Order = 11)]
    [AnimationSlider("F1", "px", 0, 64)]
    public Animation StretchWidth { get; } = new(0, 0, 256);

    [Display(Name = "色を拾う位置", Description = "輪郭よりどれだけ内側の色を引き出すか。線画の黒ではなく面の色を出したい時に上げます", Order = 12)]
    [AnimationSlider("F1", "px", 0, 32)]
    public Animation StretchPick { get; } = new(3, 0, 128);

    [Display(Name = "引き伸ばしのひねり", Description = "放射をひねります。0%で真っ直ぐ外向きです", Order = 13)]
    [AnimationSlider("F1", "%", -100, 100)]
    public Animation StretchSwirl { get; } = new(0, -100, 100);

    [Display(Name = "力線を描く", Description = "場そのものを線として重ねます（砂鉄のような見た目）", Order = 14)]
    [AnimationSlider("F1", "%", 0, 100)]
    public Animation LineDraw { get; } = new(0, 0, 100);

    [Display(Name = "力線の粒", Description = "線の太さ", Order = 15)]
    [AnimationSlider("F2", "px", 0.3, 8)]
    public Animation LineGrain { get; } = new(1.4, 0.1, 64);

    [Display(Name = "力線の濃さ", Description = "線のコントラスト", Order = 16)]
    [AnimationSlider("F1", "%", 0, 300)]
    public Animation LineDensity { get; } = new(100, 0, 1000);

    [Display(Name = "発光", Description = "明るい部分が流線に沿って伸びて光ります", Order = 17)]
    [AnimationSlider("F1", "%", 0, 100)]
    public Animation Glow { get; } = new(0, 0, 400);

    [Display(Name = "明度差", Description = "流線に沿って明暗をつけ、立体感を出します", Order = 18)]
    [AnimationSlider("F1", "%", -100, 100)]
    public Animation Shade { get; } = new(0, -400, 400);

    [Display(Name = "色収差", Description = "RGB で流線の長さを変えてずらします", Order = 19)]
    [AnimationSlider("F1", "%", 0, 100)]
    public Animation Chroma { get; } = new(0, 0, 100);

    [Display(Name = "元画像を残す", Description = "最後に元の映像を混ぜ戻します", Order = 20)]
    [AnimationSlider("F1", "%", 0, 100)]
    public Animation PreserveOriginal { get; } = new(0, 0, 100);

    [Display(Name = "ステップ数", Description = "流線と引き伸ばしの最大パス数。下げると軽くなりますが、長い流線でジャギが出ます", Order = 21)]
    [Range(8, 256)]
    [DefaultValue(96)]
    [TextBoxSlider("F0", "", 8, 256)]
    public int Steps { get => steps; set => Set(ref steps, Math.Clamp(value, 8, 256)); }
    int steps = 96;

    public override IEnumerable<string> CreateExoVideoFilters(int keyFrameIndex, ExoOutputDescription exoOutputDescription) => [];

    public override IVideoEffectProcessor CreateVideoEffect(IGraphicsDevicesAndContext devices) => new FieldLineProcessor(devices, this);

    protected override IEnumerable<IAnimatable> GetAnimatables() =>
    [
        Strength, Radius, FlowLength, Curvature, Swirl, Attract, EdgeThreshold, Smoothness, DetailScale,
        Stretch, StretchGate, StretchWidth, StretchPick, StretchSwirl,
        LineDraw, LineGrain, LineDensity, Glow, Shade, Chroma, PreserveOriginal,
    ];
}
