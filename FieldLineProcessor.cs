using System.Numerics;
using Vortice.Direct2D1;
using YukkuriMovieMaker.Commons;
using YukkuriMovieMaker.Player.Video;

namespace SaFieldLine;

/// <summary>
/// Sa_FieldLine のパス構成。
///
/// 「広域拡散 → 場の確定 → 流線積分 → 引き伸ばしの伝播」で必要な近傍サイズが全く違うので、
/// 1 枚のピクセルシェーダには収まらない。ここで複数のカスタムエフェクトと
/// D2D 組み込みエフェクトを繋ぐ。
///
///   P0  等倍   輝度
///   P1  等倍   σ,2σ,4σ,8σ,16σ のガウス微分を合成して輪郭と法線を出す
///   P2  等倍   全画面 RMS で正規化して閾値を掛ける
///   P3  1/2    重み ∝ σ のガウスを 6 枚重ねて ≈1/r の長距離カーネルを作る
///   P4  1/2    引力/回転/平滑化/コヒーレンス/curl を確定させる
///   P5  1/2    引き伸ばし用の放射場（φ の勾配の逆）
///   P6  等倍   流線を積分して変位サンプリング
///   P7  等倍   輪郭の色を 1 歩ずつ伝播させる（N 回の ping-pong）
///   P8  等倍   発光 / 力線描画 / 元画像を残す
///
/// 場は縮小して作るので、Radius を上げてもコストがほとんど増えない。
/// </summary>
internal sealed class FieldLineProcessor : IVideoEffectProcessor
{
    /// <summary>
    /// 場を作る解像度の分母。1/4 まで落とすと曲がりを上げた時の細部が溶けるので 1/2 にしてある。
    /// 長距離拡散はここで効くので、影響範囲を上げてもコストはほぼ変わらない。
    /// </summary>
    const int FieldDiv = 2;
    /// <summary>伝播 1 パスの移動量 [px]。2px を超えると櫛状の縞が戻る（プロトタイプで実測）。</summary>
    const float StretchStepPx = 1.5f;
    /// <summary>流線 1 ステップの移動量 [px]。3px を超えると流線がジャギる。</summary>
    const float StepPx = 1.25f;
    const int EdgeOctaves = 5;
    const int SpreadOctaves = 6;
    /// <summary>1x1 まで潰すのに要る段数。4K（1/4 で 960px）でも 10 段で足りる。</summary>
    const int ReduceLevels = 12;
    /// <summary>
    /// 伝播パスの上限。1 パスにつき等倍の RGBA16F が 1 枚要るので、
    /// D2D が中間バッファを使い回さない場合はここがメモリの上限になる。
    /// </summary>
    const int MaxStretchPasses = 256;

    const float BaseSigma = 1.1f;
    const float Align = 0.65f;
    const float AmpGamma = 0.85f;
    const float Falloff = 0.9f;
    const float LineSeedEdge = 0.7f;

    readonly IGraphicsDevicesAndContext devices;
    readonly FieldLineEffect item;
    readonly List<IDisposable> owned = [];
    readonly List<D2D1CustomShaderEffectBase> customPasses = [];
    readonly bool enabled;

    readonly LumaPass luma = null!;
    readonly EdgePass edge = null!;
    readonly StatsPass magStats = null!;
    readonly ConfidencePass confidence = null!;
    readonly SpreadPass spread = null!;
    readonly StatsPass phiStats = null!;
    readonly StatsPass vStats = null!;
    readonly FieldDirPass fieldDir = null!;
    readonly FieldAPass fieldA = null!;
    readonly FieldBPass fieldB = null!;
    readonly RadialPass radial = null!;
    readonly AdvectPass advect = null!;
    readonly PriorityPass priority = null!;
    readonly StretchInitPass stretchInit = null!;
    readonly CompositePass composite = null!;
    readonly PostPass post = null!;

    readonly ID2D1Image lumaOut = null!, edgeOut = null!, magStatsOut = null!, confOut = null!;
    readonly ID2D1Image spreadOut = null!, phiStatsOut = null!, vStatsOut = null!, dirOut = null!;
    readonly ID2D1Image fieldAOut = null!, fieldBOut = null!, radialOut = null!;
    readonly ID2D1Image advectOut = null!, prioOut = null!, initOut = null!;
    readonly ID2D1Image compositeOut = null!, postOut = null!;

