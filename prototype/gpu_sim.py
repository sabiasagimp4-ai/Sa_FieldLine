"""gpu_sim.py — Direct2D 実装と 1:1 対応するパイプラインのシミュレーション。

fieldline.py は研究用のリファレンス実装で、全画素の percentile など
GPU では使えない演算を含む。こちらは Direct2D で書ける演算だけを使う:

  - ガウスぼかし          -> Border(Clamp) + GaussianBlur + Crop
  - 1/2 ずつの箱平均縮小   -> Scale(0.5) の連鎖（線形補間の 2x2 平均）
  - バイリニア拡大        -> Scale
  - 画素ごとの四則とバイリニアサンプリング -> ピクセルシェーダ

グローバルな percentile が使えないので、正規化はすべて
「大きな σ の局所 RMS」に置き換える。カバレッジ（1 を同じ σ でぼかしたもの）で
割るので、画面端でも値が落ちない。

HLSL はこのファイルの式をそのまま移植する。数値を変えるときは
まずここを直して見た目を確認すること。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates

EPS = 1e-8

# --- 実装定数（HLSL 側と一致させる） -------------------------------------
FIELD_DIV = 2          # 場を作る解像度（1/2）。1/4 だと曲がりを上げた時の細部が溶ける
STRETCH_DIV = 1        # 引き伸ばしの伝播解像度（等倍）。1/2 にすると目に見えて眠くなる
STRETCH_STEP_PX = 1.5  # 伝播 1 パスの移動量 [元画像 px]
EDGE_OCTAVES = 5
SPREAD_OCTAVES = 6

# 局所 RMS -> リファレンスの percentile へ合わせる係数（calibrate.py で実測）
K_MAG = 3.50           # p99(mag)  / rms(mag)
K_PHI = 1.95           # p98(phi)  / rms(phi)
K_COH = 3.10           # p99(|v|) / rms(|v|)
K_CURL = 0.014         # p97(curl)
K_TURB = 0.08          # p88(turb) より大きめ。smoothness を上げた時だけ緩む
LINE_SEED_EDGE = 0.7   # 力線の種を輪郭近くへ寄せる度合い
PICK_GAIN = 6.0        # 色を拾う時、φ の登り幅に対する重みの立ち上がり
PICK_OWN = 0.02        # 登り先が無い時に自分の色を残すための基礎重み
K_GRAD = 0.30          # p99(|grad phi| * gs / phi_scale)
PRIO_W = 0.65          # 優先度に輪郭の強さを効かせる割合（0 だと全部同点になる）
PRIO_K = 0.70          # 輪郭の強さ（画面平均＝1）-> 優先度の傾き。1.43 倍で頭打ち
PRIO_SMOOTH = 1.0      # 輪郭の強さを均す幅（輪郭の帯の幅に対する倍率）
TIE_BASE = 0.03        # 同点の時に近い輪郭を採るための最小の距離ペナルティ

# 較正用に build_field が途中経過を残す（calibrate_gpu.py が読む）
LAST: dict = {}


def _clampsamp(img, y, x):
    coords = np.stack([y.ravel(), x.ravel()])
    if img.ndim == 2:
        return map_coordinates(img, coords, order=1, mode="nearest").reshape(y.shape).astype(np.float32)
    out = [map_coordinates(img[..., c], coords, order=1, mode="nearest").reshape(y.shape)
           for c in range(img.shape[2])]
    return np.stack(out, -1).astype(np.float32)


def d2d_blur(a, sigma):
    """Border(Clamp) -> GaussianBlur -> Crop に相当。"""
    if sigma < 0.05:
        return a.astype(np.float32)
    if a.ndim == 3:
        return np.stack([gaussian_filter(a[..., c], sigma, mode="nearest") for c in range(a.shape[2])],
                        -1).astype(np.float32)
    return gaussian_filter(a, sigma, mode="nearest").astype(np.float32)


def d2d_half(a):
    """Scale(0.5, Linear) = 2x2 の箱平均。奇数の端は切り捨てる。"""
    h, w = a.shape[:2]
    fy = 2 if h >= 2 else 1
    fx = 2 if w >= 2 else 1
    hh, ww = h // fy, w // fx
    b = a[:hh * fy, :ww * fx]
    shape = (hh, fy, ww, fx) + a.shape[2:]
    return b.reshape(shape).mean((1, 3)).astype(np.float32)


def d2d_down(a, div):
    while div > 1:
        a = d2d_half(a)
        div //= 2
    return a


def d2d_up(a, shape):
    """Scale(Linear) による拡大。"""
    h, w = shape
    sh, sw = a.shape[:2]
    yy, xx = np.meshgrid(np.arange(h, dtype=np.float32), np.arange(w, dtype=np.float32), indexing="ij")
    sy = (yy + 0.5) * sh / h - 0.5
    sx = (xx + 0.5) * sw / w - 0.5
    return _clampsamp(a, sy, sx)


def _grid(shape):
    h, w = shape
    return np.meshgrid(np.arange(h, dtype=np.float32), np.arange(w, dtype=np.float32), indexing="ij")


def smoothstep(a, b, x):
    t = np.clip((x - a) / max(b - a, EPS), 0.0, 1.0)
    return (t * t * (3.0 - 2.0 * t)).astype(np.float32)


def _dx(a, r):
    """中心差分（r texel 間隔）。GPU では 2 サンプル。"""
    yy, xx = _grid(a.shape[:2])
    return (_clampsamp(a, yy, xx + r) - _clampsamp(a, yy, xx - r)) / (2.0 * r)


def _dy(a, r):
    yy, xx = _grid(a.shape[:2])
    return (_clampsamp(a, yy + r, xx) - _clampsamp(a, yy - r, xx)) / (2.0 * r)


def d2d_reduce(a):
    """Scale(0.5) を 1x1 になるまで重ねる = 全画素平均。

    局所ぼかしで正規化してはいけない。平坦な領域では分母が小さくなり、
    そこだけ効果が最大になってしまう（＝画面全体がぐにゃぐにゃになる）。
    正規化はリファレンスと同じく画面全体の統計で行う。
    """
    while a.shape[0] > 1 or a.shape[1] > 1:
        a = d2d_half(a)
    return a


def _global_rms(x):
    """(x^2, 1) を 1x1 まで縮小してから拡大した定数テクスチャ、の RMS。"""
    st = np.stack([x * x, np.ones_like(x)], -1)
    r = d2d_reduce(st).reshape(2)
    return float(np.sqrt(max(r[0] / max(r[1], 1e-4), 0.0)))


@dataclass
class GpuParams:
    strength: float = 1.0
    radius: float = 150.0
    curvature: float = 1.0
    swirl: float = 0.0
    attract: float = 0.0
    flow_length: float = 140.0
    edge_threshold: float = 0.25
    smoothness: float = 0.40
    detail_scale: float = 0.30
    preserve_original: float = 0.0

    stretch: float = 0.0
    stretch_gate: float = 0.35
    stretch_pick: float = 3.0
    stretch_scale: float = 0.0
    stretch_swirl: float = 0.0
    stretch_decay: float = 0.6   # 近さの優先。0 だと全部が flow_length まで届いて円盤になる
    stretch_jitter: float = 0.0  # 筆の毛。流線ごとに届く距離をばらつかせる

    glow: float = 0.0
    shade: float = 0.0
    chroma: float = 0.0
    line_draw: float = 0.0
    line_grain: float = 1.4
    line_density: float = 1.0

    field_div: int = FIELD_DIV   # 場を作る解像度の分母
    stretch_div: int = STRETCH_DIV  # 引き伸ばしの伝播解像度の分母
    steps: int = 192             # 流線積分の最大ステップ数
    step_px: float = 1.25
    stretch_steps: int = 192     # 伝播の最大パス数
    base_sigma: float = 1.1
    align: float = 0.65
    amp_gamma: float = 0.85
    falloff: float = 0.9


# ==========================================================  P0..P3 : 場
def build_field(rgb, p: GpuParams):
    """P0-P3 に相当。戻り値は 1/FIELD_DIV 解像度のテクスチャ群。"""
    h, w = rgb.shape[:2]
    Q = p.field_div

    # --- P0: 輝度（プリマルチプライ済みの色をそのまま使う）
    lum = (0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]).astype(np.float32)

    # --- P1: 多重スケールのガウス微分
    k = np.arange(EDGE_OCTAVES, dtype=np.float32)
    mu = (1.0 - float(np.clip(p.detail_scale, 0.0, 1.0))) * (EDGE_OCTAVES - 1)
    wk = np.exp(-((k - mu) ** 2) / (2.0 * 0.95 ** 2))
    wk /= wk.sum()

    gx = np.zeros_like(lum); gy = np.zeros_like(lum); mag = np.zeros_like(lum)
    cur = lum
    prev_s = 0.0
    for i in range(EDGE_OCTAVES):
        s = p.base_sigma * (2.0 ** i)
        add = np.sqrt(max(s * s - prev_s * prev_s, 0.0))
        cur = d2d_blur(cur, add)
        prev_s = s
        ex = _dx(cur, 1.0) * s        # Lindeberg γ 正規化
        ey = _dy(cur, 1.0) * s
        gx += wk[i] * ex
        gy += wk[i] * ey
        mag += wk[i] * np.hypot(ex, ey)

    # --- 正規化（1/Q に落としてから大 σ の局所 RMS）
    mag_q = d2d_down(mag, Q)
    mag_scale = max(K_MAG * _global_rms(mag_q), 1e-3)

    # --- P2: conf と法線
    mag_n = mag / mag_scale
    knee = 0.06 + 0.35 * (1.0 - p.edge_threshold)
    conf = smoothstep(p.edge_threshold, p.edge_threshold + knee, mag_n)
    gv = np.hypot(gx, gy) + EPS
    nx = gx / gv
    ny = gy / gv
    confn = np.stack([conf * nx, conf * ny, conf], -1).astype(np.float32)

    # --- P3: 長距離拡散（1/Q）
    cq = d2d_down(confn, Q)
    rq = max(p.radius / Q, 0.35)
    acc = np.zeros_like(cq); wsum = 0.0
    cur = cq; prev_s = 0.0
    for j in range(SPREAD_OCTAVES - 1, -1, -1):        # 小さい σ から順に重ねる
        s = max(rq * (0.5 ** j), 0.35)
        add = np.sqrt(max(s * s - prev_s * prev_s, 0.0))
        cur = d2d_blur(cur, add)
        prev_s = s
        wj = rq * (0.5 ** j)
        acc += wj * cur
        wsum += wj
    spread = acc / max(wsum, EPS)
    Vx, Vy, phi = spread[..., 0], spread[..., 1], spread[..., 2]

    phi_scale = max(K_PHI * _global_rms(phi), 1e-4)
    phi_n = np.clip(phi / phi_scale, 0.0, 1.0).astype(np.float32)
    vx = Vx / phi_scale
    vy = Vy / phi_scale

    # --- 引力 / 反発: φ の勾配
    if abs(p.attract) > 1e-4:
        gs = max(p.radius * 0.16, 2.5) / Q
        r = max(gs, 1.0)
        px_ = _dx(phi, r) * gs / phi_scale / K_GRAD
        py_ = _dy(phi, r) * gs / phi_scale / K_GRAD
        vx = vx + p.attract * px_
        vy = vy + p.attract * py_

    # --- swirl
    if abs(p.swirl) > 1e-4:
        th = p.swirl * (np.pi / 2.0)
        c, s = np.cos(th), np.sin(th)
        vx, vy = c * vx - s * vy, s * vx + c * vy

    # HLSL 側は符号つきの値を [0,1] に折り込んで持つ（8bit バッファ対策）。
    # アフィン変換なので数値は変わらないが、折り込み範囲 ±2 のクリップだけは効く。
    vx = np.clip(vx, -2.0, 2.0)
    vy = np.clip(vy, -2.0, 2.0)

    # --- 場の平滑化
    sig = (0.6 + p.smoothness * (2.0 + 0.085 * p.radius)) / Q
    vx = d2d_blur(vx, sig); vy = d2d_blur(vy, sig)

    amp_raw = np.hypot(vx, vy)
    # コヒーレンスも全画面 RMS で正規化する。定数で割ると、輪郭がまばらな素材
    # （文字など）で場が弱くなり、効果が丸ごと沈む。
    coh_scale = max(K_COH * _global_rms(amp_raw), 1e-4)
    coh = np.clip(amp_raw / coh_scale, 0.0, 1.0)
    env = phi_n ** (0.35 + 1.3 * p.falloff)
    flow = (0.30 + 0.70 * np.sqrt(coh)).astype(np.float32)
    amp = (((0.10 + 0.90 * env) * (0.35 + 0.65 * coh)) ** p.amp_gamma).astype(np.float32)

    inv = 1.0 / (amp_raw + EPS)
    dx = (vx * inv).astype(np.float32)
    dy = (vy * inv).astype(np.float32)

    # --- curl（干渉によるねじれ）
    cs = max(1.5, 0.05 * p.radius) / Q
    r = max(cs, 1.0)
    curl = (_dx(vy, r) - _dy(vx, r)) * cs / K_CURL
    curl = np.clip(curl, -3.0, 3.0).astype(np.float32)

    # --- res（場が速く回りすぎる所は流線を解像できない）
    ts = 1.2 / Q
    r = max(ts, 1.0)
    turb = (np.hypot(_dx(dx, r), _dy(dx, r)) + np.hypot(_dx(dy, r), _dy(dy, r))) * ts / K_TURB
    res = (1.0 / (1.0 + (0.85 * turb) ** 2)).astype(np.float32)


    LAST.clear()
    LAST.update(mag=mag, mag_q=mag_q, rms_mag=_global_rms(mag_q),
                phi=phi, rms_phi=_global_rms(phi),
                amp_raw=amp_raw, curl_raw=curl * K_CURL, turb_raw=turb * K_TURB,
                phi_scale=phi_scale)

    # --- 引き伸ばし用の放射場（-grad phi）
    gs = max(p.radius * 0.10, 2.0) / Q
    r = max(gs, 1.0)
    rx = -_dx(phi_n, r)
    ry = -_dy(phi_n, r)
    if abs(p.stretch_swirl) > 1e-4:
        th = p.stretch_swirl * (np.pi / 2.0)
        c, sn = np.cos(th), np.sin(th)
        rx, ry = c * rx - sn * ry, sn * rx + c * ry
    m = np.hypot(rx, ry) + EPS
    rx = (rx / m).astype(np.float32); ry = (ry / m).astype(np.float32)

    return {
        "A": np.stack([dx, dy, flow, curl], -1).astype(np.float32),   # FieldA
        # R は素の amp。res の掛け方は用途ごとに違うので、ここでは掛けない。
        #   変位: amp * (0.55 + 0.45*res) / 発光: amp / 力線: amp * res
        "B": np.stack([amp, phi_n, res, np.zeros_like(res)], -1).astype(np.float32),
        "R": np.stack([rx, ry], -1).astype(np.float32),               # Radial
        "conf": conf,
        # 輪郭の「強さ」。conf は閾値で飽和するので、優先度に使うにはこちらが要る。
        # GPU 側は Confidence の空いていた .a に載せて運ぶ（パスは増えない）。
        # 1/4 に縮めて [0,1] に収めるのは、中間バッファが 8bit しか取れない環境でも
        # 強い輪郭どうしの差が潰れないようにするため。優先度は画面平均との比で
        # 使うので、この 1/4 は約分されて消える。
        "magn": np.clip(mag_n * 0.25, 0.0, 1.0).astype(np.float32),
        "shape": (h, w),
    }


def pick_range(p: "GpuParams") -> float:
    """色を拾うために上流を探す距離 [px]。

    conf は輪郭のスケール（= detail_scale が決めるオクターブの σ）ぶん太い帯になる。
    その帯を跨げない距離では、帯の外縁が背景色を運ぶ種になってしまう。
    """
    mu = (1.0 - float(np.clip(p.detail_scale, 0.0, 1.0))) * (EDGE_OCTAVES - 1)
    edge_sigma = p.base_sigma * (2.0 ** mu)
    return max(p.stretch_pick, 2.0 * edge_sigma)


def _step_count(length, step_px, cap):
    return int(np.clip(round(abs(length) / max(step_px, 0.2)), 8, cap))


# ==========================================================  P4 : 流線変位
def advect(rgb, F, p: GpuParams):
    h, w = rgb.shape[:2]
    Q = p.field_div
    A = F["A"]; B = F["B"]
    yy, xx = _grid((h, w))

    n = _step_count(p.flow_length, p.step_px, p.steps)
    hstep = p.flow_length / n
    # 色収差: 同じ経路の別の位置を使う（3 回追わない）
    fr = 1.0 + 0.35 * p.chroma
    fb = 1.0 - 0.35 * p.chroma
    nmax = int(np.ceil(n * max(fr, 1.0)))

    amp_raw = d2d_up(B[..., 0], (h, w))
    res_up = d2d_up(B[..., 2], (h, w))
    amp_eff = amp_raw * (0.55 + 0.45 * res_up)
    k_all = p.strength * amp_eff

    px = xx.copy(); py = yy.copy()
    a0 = _clampsamp(A, yy / Q, xx / Q)
    d_x = (-a0[..., 0]).copy(); d_y = (-a0[..., 1]).copy()

    caps = {}
    targets = sorted({max(int(round(n * fb)), 1), n, min(nmax, int(round(n * fr)))})
    for i in range(nmax):
        a = _clampsamp(A, py / Q, px / Q)
        fx = -a[..., 0]; fy = -a[..., 1]
        gate = a[..., 2]; cu = a[..., 3]
        flip = np.where(fx * d_x + fy * d_y < 0.0, -1.0, 1.0).astype(np.float32)
        fx *= flip; fy *= flip
        ang = np.arctan2(d_x * fy - d_y * fx, d_x * fx + d_y * fy)
        turn = p.align * ang + p.curvature * cu * hstep * 0.09
        ct, st = np.cos(turn), np.sin(turn)
        d_x, d_y = ct * d_x - st * d_y, st * d_x + ct * d_y
        dn = np.hypot(d_x, d_y) + EPS
        d_x /= dn; d_y /= dn
        step = hstep * gate
        px = px + d_x * step
        py = py + d_y * step
        if (i + 1) in targets:
            caps[i + 1] = (py.copy(), px.copy())

    def fetch(idx):
        ey, ex = caps[idx]
        return yy + (ey - yy) * k_all, xx + (ex - xx) * k_all

    sy, sx = fetch(n)
    if p.chroma > 1e-4:
        ry_, rx_ = fetch(targets[-1])
        by_, bx_ = fetch(targets[0])
        out = np.stack([_clampsamp(rgb[..., 0], ry_, rx_),
                        _clampsamp(rgb[..., 1], sy, sx),
                        _clampsamp(rgb[..., 2], by_, bx_)], -1)
    else:
        out = _clampsamp(rgb, sy, sx)

    if p.shade > 1e-4:
        sh = _clampsamp(amp_raw, sy, sx) - amp_raw
        out = out * (1.0 + p.shade * 1.2 * sh[..., None])
    return out.astype(np.float32), (sy, sx)


# ==========================================================  P5 : 引き伸ばし
def stretch(colour, F, p: GpuParams):
    """1/STRETCH_DIV 解像度で ping-pong 伝播させ、等倍へ戻す。"""
    h, w = colour.shape[:2]
    S = p.stretch_div
    Q = p.field_div
    col0 = d2d_down(colour, S)
    conf_s = d2d_down(F["conf"], S)
    lh, lw = col0.shape[:2]
    yy, xx = _grid((lh, lw))

    # 放射場を 1/S へ拡大（場は 1/Q なので Q/S 倍）
    R = d2d_up(F["R"], (lh, lw))
    m = np.hypot(R[..., 0], R[..., 1]) + EPS
    dx = R[..., 0] / m; dy = R[..., 1] / m

    # conf は閾値で飽和するので、これだけを優先度にすると「どの輪郭も同点 1.0」になる。
    # 同点なら距離ペナルティで必ず一番近い輪郭が勝つので、外側の輪郭が外を丸ごと取り、
    # 内側の輪郭の色は一歩も外へ出られない（強さを逆転させても出られないことを実測）。
    # 輪郭の強さを残しておくと、強い内側の輪郭が弱い外側の輪郭を押しのけて出てくる。
    #
    # ただし画素ごとの強さをそのまま competition に使うと、隣り合う画素が別の輪郭に
    # 当たって櫛状の縞が戻る。帯の幅で **conf を重みにした平均** を取り、
    # 「この輪郭の強さ」にしてから使う。ただ平滑化すると帯の山が削れて
    # 塗る範囲まで痩せるが、重み付き平均なら山の高さは保たれる。
    # 強さは **絶対値ではなく画面平均との比** で持つ。絶対値で持つと、正規化の
    # 係数がずれている素材で強さが丸ごと上下して、届く距離まで変わってしまう。
    # 比にすれば正規化の係数は約分されて消える（K_MAG などと同じ考え方）。
    sg = PRIO_SMOOTH * pick_range(p) * 0.5
    mc = F["magn"] * F["conf"]
    region = d2d_blur(mc, sg) / np.maximum(d2d_blur(F["conf"], sg), 1e-4)
    # GPU 側は 1/Q に落とした conf テクスチャから 1x1 まで潰すので、ここも同じ順で潰す。
    g = d2d_reduce(d2d_down(np.stack([mc, F["conf"]], -1), Q)).reshape(2)
    strength = region / max(g[0] / max(g[1], 1e-4), 1e-4)
    prio = (conf_s ** 1.2) * (1.0 - PRIO_W + PRIO_W * np.clip(d2d_down(strength, S) * PRIO_K, 0.0, 1.0))
    prio = prio.astype(np.float32)
    if p.stretch_jitter > 1e-4:
        # 筆の毛。届く距離は優先度で決まるので、優先度をばらつかせると毛先が不揃いになる。
        # 粒は flow_length に比例させる（長い流線ほど太い毛）。
        #
        # ノイズの座標だけは GPU と一致しない。こちらは画像の画素座標、HLSL は
        # **シーン座標**（D2DGetScenePosition）を使う。素材が動いた時に模様が
        # 泳がないようにするためで、力線のノイズと同じ扱い。位相がずれるだけで
        # 統計は同じなので、ここを画素座標に揃えてはいけない。
        cell = max(p.flow_length * 0.08, 4.0) / S
        nz = _value_noise(xx / cell, yy / cell)
        prio = (prio * (1.0 - p.stretch_jitter * nz)).astype(np.float32)
    if p.stretch_scale > 0.3:
        prio = d2d_blur(prio, p.stretch_scale / S)

    total_px = p.flow_length
    n = _step_count(total_px, STRETCH_STEP_PX, p.stretch_steps)
    hs = (total_px / n) / S              # texel 単位の歩幅
    # decay=0 だと距離の項はほぼ効かず、どの流線も flow_length いっぱいまで届く
    # （＝塗る範囲が円盤になる）。decay=1 で「優先度 1 の輪郭がちょうど届き切る」。
    tie = (TIE_BASE + p.stretch_decay * (1.0 - p.stretch_gate)) / max(total_px, 1.0)

    # 固定距離で拾ってはいけない。conf は輪郭のスケールぶん太い帯になるので、
    # 帯の外縁にいる画素は数 px 上流を見ても背景のままで、
    # 「背景色を運ぶ強い種」になって本来の輪郭色を塞ぐ。帯が眠くなる原因はこれ。
    # 代わりに φ の尾根まで登り、登り切った所の色を拾う。すでに尾根にいる画素
    # （＝構造の内側）は自分の色のままになるので、文字や線画の面が塗り潰されない。
    # argmax で 1 点を選ぶと、隣接画素で選ばれる点が切り替わって細かい縞が出る。
    # 「自分より φ が高いぶん」で重み付けした平均にすると空間的に滑らかになり、
    # なおかつ尾根の色が支配的になる。登り先が無ければ自分の色のまま。
    pick = pick_range(p) / S
    phi = d2d_up(F["B"][..., 1], (lh, lw))
    own = _clampsamp(col0, yy, xx)
    phi0 = _clampsamp(phi, yy, xx)
    acc = own * PICK_OWN
    wsum = np.full((lh, lw), PICK_OWN, np.float32)
    for i in range(1, 5):
        t = i * 0.25
        sy = yy - dy * (pick * t)
        sx = xx - dx * (pick * t)
        wt = np.clip((_clampsamp(phi, sy, sx) - phi0) * PICK_GAIN, 0.0, 1.0) ** 2
        acc = acc + _clampsamp(col0, sy, sx) * wt[..., None]
        wsum = wsum + wt
    col = (acc / wsum[..., None]).astype(np.float32)
    score = prio.copy()                  # score = 優先度 - tie * 伝播距離

    for _ in range(n):
        sy = yy - dy * hs
        sx = xx - dx * hs
        c2 = _clampsamp(col, sy, sx)
        s2 = _clampsamp(score, sy, sx) - tie * hs * S
        better = s2 > score
        score = np.where(better, s2, score).astype(np.float32)
        col = np.where(better[..., None], c2, col).astype(np.float32)

    return d2d_up(col, (h, w)), d2d_up(score, (h, w))


# ==========================================================  合成
def render(rgb, p: GpuParams, F=None):
    rgb = rgb.astype(np.float32)
    if F is None:
        F = build_field(rgb, p)
    out, _ = advect(rgb, F, p)

    if p.stretch > 1e-4:
        st, q = stretch(out, F, p)
        # score = prio - tie*dist なので、gate は最小ペナルティの半分だけ下げて補正する。
        # decay のぶんは引かない（引くと decay を上げるほど塗る範囲が広がってしまう）。
        covered = q >= (p.stretch_gate - TIE_BASE * 0.5)
        k = (covered.astype(np.float32) * p.stretch)[..., None]
        out = out * (1.0 - k) + st * k

    out = post(out, F, p, rgb)
    return out, F


# ==========================================================  P8 : 発展要素
def _frac(x):
    return x - np.floor(x)


def _hash21(x, y):
    """Post.hlsl の saHash と同じ。"""
    px = _frac(x * 0.1031)
    py = _frac(y * 0.1030)
    d = px * (py + 33.33) + py * (px + 33.33)
    px = px + d
    py = py + d
    return _frac((px + py) * px)


def _value_noise(x, y):
    ix, iy = np.floor(x), np.floor(y)
    fx, fy = x - ix, y - iy
    fx = fx * fx * (3.0 - 2.0 * fx)
    fy = fy * fy * (3.0 - 2.0 * fy)
    a = _hash21(ix, iy)
    b = _hash21(ix + 1.0, iy)
    c = _hash21(ix, iy + 1.0)
    d = _hash21(ix + 1.0, iy + 1.0)
    return (a + (b - a) * fx) + ((c + (d - c) * fx) - (a + (b - a) * fx)) * fy


def _line_noise(px, py, phi, grain, seed_edge):
    cell = max(grain, 0.6)
    z = (_value_noise(px / cell, py / cell) - 0.5) / 0.19   # 値ノイズの標準偏差 ~0.19
    seed = np.clip(phi, 0.0, 1.0) ** 0.7
    z = z * ((1.0 - seed_edge) + seed_edge * (0.25 + 0.75 * seed))
    return z * 0.5 + 0.5


def _highlight(col, py, px):
    c = _clampsamp(col, py, px)
    l = 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]
    return np.clip((l - 0.55) / 0.45, 0.0, 1.0)[..., None] * c


def _walk(col, F, p: GpuParams, sgn, n, hstep, mode):
    """流線に沿って payload を平均する。mode 0 = 発光、1 = 力線(LIC)。

    戻り値は (payload, 実際に歩いた距離)。歩幅は場の強さでゲートされるので、
    公称の長さとは大きく変わる。LIC の正規化にはこちらを使う。
    """
    h, w = col.shape[:2]
    Q = p.field_div
    A = F["A"]
    phiN = d2d_up(F["B"][..., 1], (h, w))
    yy, xx = _grid((h, w))
    a0 = _clampsamp(A, yy / Q, xx / Q)
    dxv = sgn * a0[..., 0]
    dyv = sgn * a0[..., 1]
    cx, cy = xx.copy(), yy.copy()

    if mode == 0:
        acc = _highlight(col, cy, cx)
        lic = None
    else:
        acc = None
        lic = _line_noise(cx, cy, phiN, p.line_grain, LINE_SEED_EDGE)
    wsum = np.ones((h, w), np.float32)
    plen = np.zeros((h, w), np.float32)

    for i in range(n):
        a = _clampsamp(A, cy / Q, cx / Q)
        fx = sgn * a[..., 0]
        fy = sgn * a[..., 1]
        flip = np.where(fx * dxv + fy * dyv < 0.0, -1.0, 1.0).astype(np.float32)
        fx *= flip
        fy *= flip
        ang = np.arctan2(dxv * fy - dyv * fx, dxv * fx + dyv * fy)
        turn = p.align * ang + p.curvature * a[..., 3] * hstep * 0.09
        ct, st = np.cos(turn), np.sin(turn)
        dxv, dyv = ct * dxv - st * dyv, st * dxv + ct * dyv
        dn = np.hypot(dxv, dyv) + EPS
        dxv /= dn
        dyv /= dn
        step = hstep * a[..., 2]
        cx = cx + dxv * step
        cy = cy + dyv * step
        plen = plen + step

        t = (i + 1) / n
        wgt = np.float32(0.5 + 0.5 * np.cos(np.pi * t))
        if mode == 0:
            acc = acc + _highlight(col, cy, cx) * wgt
        else:
            ph = _clampsamp(phiN, cy, cx)
            lic = lic + _line_noise(cx, cy, ph, p.line_grain, LINE_SEED_EDGE) * wgt
        wsum = wsum + wgt

    if mode == 0:
        return acc / wsum[..., None], plen
    return lic / wsum, plen


def post(col, F, p: GpuParams, original):
    """Post.hlsl と同じ順序で発光・力線・元画像の混ぜ戻しを掛ける。"""
    h, w = col.shape[:2]
    out = col.copy()
    amp = d2d_up(F["B"][..., 0], (h, w))
    res = d2d_up(F["B"][..., 2], (h, w))

    if p.glow > 1e-4:
        total = p.flow_length * 2.2
        n = _step_count(total, p.step_px, p.steps)
        hstep = total / n
        gf, _ = _walk(out, F, p, -1.0, n, hstep, 0)
        gb, _ = _walk(out, F, p, 1.0, n, hstep, 0)
        g = 0.5 * (gf + gb)
        g = np.clip(g * (p.glow * 2.0 * amp)[..., None], 0.0, 1.0)
        out = 1.0 - (1.0 - np.clip(out, 0.0, 1.0)) * (1.0 - g)      # screen

    if p.line_draw > 1e-4:
        total = max(p.flow_length * 1.8, 34.0)
        n = int(np.clip(round(total), 8, min(p.steps * 2, 220)))
        hstep = total / n
        lf, len_f = _walk(out, F, p, -1.0, n, hstep, 1)
        lb, len_b = _walk(out, F, p, 1.0, n, hstep, 1)
        lic = 0.5 * (lf + lb)
        # 局所コントラスト正規化の代わりに、LIC の標準偏差を解析的に出して割る。
        # 公称の長さではなく **実際に歩いた距離** を使う。場が強くコヒーレントな所ほど
        # 長く歩き、平均される本数が増えて分散が下がるので、そこで線が薄くなる。
        g_eff = max(p.line_grain, 0.6)
        plen = 0.5 * (len_f + len_b)
        sd = 0.5 * np.sqrt(g_eff / np.maximum(plen, g_eff)) + 0.030
        # 0.36 は実測合わせ。リファレンスの局所正規化に対してコントラストが
        # 2 割ほど足りなかったぶんを埋める。
        tex = np.clip((lic - 0.5) / sd * 0.36 * p.line_density + 0.5, 0.0, 1.0)
        # 力線は解像できない所（場が速く回る所）を強く抑える
        t = ((tex - 0.5) * (p.line_draw * amp * res) * 1.7)[..., None]
        base = np.clip(out, 0.0, 1.0)
        out = np.maximum(base + t * (0.35 + 0.65 * (1.0 - np.abs(2.0 * base - 1.0))), 0.0)

    if p.preserve_original > 1e-4:
        out = out * (1.0 - p.preserve_original) + original * p.preserve_original
    return np.clip(out, 0.0, 1.0).astype(np.float32)