    readonly Node lumaBorder = null!;
    readonly Node[] edgeBlur = new Node[EdgeOctaves];
    readonly Node[] edgeCrop = new Node[EdgeOctaves];
    readonly Node edgeQ = null!;
    readonly Node[] magReduce = new Node[ReduceLevels];
    readonly Node magNorm = null!;
    readonly Node confQ = null!, confBorder = null!;
    readonly Node[] spreadBlur = new Node[SpreadOctaves];
    readonly Node[] spreadCrop = new Node[SpreadOctaves];
    readonly Node[] phiReduce = new Node[ReduceLevels];
    readonly Node phiNorm = null!;
    readonly Node[] vReduce = new Node[ReduceLevels];
    readonly Node vNorm = null!;
    readonly Node dirBorder = null!, dirBlur = null!, dirCrop = null!;
    readonly Node prioBorder = null!, prioBlur = null!, prioCrop = null!;

    readonly List<StretchStepPass> stretchSteps = [];
    readonly List<ID2D1Image> stretchStepOutputs = [];

    ID2D1Image? input;
    bool bypass;
    int wiredReduceLevels = -1;
    int wiredStretchTail = -1;
    int wiredStretchMode = -1;

    sealed class Node(ID2D1Effect effect) : IDisposable
    {
        public ID2D1Effect Effect { get; } = effect;
        public ID2D1Image Output { get; } = effect.Output;

        public void Dispose()
        {
            Output.Dispose();
            Effect.Dispose();
        }
    }

    public FieldLineProcessor(IGraphicsDevicesAndContext devices, FieldLineEffect item)
    {
        this.devices = devices;
        this.item = item;

        // ShaderModel 非対応環境ではパススルーする
        var probe = new LumaPass(devices);
        if (!probe.IsEnabled)
        {
            probe.Dispose();
            return;
        }
        enabled = true;

        var dc = devices.DeviceContext;
        Node NewBorder() => Own(new Node(FieldLineGraph.CreateBorder(dc)));
        Node NewBlur() => Own(new Node(FieldLineGraph.CreateBlur(dc)));
        Node NewCrop() => Own(new Node(FieldLineGraph.CreateCrop(dc)));
        Node NewScale(float f) => Own(new Node(FieldLineGraph.CreateScale(dc, f)));

        luma = Keep(probe, out lumaOut);
        edge = Keep(new EdgePass(devices), out edgeOut);
        magStats = Keep(new StatsPass(devices), out magStatsOut);
        confidence = Keep(new ConfidencePass(devices), out confOut);
        spread = Keep(new SpreadPass(devices), out spreadOut);
        phiStats = Keep(new StatsPass(devices), out phiStatsOut);
        vStats = Keep(new StatsPass(devices), out vStatsOut);
        fieldDir = Keep(new FieldDirPass(devices), out dirOut);
        fieldA = Keep(new FieldAPass(devices), out fieldAOut);
        fieldB = Keep(new FieldBPass(devices), out fieldBOut);
        radial = Keep(new RadialPass(devices), out radialOut);
        advect = Keep(new AdvectPass(devices), out advectOut);
        priority = Keep(new PriorityPass(devices), out prioOut);
        stretchInit = Keep(new StretchInitPass(devices), out initOut);
        composite = Keep(new CompositePass(devices), out compositeOut);
        post = Keep(new PostPass(devices), out postOut);

        // --- P0/P1: 輝度 -> オクターブごとのぼかし -> ガウス微分の合成
        lumaBorder = NewBorder();
        lumaBorder.Effect.SetInput(0, lumaOut, true);
        for (var i = 0; i < EdgeOctaves; i++)
        {
            edgeBlur[i] = NewBlur();
            edgeBlur[i].Effect.SetInput(0, i == 0 ? lumaBorder.Output : edgeBlur[i - 1].Output, true);
            edgeCrop[i] = NewCrop();
            edgeCrop[i].Effect.SetInput(0, edgeBlur[i].Output, true);
            edge.SetInput(i, edgeCrop[i].Output, true);
        }

        // --- 正規化用の全画面 RMS。1/4 に落としてから 1x1 まで潰す。
        edgeQ = NewScale(1f / FieldDiv);
        edgeQ.Effect.SetInput(0, edgeOut, true);
        magStats.SetInput(0, edgeQ.Output, true);
        for (var i = 0; i < ReduceLevels; i++)
        {
            magReduce[i] = NewScale(0.5f);
            magReduce[i].Effect.SetInput(0, i == 0 ? magStatsOut : magReduce[i - 1].Output, true);
        }
        // 1x1 を Border(Clamp) で無限に広げると、どの位置で読んでも同じ定数が返る。
        magNorm = NewBorder();

        // --- P2: 閾値と法線
        confidence.SetInput(0, edgeOut, true);
        confidence.SetInput(1, magNorm.Output, true);

        // --- P3: 長距離拡散（1/4）
        confQ = NewScale(1f / FieldDiv);
        confQ.Effect.SetInput(0, confOut, true);
        confBorder = NewBorder();
        confBorder.Effect.SetInput(0, confQ.Output, true);
        for (var j = 0; j < SpreadOctaves; j++)
        {
            spreadBlur[j] = NewBlur();
            spreadBlur[j].Effect.SetInput(0, j == 0 ? confBorder.Output : spreadBlur[j - 1].Output, true);
            spreadCrop[j] = NewCrop();
            spreadCrop[j].Effect.SetInput(0, spreadBlur[j].Output, true);
            spread.SetInput(j, spreadCrop[j].Output, true);
        }

        phiStats.SetInput(0, spreadOut, true);
        for (var i = 0; i < ReduceLevels; i++)
        {
            phiReduce[i] = NewScale(0.5f);
            phiReduce[i].Effect.SetInput(0, i == 0 ? phiStatsOut : phiReduce[i - 1].Output, true);
        }
        phiNorm = NewBorder();

        // --- P4: 引力/回転 -> 平滑化 -> 方向と強さ
        fieldDir.SetInput(0, spreadOut, true);
        fieldDir.SetInput(1, phiNorm.Output, true);
        dirBorder = NewBorder();
        dirBorder.Effect.SetInput(0, dirOut, true);
        dirBlur = NewBlur();
        dirBlur.Effect.SetInput(0, dirBorder.Output, true);
        dirCrop = NewCrop();
        dirCrop.Effect.SetInput(0, dirBlur.Output, true);

        // コヒーレンスも全画面 RMS で正規化する。定数で割ると、輪郭がまばらな素材
        // （文字など）で場が弱くなり、効果が丸ごと沈む。
        vStats.SetInput(0, dirCrop.Output, true);
        for (var i = 0; i < ReduceLevels; i++)
        {
            vReduce[i] = NewScale(0.5f);
            vReduce[i].Effect.SetInput(0, i == 0 ? vStatsOut : vReduce[i - 1].Output, true);
        }
        vNorm = NewBorder();

        fieldA.SetInput(0, dirCrop.Output, true);
        fieldA.SetInput(1, vNorm.Output, true);
        fieldB.SetInput(0, dirCrop.Output, true);
        fieldB.SetInput(1, spreadOut, true);
        fieldB.SetInput(2, phiNorm.Output, true);
        fieldB.SetInput(3, vNorm.Output, true);

        // --- P5: 引き伸ばし専用の放射場
        radial.SetInput(0, fieldBOut, true);

        // --- P6: 流線積分
        advect.SetInput(1, fieldAOut, true);
        advect.SetInput(2, fieldBOut, true);

        // --- P7: 引き伸ばしの伝播（等倍）
        // 1/2 で伝播させると 1 パスが 1/4 のコストで済むが、帯の境界も運ぶ色も眠くなる。
        // 3 倍に拡大して比べると差がはっきり出たので等倍にしてある。
        priority.SetInput(0, confOut, true);
        prioBorder = NewBorder();
        prioBorder.Effect.SetInput(0, prioOut, true);
        prioBlur = NewBlur();
        prioBlur.Effect.SetInput(0, prioBorder.Output, true);
        prioCrop = NewCrop();
        prioCrop.Effect.SetInput(0, prioBlur.Output, true);

        stretchInit.SetInput(0, advectOut, true);
        stretchInit.SetInput(1, radialOut, true);
        stretchInit.SetInput(2, prioCrop.Output, true);
        stretchInit.SetInput(3, fieldBOut, true);

        composite.SetInput(0, advectOut, true);

        // --- P8
        post.SetInput(1, fieldAOut, true);
        post.SetInput(2, fieldBOut, true);
    }

    T Own<T>(T value) where T : IDisposable
    {
        owned.Add(value);
        return value;
    }

    T Keep<T>(T pass, out ID2D1Image output) where T : D2D1CustomShaderEffectBase
    {
        customPasses.Add(pass);
        output = pass.Output;
        owned.Add(output);
        return pass;
    }


    public DrawDescription Update(EffectDescription effectDescription)
    {
        if (!enabled || input is null)
        {
            bypass = true;
            return effectDescription.DrawDescription;
        }

        var bounds = devices.DeviceContext.GetImageLocalBounds(input);
        if (!float.IsFinite(bounds.Left) || !float.IsFinite(bounds.Top)
            || !float.IsFinite(bounds.Right) || !float.IsFinite(bounds.Bottom)
            || bounds.Right - bounds.Left < 4f || bounds.Bottom - bounds.Top < 4f)
        {
            // 無限大や極小の矩形では場が定まらないのでパススルーする
            bypass = true;
            return effectDescription.DrawDescription;
        }

        var frame = effectDescription.ItemPosition.Frame;
        var duration = effectDescription.ItemDuration.Frame;
        var fps = effectDescription.FPS;

        var strength = item.Strength.GetValue(frame, duration, fps) / 100d;
        var radius = Math.Clamp(item.Radius.GetValue(frame, duration, fps), 1d, 4000d);
        var flowLength = Math.Clamp(item.FlowLength.GetValue(frame, duration, fps), 0d, 4000d);
        var curvature = Math.Max(item.Curvature.GetValue(frame, duration, fps) / 100d, 0d);
        var swirl = Math.Clamp(item.Swirl.GetValue(frame, duration, fps) / 100d, -1d, 1d);
        var attract = Math.Clamp(item.Attract.GetValue(frame, duration, fps) / 100d, -1d, 1d);
        var threshold = Math.Clamp(item.EdgeThreshold.GetValue(frame, duration, fps) / 100d, 0d, 1d);
        var smoothness = Math.Clamp(item.Smoothness.GetValue(frame, duration, fps) / 100d, 0d, 1d);
        var detail = Math.Clamp(item.DetailScale.GetValue(frame, duration, fps) / 100d, 0d, 1d);
        var stretch = Math.Clamp(item.Stretch.GetValue(frame, duration, fps) / 100d, 0d, 1d);
        var gate = Math.Clamp(item.StretchGate.GetValue(frame, duration, fps) / 100d, 0d, 1d);
        var stretchWidth = Math.Clamp(item.StretchWidth.GetValue(frame, duration, fps), 0d, 256d);
        var pick = Math.Clamp(item.StretchPick.GetValue(frame, duration, fps), 0d, 128d);
        var stretchSwirl = Math.Clamp(item.StretchSwirl.GetValue(frame, duration, fps) / 100d, -1d, 1d);
        var lineDraw = Math.Clamp(item.LineDraw.GetValue(frame, duration, fps) / 100d, 0d, 1d);
        var lineGrain = Math.Clamp(item.LineGrain.GetValue(frame, duration, fps), 0.1d, 64d);
        var lineDensity = Math.Clamp(item.LineDensity.GetValue(frame, duration, fps) / 100d, 0d, 10d);
        var glow = Math.Clamp(item.Glow.GetValue(frame, duration, fps) / 100d, 0d, 4d);
        var shade = Math.Clamp(item.Shade.GetValue(frame, duration, fps) / 100d, -4d, 4d);
        var chroma = Math.Clamp(item.Chroma.GetValue(frame, duration, fps) / 100d, 0d, 1d);
        var preserve = Math.Clamp(item.PreserveOriginal.GetValue(frame, duration, fps) / 100d, 0d, 1d);
        var maxSteps = Math.Clamp(item.Steps, 8, 256);

        bypass = false;

        var left = MathF.Floor(bounds.Left);
        var top = MathF.Floor(bounds.Top);
        var right = MathF.Ceiling(bounds.Right);
        var bottom = MathF.Ceiling(bounds.Bottom);
        var rect = new Vector4(left, top, right, bottom);
        // 縮小後の矩形も整数に丸める。半端な値だと Crop の縁が半透明になり、
        // そこを読んだ流線が壊れる。
        var fieldRect = Shrink(rect, FieldDiv);

        // --- 全画面 RMS を取るための縮小段数。1x1 になるところで打ち切る。
        var wq = MathF.Max((right - left) / FieldDiv, 1f);
        var hq = MathF.Max((bottom - top) / FieldDiv, 1f);
        var levels = Math.Clamp((int)MathF.Ceiling(MathF.Log2(MathF.Max(wq, hq))), 1, ReduceLevels);
        if (levels != wiredReduceLevels)
        {
            magNorm.Effect.SetInput(0, magReduce[levels - 1].Output, true);
            phiNorm.Effect.SetInput(0, phiReduce[levels - 1].Output, true);
            vNorm.Effect.SetInput(0, vReduce[levels - 1].Output, true);
            wiredReduceLevels = levels;
        }

        // --- P1: detail_scale で細かい輪郭と大きい輪郭を配合する
        var mu = (1d - detail) * (EdgeOctaves - 1);
        var weights = new double[EdgeOctaves];
        var weightSum = 0d;
        for (var i = 0; i < EdgeOctaves; i++)
        {
            weights[i] = Math.Exp(-(i - mu) * (i - mu) / (2d * 0.95d * 0.95d));
            weightSum += weights[i];
        }
        for (var i = 0; i < EdgeOctaves; i++)
            weights[i] /= Math.Max(weightSum, 1e-9d);

        var prevSigma = 0d;
        for (var i = 0; i < EdgeOctaves; i++)
        {
            var target = BaseSigma * Math.Pow(2d, i);
            // σ のガウスを重ねて 2σ にするには sqrt(4-1)σ だけ足せばよい
            FieldLineGraph.SetBlurSigma(edgeBlur[i].Effect,
                (float)Math.Sqrt(Math.Max(target * target - prevSigma * prevSigma, 0d)));
            FieldLineGraph.SetCropRect(edgeCrop[i].Effect, rect);
            prevSigma = target;
        }
        edge.C0 = new Vector4((float)weights[0], (float)weights[1], (float)weights[2], (float)weights[3]);
        edge.C1 = new Vector4((float)weights[4], BaseSigma, 0f, 0f);
        edge.C2 = rect;
        edge.C5 = new Vector4(0f, 0f, 2f, 0f);

        luma.C5 = Vector4.Zero;
        // Stats のモード: 0 = B チャンネル、1 = RG の折込ベクトル
        magStats.C0 = Vector4.Zero;
        magStats.C5 = Vector4.Zero;
        phiStats.C0 = Vector4.Zero;
        phiStats.C5 = Vector4.Zero;
        vStats.C0 = new Vector4(1f, 0f, 0f, 0f);
        vStats.C5 = Vector4.Zero;
        priority.C5 = Vector4.Zero;
        // 掴めた画素は完全不透明で塗り替える。score には tie*距離 が入っているので、
        // 閾値をその半分ぶん下げて補正する。
        composite.C0 = new Vector4((float)(gate - 0.015d), (float)stretch, 0f, 0f);
        composite.C5 = Vector4.Zero;

        confidence.C0 = new Vector4((float)threshold, 0f, 0f, 0f);
        confidence.C5 = Vector4.Zero;

        // --- P3: 重み ∝ σ のガウスを 6 枚。入力 0 が最小 σ。
        var rq = Math.Max(radius / FieldDiv, 0.35d);
        var spreadWeights = new double[SpreadOctaves];
        prevSigma = 0d;
        for (var k = 0; k < SpreadOctaves; k++)
        {
            var nominal = rq * Math.Pow(0.5d, SpreadOctaves - 1 - k);
            var target = Math.Max(nominal, 0.35d);
            FieldLineGraph.SetBlurSigma(spreadBlur[k].Effect,
                (float)Math.Sqrt(Math.Max(target * target - prevSigma * prevSigma, 0d)));
            FieldLineGraph.SetCropRect(spreadCrop[k].Effect, fieldRect);
            prevSigma = target;
            spreadWeights[k] = nominal;
        }
        spread.C0 = new Vector4((float)spreadWeights[0], (float)spreadWeights[1],
                                (float)spreadWeights[2], (float)spreadWeights[3]);
        spread.C1 = new Vector4((float)spreadWeights[4], (float)spreadWeights[5], 0f, 0f);
        spread.C5 = Vector4.Zero;

        // --- P4: 引力/反発 -> 回転 -> 平滑化
        var attractSigma = Math.Max(radius * 0.16d, 2.5d) / FieldDiv;
        var attractStep = Math.Max(attractSigma, 1d);
        fieldDir.C0 = new Vector4((float)attract, (float)swirl, (float)attractStep, (float)attractSigma);
        fieldDir.C2 = fieldRect;
        fieldDir.C5 = new Vector4(0f, 0f, (float)Math.Ceiling(attractStep) + 1f, 0f);

        // 近傍のディテールを壊さない程度に抑える（ここを強くすると単なるぐにゃぐにゃになる）
        var smoothSigma = (0.6d + smoothness * (2d + 0.085d * radius)) / FieldDiv;
        FieldLineGraph.SetBlurSigma(dirBlur.Effect, (float)smoothSigma);
        FieldLineGraph.SetCropRect(dirCrop.Effect, fieldRect);

        var curlSigma = Math.Max(1.5d, 0.05d * radius) / FieldDiv;
        var curlStep = Math.Max(curlSigma, 1d);
        fieldA.C0 = new Vector4((float)curlStep, (float)curlSigma, 0f, 0f);
        fieldA.C2 = fieldRect;
        fieldA.C5 = new Vector4(0f, 0f, (float)Math.Ceiling(curlStep) + 1f, 0f);

        var turbSigma = 1.2d / FieldDiv;
        var turbStep = Math.Max(turbSigma, 1d);
        fieldB.C0 = new Vector4((float)turbStep, (float)turbSigma, Falloff, AmpGamma);
        fieldB.C2 = fieldRect;
        fieldB.C5 = new Vector4(0f, 0f, (float)Math.Ceiling(turbStep) + 1f, 0f);

        var radialSigma = Math.Max(radius * 0.10d, 2d) / FieldDiv;
        var radialStep = Math.Max(radialSigma, 1d);
        radial.C0 = new Vector4((float)radialStep, (float)stretchSwirl, 0f, 0f);
        radial.C2 = fieldRect;
        radial.C5 = new Vector4(0f, 0f, (float)Math.Ceiling(radialStep) + 1f, 0f);

        // --- P6: 歩幅を px 基準で決める（ステップが粗いと流線がジャギる）
        var steps = Math.Clamp((int)Math.Round(flowLength / StepPx), 8, maxSteps);
        var hstep = flowLength / steps;
        var stepsRed = steps;
        var stepsBlue = steps;
        if (chroma > 1e-4d)
        {
            stepsRed = Math.Clamp((int)Math.Round(steps * (1d + 0.35d * chroma)), 1, 512);
            stepsBlue = Math.Clamp((int)Math.Round(steps * (1d - 0.35d * chroma)), 1, steps);
        }
        advect.C0 = new Vector4(steps, (float)hstep, Align, (float)curvature);
        advect.C1 = new Vector4((float)strength, (float)chroma, (float)shade, 0f);
        advect.C2 = rect;
        advect.C3 = fieldRect;
        advect.C4 = new Vector4(1f / FieldDiv, stepsRed, stepsBlue, 0f);
        // 流線は遠くまで走るので、元画像と場は全体を要求する
        advect.C5 = new Vector4(0f, 0f, 0f, 7f);

        // --- P7: 引き伸ばし
        var stretchOn = stretch > 1e-4d && flowLength > 0.5d;
        if (stretchOn)
        {
            var passes = Math.Clamp((int)Math.Round(flowLength / StretchStepPx), 8,
                                    Math.Min(maxSteps, MaxStretchPasses));
            EnsureStretchSteps(passes);

            var stepPx = flowLength / passes;
            var radialScale = 1f / FieldDiv;
            // score = 優先度 - tie * 距離。1 歩ぶんのペナルティは tie(=0.03/total) * stepPx。
            var tie = 0.03d / passes;

            FieldLineGraph.SetBlurSigma(prioBlur.Effect, (float)stretchWidth);
            FieldLineGraph.SetCropRect(prioCrop.Effect, rect);

            // conf は輪郭のスケールぶん太い帯になるので、色を拾う探索距離は
            // その帯を跨げるだけ要る。足りないと帯の外縁が背景色を運ぶ種になり、
            // 本来の輪郭色を塞いで帯が眠くなる。
            var edgeSigma = BaseSigma * Math.Pow(2d, mu);
            var pickRange = Math.Max(pick, 2d * edgeSigma);
            stretchInit.C0 = new Vector4((float)pickRange, radialScale, 0f, 0f);
            stretchInit.C2 = rect;
            stretchInit.C3 = fieldRect;
            // 伝播は 100 パス近く連なるので、入力は「一部を広げて」ではなく「全体」を要求する。
            // 広げる形だと、D2D がタイルに分けて描いた時に上流の連鎖が
            // タイルごとに描き直され、深さぶんだけ無駄が積み上がる。
            stretchInit.C5 = new Vector4(0f, 0f, 0f, 11f);   // 入力 0,1,3 は全体が要る

            var stepC0 = new Vector4((float)stepPx, radialScale, (float)tie, 0f);
            var stepC5 = new Vector4(0f, 0f, 0f, 3f);
            for (var i = 0; i < passes; i++)
            {
                var pass = stretchSteps[i];
                pass.C0 = stepC0;
                pass.C2 = rect;
                pass.C3 = fieldRect;
                pass.C5 = stepC5;
            }

            if (wiredStretchTail != passes)
            {
                composite.SetInput(1, stretchStepOutputs[passes - 1], true);
                wiredStretchTail = passes;
            }
        }

        var stretchMode = stretchOn ? 1 : 0;
        if (stretchMode != wiredStretchMode)
        {
            post.SetInput(0, stretchOn ? compositeOut : advectOut, true);
            wiredStretchMode = stretchMode;
        }

        // --- P8
        var glowTotal = flowLength * 2.2d;
        var glowSteps = Math.Clamp((int)Math.Round(glowTotal / StepPx), 8, maxSteps);
        var lineTotal = Math.Max(flowLength * 1.8d, 34d);
        var lineSteps = Math.Clamp((int)Math.Round(lineTotal), 8, Math.Min(maxSteps * 2, 220));
        post.C0 = new Vector4((float)glow, (float)lineDraw, (float)lineDensity, (float)lineGrain);
        post.C1 = new Vector4(LineSeedEdge, (float)preserve, Align, (float)curvature);
        post.C2 = rect;
        post.C3 = fieldRect;
        post.C4 = new Vector4(1f / FieldDiv, glowSteps, (float)(glowTotal / glowSteps), lineSteps);
        // 場（入力 1,2）は解像度が違うので常に全体。入力 0 は発光の流線が拾いに行く時だけ。
        var postWhole = 2f + 4f + (glow > 1e-4d ? 1f : 0f);
        post.C5 = new Vector4((float)(lineTotal / lineSteps), (float)lineTotal, 0f, postWhole);

        return effectDescription.DrawDescription;
    }

    /// <summary>矩形を 1/div にして整数へ内側に丸める。</summary>
    static Vector4 Shrink(Vector4 rect, int div)
        => new(MathF.Ceiling(rect.X / div), MathF.Ceiling(rect.Y / div),
               MathF.Floor(rect.Z / div), MathF.Floor(rect.W / div));

    void EnsureStretchSteps(int count)
    {
        while (stretchSteps.Count < count)
        {
            var pass = new StretchStepPass(devices);
            customPasses.Add(pass);
            var image = pass.Output;
            owned.Add(image);
            pass.SetInput(0, stretchSteps.Count == 0 ? initOut : stretchStepOutputs[^1], true);
            pass.SetInput(1, radialOut, true);
            stretchSteps.Add(pass);
            stretchStepOutputs.Add(image);
        }
    }

    public ID2D1Image Output
    {
        get
        {
            if (enabled && !bypass)
                return postOut;
            return input ?? throw new InvalidOperationException("入力が未設定です。");
        }
    }

    public void SetInput(ID2D1Image? image)
    {
        input = image;
        if (!enabled)
            return;
        luma.SetInput(0, image, true);
        advect.SetInput(0, image, true);
        post.SetInput(3, image, true);
    }

    public void ClearInput() => SetInput(null);

    public void Dispose()
    {
        ClearInput();
        for (var i = owned.Count - 1; i >= 0; i--)
            owned[i].Dispose();
        owned.Clear();
        for (var i = customPasses.Count - 1; i >= 0; i--)
            customPasses[i].Dispose();
        customPasses.Clear();
    }
}
