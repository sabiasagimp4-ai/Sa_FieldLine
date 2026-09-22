"""Sa_FieldLine - reference prototype (CPU / numpy).

エッジを「線」ではなく「力場の発生源」として扱い、
輪郭から生まれたベクトル場に沿って画素を流すエフェクト。

pipeline
    1. multi-scale edge detection      -> 複数スケールの輪郭
    2. edge normal                     -> 法線ベクトル
    3. long-range spread (multi-octave)-> 法線を周囲へ広げて場を作る
    4. superposition / swirl / curl    -> 場同士の干渉で方向が曲がる
    5. streamline advection            -> 流線に沿って画素を移動
"""

from __future__ import annotations

from dataclasses import dataclass, field as _dcfield

import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates

EPS = 1e-8

# 引き伸ばしの優先度（gpu_sim.py と同じ値にすること）
PRIO_W = 0.65          # 優先度に輪郭の強さを効かせる割合（0 だと全部同点になる）
PRIO_K = 0.70          # 輪郭の強さ（画面平均＝1）-> 優先度の傾き。1.43 倍で頭打ち
TIE_BASE = 0.03        # 同点の時に近い輪郭を採るための最小の距離ペナルティ
PRIO_SMOOTH = 1.0      # 優先度を均す幅（輪郭の帯の幅に対する倍率）


# ---------------------------------------------------------------- color utils
def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, None)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)


def luma(rgb: np.ndarray) -> np.ndarray:
    return (0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]).astype(np.float32)


def smoothstep(a: float, b: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - a) / max(b - a, EPS), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def robust_scale(x: np.ndarray, pct: float = 99.0) -> float:
    """Return a normalising divisor so that parameters stay resolution/content independent."""
    v = float(np.percentile(np.abs(x), pct))
    return v if v > EPS else 1.0


# ------------------------------------------------------------------ parameters
@dataclass
class Params:
    # --- 主なパラメータ（仕様書どおり） ---
    strength: float = 1.0          # 変位の強さ
    radius: float = 120.0           # エッジの影響範囲 [px]
    curvature: float = 1.0         # 流れの曲がり具合
    swirl: float = 0.0             # 回転成分 (-1..1 -> -90deg..+90deg)
    attract: float = 0.0           # 引力(+) / 反発(-)
    flow_length: float = 40.0      # 流線の長さ [px]
    edge_threshold: float = 0.10   # 使用するエッジの強さ
    smoothness: float = 0.5        # ベクトル場の滑らかさ
    detail_scale: float = 0.5      # 細かい輪郭(1) <-> 大きい輪郭(0)
    preserve_original: float = 0.0 # 元画像を残す量

    # --- 発展 ---
    smear: float = 0.0             # 流線に沿って色を平均する（方向ボケ）
    stretch: float = 0.0           # 流線に沿って色を「帯のまま」引き伸ばす
    stretch_mode: str = "edge"     # edge / contrast / bright / dark / vivid / far
    stretch_decay: float = 0.6     # 近さの優先。0 なら流線上で最も強い輪郭の色が
                                   # flow_length いっぱいまで届く（塗る範囲が円盤になる）。
                                   # 1 で「優先度 1 の輪郭がちょうど届き切る」長さになり、
                                   # 弱い輪郭ほど手前で止まる
    stretch_scale: float = 0.0     # 優先度マップのぼかし [px]。**ストロークの太さ**
    stretch_radial: bool = True    # 引き伸ばし専用に「輪郭から放射」する場を使う。
                                   # 変位側が Swirl でも引き伸ばしは放射のままになる
    stretch_swirl: float = 0.0     # 放射場をひねる。0 で真っ直ぐ外向き
    stretch_pick: float = 3.0      # 色を拾う位置を、輪郭からさらに上流へ [px]
                                   # ずらす。線画の黒ではなく面の色を引き出す。
    stretch_gate: float = 0.35     # これ未満しか輪郭を掴めなかった画素は元のまま。
                                   # 掴めた画素は **完全不透明** で塗り替わる
    stretch_jitter: float = 0.0    # 筆の毛。優先度をばらつかせて毛先を不揃いにする。
                                   # 届く距離は優先度で決まるので stretch_decay と併用する
    posterize: int = 0             # 0で無効。色を階調に丸めてフラットにする
    streamer: float = 0.0          # エッジの色を流線に沿って引き出す（力線そのもの）
    streamer_decay: float = 2.2    # 引き出した色の減衰（大きいほど短い）
    streamer_split: float = 0.75   # 種をまばらに撒いて線を分離させる度合い（砂鉄）
    streamer_grain: float = 0.8    # 種の粒
    glow: float = 0.0              # 流線に沿って発光
    shade: float = 0.0             # 流線に沿った明度差
    line_draw: float = 0.0         # 力線そのものを描画
    line_grain: float = 1.4        # 力線の太さ（LICノイズの粒）
    line_density: float = 1.0      # 力線のコントラスト / 密度
    line_seed_edge: float = 0.7    # 力線をエッジ近傍から生やす度合い
    chroma: float = 0.0            # 流線方向の色収差

    # --- 内部品質 ---
    steps: int = 128               # 流線の積分ステップ数の上限
    step_px: float = 1.25          # 1ステップあたりの移動量[px]（小さいほど綺麗・重い）
    base_sigma: float = 1.1        # 最小エッジスケール
    octaves: int = 5               # エッジのスケール段数
    align: float = 0.65            # 場へ向きを合わせる速さ（慣性の逆）
    amp_gamma: float = 0.85        # 場の強さ -> 変位量のカーブ
    falloff: float = 0.9           # エッジからの距離減衰の効き
    bidirectional: bool = False    # 流線を前後両方向へ伸ばす
    seed: int = 12345


# ------------------------------------------------------- 1. multi-scale edges
def multiscale_edges(lum: np.ndarray, p: Params):
    """複数スケールのガウス微分で輪郭を取り、detail_scale で細/粗を配合する。"""
    k = np.arange(p.octaves, dtype=np.float32)
    mu = (1.0 - float(np.clip(p.detail_scale, 0.0, 1.0))) * (p.octaves - 1)
    w = np.exp(-((k - mu) ** 2) / (2.0 * 0.95 ** 2))
    w /= w.sum()

    gx = np.zeros_like(lum)
    gy = np.zeros_like(lum)
    mag = np.zeros_like(lum)
    for i in range(p.octaves):
        s = p.base_sigma * (2.0 ** i)
        ex = gaussian_filter(lum, s, order=[0, 1], mode="reflect")
        ey = gaussian_filter(lum, s, order=[1, 0], mode="reflect")
        # Lindeberg gamma-normalisation: 粗いスケールが不当に弱くならないようにする
        ex *= s
        ey *= s
        gx += w[i] * ex
        gy += w[i] * ey
        mag += w[i] * np.hypot(ex, ey)
    return gx.astype(np.float32), gy.astype(np.float32), mag.astype(np.float32)


# ------------------------------------------------- 3. long range field spread
def spread(x: np.ndarray, radius: float, octaves: int = 6) -> np.ndarray:
    """複数オクターブのガウスを重ねて ~1/r の長距離カーネルを近似する。"""
    out = np.zeros_like(x)
    wsum = 0.0
    for j in range(octaves):
        s = radius * (0.5 ** j)
        if s < 0.7:
            break
        w = s  # weight ∝ sigma  ->  sum of gaussians ≈ power law
        if x.ndim == 3:
            blurred = np.stack([gaussian_filter(x[..., c], s, mode="reflect") for c in range(x.shape[2])], -1)
        else:
            blurred = gaussian_filter(x, s, mode="reflect")
        out += w * blurred
        wsum += w
    return out / max(wsum, EPS)


# ----------------------------------------------------------- build the field
def build_field(rgb_srgb: np.ndarray, p: Params):
    """輪郭 -> 法線 -> 拡散 -> 干渉 でベクトル場を作る。"""
    lum = luma(rgb_srgb)

    # 1&2. edges and their normals
    gx, gy, mag = multiscale_edges(lum, p)
    mag_n = mag / robust_scale(mag, 99.0)
    knee = 0.06 + 0.35 * (1.0 - p.edge_threshold)
    conf = smoothstep(p.edge_threshold, p.edge_threshold + knee, mag_n).astype(np.float32)

    gv = np.hypot(gx, gy) + EPS
    nx = (gx / gv).astype(np.float32)
    ny = (gy / gv).astype(np.float32)

    # 3. 法線を周囲へ広げる（符号付きなので、向かい合うエッジは打ち消し合う＝干渉）
    src = np.stack([conf * nx, conf * ny], axis=-1)
    vn = spread(src, p.radius)
    vn /= robust_scale(np.hypot(vn[..., 0], vn[..., 1]), 99.0)

    # 3b. エッジ密度のポテンシャル φ
    #     - 勾配は引力 / 反発成分
    #     - φ 自体は「エッジからどれだけ離れたか」の距離減衰として使う
    phi = spread(conf, p.radius)
    phi_n = np.clip(phi / robust_scale(phi, 98.0), 0.0, 1.0).astype(np.float32)

    vx = vn[..., 0].copy()
    vy = vn[..., 1].copy()
    if abs(p.attract) > 1e-4:
        # 細い輪郭だと勾配が数 px で反転して裂けるので、広めに均す
        gs = max(p.radius * 0.16, 2.5)
        px = gaussian_filter(phi, gs, order=[0, 1], mode="reflect")
        py = gaussian_filter(phi, gs, order=[1, 0], mode="reflect")
        sc = robust_scale(np.hypot(px, py), 99.0)
        vx += p.attract * px / sc
        vy += p.attract * py / sc

    # 4. swirl: 90deg 回すと流れがエッジに巻き付き、磁力線のようになる
    if abs(p.swirl) > 1e-4:
        th = p.swirl * (np.pi / 2.0)
        c, s = np.cos(th), np.sin(th)
        vx, vy = c * vx - s * vy, s * vx + c * vy

    # 5. 場の平滑化（強さの情報は残す）
    # 近傍のディテールを壊さない程度に抑える（ここを強くすると単なるぐにゃぐにゃになる）
    sig = 0.6 + p.smoothness * (2.0 + 0.085 * p.radius)
    vx = gaussian_filter(vx, sig, mode="reflect")
    vy = gaussian_filter(vy, sig, mode="reflect")

    amp_raw = np.hypot(vx, vy)
    amp_scale = robust_scale(amp_raw, 99.0)
    coh = np.clip(amp_raw / amp_scale, 0.0, 1.0)          # 場のコヒーレンス（打ち消し合う所は0）
    env = phi_n ** (0.35 + 1.3 * p.falloff)               # エッジからの距離減衰

    # flow : 流線が「どれだけ進むか」。打ち消し合う点で暴れないよう抑えるだけ。
    # amp  : 効果を「どれだけ適用するか」。エッジからの距離で減衰させる。
    flow = (0.30 + 0.70 * coh ** 0.5).astype(np.float32)
    amp = (((0.10 + 0.90 * env) * (0.35 + 0.65 * coh)) ** p.amp_gamma).astype(np.float32)

    inv = 1.0 / (amp_raw + EPS)
    dx = (vx * inv).astype(np.float32)
    dy = (vy * inv).astype(np.float32)

    # 6. curl: 場同士の干渉によるねじれ -> 進行方向を少しずつ曲げる源
    cs = max(1.5, 0.05 * p.radius)
    curl = (gaussian_filter(vy, cs, order=[0, 1], mode="reflect")
            - gaussian_filter(vx, cs, order=[1, 0], mode="reflect"))
    curl = (curl / robust_scale(curl, 97.0)).astype(np.float32)
    curl = np.clip(curl, -3.0, 3.0)

    # 方向場が速く回りすぎる所では、流線も力線も解像できない（＝ガサつく）ので抑える
    ts = 1.2
    turb = (np.hypot(gaussian_filter(dx, ts, order=[0, 1], mode="reflect"),
                     gaussian_filter(dx, ts, order=[1, 0], mode="reflect"))
            + np.hypot(gaussian_filter(dy, ts, order=[0, 1], mode="reflect"),
                       gaussian_filter(dy, ts, order=[1, 0], mode="reflect")))
    turb = turb / robust_scale(turb, 88.0)
    res = (1.0 / (1.0 + (0.85 * turb) ** 2)).astype(np.float32)

    return {
        "dx": dx, "dy": dy, "amp": amp, "flow": flow, "curl": curl, "res": res,
        "conf": conf, "mag_n": mag_n.astype(np.float32), "phi": phi_n,
        "nx": nx, "ny": ny,
    }


# ---------------------------------------------------------------- sampling
def _sample(img: np.ndarray, y: np.ndarray, x: np.ndarray, mode: str = "reflect") -> np.ndarray:
    coords = np.stack([y.ravel(), x.ravel()])
    if img.ndim == 2:
        return map_coordinates(img, coords, order=1, mode=mode).reshape(y.shape).astype(np.float32)
    out = [map_coordinates(img[..., c], coords, order=1, mode=mode).reshape(y.shape)
           for c in range(img.shape[2])]
    return np.stack(out, -1).astype(np.float32)



def _pick_range(p: Params) -> float:
    """色を拾うために上流を探す距離 [px]。

    conf は輪郭のスケール（= detail_scale が決めるオクターブの σ）ぶん太い帯になる。
    その帯を跨げない距離では、帯の外縁が背景色を運ぶ種になってしまう。
    """
    mu = (1.0 - float(np.clip(p.detail_scale, 0.0, 1.0))) * (p.octaves - 1)
    return max(p.stretch_pick, 2.0 * p.base_sigma * (2.0 ** mu))


def _step_count(p: Params, length: float) -> int:
    """歩幅が px 単位で一定になるようにステップ数を決める（ジャギー防止）。"""
    return int(np.clip(round(abs(length) / max(p.step_px, 0.2)), 8, p.steps))


# ------------------------------------------------------ 5. streamline advect
def trace(fieldset, shape, p: Params, sign: float = -1.0, payload=None, length_scale: float = 1.0):
    """流線を積分する。

    返り値: (終点座標 y,x), (payload を流線に沿って平均した画像) or None
    """
    h, w = shape
    yy, xx = np.meshgrid(np.arange(h, dtype=np.float32), np.arange(w, dtype=np.float32), indexing="ij")
    px, py = xx.copy(), yy.copy()

    dx0 = fieldset["dx"]
    dy0 = fieldset["dy"]
    d_x = (sign * dx0).copy()
    d_y = (sign * dy0).copy()

    total = p.flow_length * length_scale
    n = _step_count(p, total)
    hstep = total / n

    acc = None
    acc_w = None
    if payload is not None:
        acc = np.zeros(payload.shape, dtype=np.float32)
        acc_w = np.zeros(shape, dtype=np.float32)
        w0 = 1.0
        acc += payload * w0
        acc_w += w0

    for i in range(n):
        fx = _sample(dx0, py, px)
        fy = _sample(dy0, py, px)
        gate = _sample(fieldset["flow"], py, px)
        cu = _sample(fieldset["curl"], py, px)

        fx = sign * fx
        fy = sign * fy
        # 場が弱いところで向きが暴れないよう、進行方向側の半球へ揃える
        flip = np.where(fx * d_x + fy * d_y < 0.0, -1.0, 1.0).astype(np.float32)
        fx *= flip
        fy *= flip

        cross = d_x * fy - d_y * fx
        dot = d_x * fx + d_y * fy
        ang = np.arctan2(cross, dot)

        turn = p.align * ang + p.curvature * cu * hstep * 0.09
        ct, st = np.cos(turn), np.sin(turn)
        d_x, d_y = ct * d_x - st * d_y, st * d_x + ct * d_y
        dn = np.hypot(d_x, d_y) + EPS
        d_x /= dn
        d_y /= dn

        step = hstep * gate
        px = px + d_x * step
        py = py + d_y * step

        if payload is not None:
            t = (i + 1) / n
            wgt = (0.5 + 0.5 * np.cos(np.pi * t)).astype(np.float32)  # tapered
            s = _sample(payload, py, px)
            acc += s * wgt if payload.ndim == 2 else s * wgt[..., None]
            acc_w += wgt

    out = None
    if payload is not None:
        out = acc / (acc_w[..., None] if payload.ndim == 3 else acc_w)
    return (py, px), out, (yy, xx)



# --------------------------------------- 5b. edge colour streamers (力線本体)
def edge_streamer(fieldset, lin: np.ndarray, p: Params, sign: float = -1.0,
                  length_scale: float = 1.0):
    """流線をさかのぼり、上流にあるエッジの色を集めて引き伸ばす。

    輪郭の色そのものが場に沿って流れ出すので、
    「画像自身の色でできた力線」が輪郭から生える。
    """
    h, w = lin.shape[:2]
    yy, xx = np.meshgrid(np.arange(h, dtype=np.float32), np.arange(w, dtype=np.float32), indexing="ij")
    px, py = xx.copy(), yy.copy()

    dx0, dy0 = fieldset["dx"], fieldset["dy"]
    conf = (fieldset["conf"] ** 1.6).astype(np.float32)

    # 種をまばらにすると、隣り合う流線が別々の種を拾うので線が分離する（砂鉄）
    if p.streamer_split > 1e-4:
        rng = np.random.default_rng(p.seed + 77)
        nz = gaussian_filter(rng.random((h, w)).astype(np.float32), max(p.streamer_grain, 0.25), mode="reflect")
        nz = (nz - nz.min()) / (np.ptp(nz) + EPS)
        nz = nz ** (1.0 + 2.5 * p.streamer_split)
        conf = conf * (1.0 - p.streamer_split + p.streamer_split * nz * 2.4)
    d_x = (sign * dx0).copy()
    d_y = (sign * dy0).copy()

    total = p.flow_length * length_scale
    n = _step_count(p, total)
    hstep = total / n

    acc = np.zeros_like(lin)
    accw = np.zeros((h, w), np.float32)
    for i in range(n):
        fx = sign * _sample(dx0, py, px)
        fy = sign * _sample(dy0, py, px)
        gate = _sample(fieldset["flow"], py, px)
        cu = _sample(fieldset["curl"], py, px)

        flip = np.where(fx * d_x + fy * d_y < 0.0, -1.0, 1.0).astype(np.float32)
        fx *= flip
        fy *= flip
        ang = np.arctan2(d_x * fy - d_y * fx, d_x * fx + d_y * fy)
        turn = p.align * ang + p.curvature * cu * hstep * 0.09
        ct, st = np.cos(turn), np.sin(turn)
        d_x, d_y = ct * d_x - st * d_y, st * d_x + ct * d_y
        dn = np.hypot(d_x, d_y) + EPS
        d_x /= dn
        d_y /= dn

        px = px + d_x * hstep * gate
        py = py + d_y * hstep * gate

        t = (i + 1) / n
        decay = np.exp(-p.streamer_decay * t).astype(np.float32)
        k = _sample(conf, py, px) * decay
        acc += _sample(lin, py, px) * k[..., None]
        accw += k

    col = acc / (accw[..., None] + 1e-4)
    cover = np.clip(accw / (0.30 * n / max(p.streamer_decay, 0.4)), 0.0, 1.0)
    return col.astype(np.float32), cover.astype(np.float32)


def radial_fieldset(fieldset, p: Params):
    """引き伸ばし用に、輪郭から外向きに放射する場を作る。

    φ（エッジ密度のポテンシャル）の勾配は輪郭へ向かう。その逆が外向き。
    勾配場なので回転成分を持たず、電気力線のように素直に放射する。
    流線を「さかのぼる」と必ず輪郭に着くので、端の色を拾える。
    """
    phi = fieldset["phi"]
    gs = max(p.radius * 0.10, 2.0)
    gx = gaussian_filter(phi, gs, order=[0, 1], mode="reflect")
    gy = gaussian_filter(phi, gs, order=[1, 0], mode="reflect")

    vx, vy = -gx, -gy                       # 外向き
    if abs(p.stretch_swirl) > 1e-4:
        th = p.stretch_swirl * (np.pi / 2.0)
        c, sn = np.cos(th), np.sin(th)
        vx, vy = c * vx - sn * vy, sn * vx + c * vy

    m = np.hypot(vx, vy) + EPS
    fs = dict(fieldset)
    fs["dx"] = (vx / m).astype(np.float32)
    fs["dy"] = (vy / m).astype(np.float32)
    # 減衰させないので歩幅はゲートしない
    fs["flow"] = np.ones_like(fs["dx"])
    return fs


# ------------------------------------------- 5c. flow hold (引き伸ばし本体)
def _frac(x):
    return x - np.floor(x)


def _hash21(x, y):
    """gpu_sim._hash21 / FieldLineCommon.hlsli の saHash と同じ。"""
    px = _frac(x * 0.1031)
    py = _frac(y * 0.1030)
    d = px * (py + 33.33) + py * (px + 33.33)
    return _frac(((px + d) + (py + d)) * (px + d))


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


def _priority_map(lin: np.ndarray, fieldset, mode: str, prm: Params) -> np.ndarray:
    """流線上で「どのサンプルを採用するか」を決める優先度。"""
    l = luma(lin)
    if mode == "edge":
        # conf は閾値で飽和するので、これだけだと「どの輪郭も同点」になり、
        # 伝播では必ず一番近い（＝一番外側の）輪郭が勝つ。強さを残すと、
        # 強い内側の輪郭が弱い外側の輪郭を押しのけて外まで出られる。
        # 画素ごとの強さのままだと櫛状の縞が戻るので、輪郭の帯の幅で
        # conf を重みにした平均を取り、「この輪郭の強さ」にしてから使う。
        # 強さは絶対値ではなく画面平均との比で持つ（gpu_sim と同じ）。
        # 正規化の係数が約分されて消えるので、実装どうしの差が出ない。
        conf = fieldset["conf"]
        sg = PRIO_SMOOTH * _pick_range(prm) * 0.5
        # gpu_sim / Confidence.hlsl と同じく 1/4 に縮めて [0,1] に収める。
        # 比で使うので倍率は約分されて消える。
        mc = np.clip(fieldset["mag_n"] * 0.25, 0.0, 1.0) * conf
        region = (gaussian_filter(mc, sg, mode="reflect")
                  / np.maximum(gaussian_filter(conf, sg, mode="reflect"), 1e-4))
        st = region / max(float(mc.mean()) / max(float(conf.mean()), 1e-4), 1e-4)
        return (conf ** 1.2) * (1.0 - PRIO_W + PRIO_W * np.clip(st * PRIO_K, 0.0, 1.0))
    if mode == "contrast":
        # 局所平均からの外れ具合。明部も暗部も等しく伸びる
        d = np.abs(l - gaussian_filter(l, 6.0, mode="reflect"))
        return (d / robust_scale(d, 97.0)).astype(np.float32)
    if mode == "bright":
        return l
    if mode == "dark":
        return 1.0 - l
    if mode == "vivid":
        mx = lin.max(-1)
        mn = lin.min(-1)
        return ((mx - mn) / (mx + EPS)).astype(np.float32)
    return np.zeros_like(l)  # far: 優先度なし → 常に上書き = 最遠点を保持


def flow_flood(fieldset, lin: np.ndarray, p: Params, length_scale: float = 1.0):
    """輪郭の色を、場に沿って **1歩ずつ隣へ伝播** させる。

    1画素ずつ長い流線を追うと、鞍点の近くで隣接画素の流線が指数的に離れ、
    隣同士が別の輪郭に着いてしまう。結果は櫛状の破線になり、
    解像度を上げても消えない（画素のエイリアスではなく実構造のため）。

    各反復で 1 歩上流（輪郭側）だけを見て、より強い輪郭から来た色を
    受け継ぐ形にすると、隣接画素は必ず近い結果になり縞が出ない。
    伝播距離も一緒に運ぶので、塗る範囲の境界も滑らかになる。
    """
    h, w = lin.shape[:2]
    yy, xx = np.meshgrid(np.arange(h, dtype=np.float32), np.arange(w, dtype=np.float32), indexing="ij")

    dx, dy = fieldset["dx"], fieldset["dy"]

    prio = _priority_map(lin, fieldset, p.stretch_mode, p)
    if p.stretch_jitter > 1e-4:
        # 筆の毛。届く距離は優先度で決まるので、優先度をばらつかせると毛先が不揃いになる。
        # 粒は flow_length に比例させる（長い流線ほど太い毛）。
        cell = max(p.flow_length * 0.08, 4.0)
        nz = _value_noise(xx / cell, yy / cell)
        prio = prio * (1.0 - p.stretch_jitter * nz)
    if p.stretch_scale > 0.3:
        prio = gaussian_filter(prio, p.stretch_scale, mode="reflect")
    prio = prio.astype(np.float32)

    total = p.flow_length * length_scale
    n = _step_count(p, total)
    hstep = total / n

    # 輪郭ちょうどは線画の色なので、上流（面の側）から色を拾う。
    #
    # 固定距離で拾ってはいけない。conf は輪郭のスケールぶん太い帯になるので、
    # 帯の外縁にいる画素は数 px 上流を見ても背景のままで、
    # 「背景色を運ぶ強い種」になって本来の輪郭色を塞ぐ。帯が眠くなる原因はこれ。
    # 代わりに φ（輪郭密度）の尾根まで登り、登り切った所の色を拾う。
    # すでに尾根にいる画素（＝構造の内側）は自分の色のままになるので、
    # 文字や線画の面が背景色で塗り潰されない。
    # argmax で 1 点を選ぶと、隣接画素で選ばれる点が切り替わって細かい縞が出る。
    # 「自分より φ が高いぶん」で重み付けした平均にすると空間的に滑らかになり、
    # なおかつ尾根の色が支配的になる。登り先が無ければ自分の色のまま。
    pick = _pick_range(p)
    phi = fieldset["phi"]
    own = _sample(lin, yy, xx)
    phi0 = _sample(phi, yy, xx)
    acc = own * 0.02
    wsum = np.full((h, w), 0.02, np.float32)
    for i in range(1, 5):
        t = i * 0.25
        sy = yy - dy * (pick * t)
        sx = xx - dx * (pick * t)
        wt = np.clip((_sample(phi, sy, sx) - phi0) * 6.0, 0.0, 1.0) ** 2
        acc = acc + _sample(lin, sy, sx) * wt[..., None]
        wsum = wsum + wt
    col = (acc / wsum[..., None]).astype(np.float32)

    src = prio.copy()                      # 受け継いだ輪郭の強さ
    dist = np.zeros((h, w), np.float32)    # そこから伝播してきた距離

    # 近さの優先。0 だと距離の項がほぼ効かず、どの流線も flow_length いっぱいまで
    # 届く（＝塗る範囲が円盤になる）。1 で「優先度 1 の輪郭がちょうど届き切る」。
    tie = (TIE_BASE + p.stretch_decay * (1.0 - p.stretch_gate)) / max(total, 1.0)

    for _ in range(n):
        sy = yy - dy * hstep
        sx = xx - dx * hstep
        c2 = _sample(col, sy, sx)
        s2 = _sample(src, sy, sx)
        d2 = _sample(dist, sy, sx) + hstep

        better = s2 - tie * d2 > src - tie * dist
        src = np.where(better, s2, src).astype(np.float32)
        dist = np.where(better, d2, dist).astype(np.float32)
        col = np.where(better[..., None], c2, col).astype(np.float32)

    return col, src, dist


# ------------------------------------------------------------------- render
def render(rgb_srgb: np.ndarray, p: Params, fieldset=None):
    h, w = rgb_srgb.shape[:2]
    if fieldset is None:
        fieldset = build_field(rgb_srgb, p)

    lin = srgb_to_linear(rgb_srgb).astype(np.float32)
    amp = fieldset["amp"]

    def advect(scale: float):
        (ey, ex), _, (yy, xx) = trace(fieldset, (h, w), p, sign=-1.0, length_scale=scale)
        k = p.strength * amp * (0.55 + 0.45 * fieldset["res"])
        return yy + (ey - yy) * k, xx + (ex - xx) * k

    if p.chroma > 1e-4:
        chans = []
        for ci, sc in enumerate((1.0 + 0.35 * p.chroma, 1.0, 1.0 - 0.35 * p.chroma)):
            sy, sx = advect(sc)
            chans.append(_sample(lin[..., ci], sy, sx))
        out = np.stack(chans, -1)
        sy, sx = advect(1.0)
    else:
        sy, sx = advect(1.0)
        out = _sample(lin, sy, sx)

    # --- 発展: 流線に沿って色を帯のまま引き伸ばす ---
    if p.stretch > 1e-4:
        sfs = radial_fieldset(fieldset, p) if p.stretch_radial else fieldset
        st, q, dist = flow_flood(sfs, out, p)
        # 輪郭を掴めた画素は **完全不透明** で上書きする（下の色は残さない）。
        # 掴めなかった画素だけ元のまま。減衰も距離ブレンドも掛けない。
        tie = (TIE_BASE + p.stretch_decay * (1.0 - p.stretch_gate)) / max(p.flow_length, 1.0)
        covered = ((q - tie * dist) >= p.stretch_gate - TIE_BASE * 0.5) & (dist > 0.0)
        if p.stretch >= 0.999:
            out = np.where(covered[..., None], st, out)
        else:
            k = (covered.astype(np.float32) * p.stretch)[..., None]
            out = out * (1.0 - k) + st * k

    # --- 発展: エッジの色を流線に沿って引き出す（力線本体） ---
    if p.streamer > 1e-4:
        col, cov = edge_streamer(fieldset, out, p, sign=-1.0)
        if p.bidirectional:
            c2, v2 = edge_streamer(fieldset, out, p, sign=1.0)
            tot = cov + v2 + 1e-5
            col = (col * cov[..., None] + c2 * v2[..., None]) / tot[..., None]
            cov = np.clip(cov + v2, 0.0, 1.0)
        k = (p.streamer * cov * amp)[..., None]
        out = out * (1.0 - k) + col * k

    # --- 発展: 流線に沿って色を引き伸ばす ---
    if p.smear > 1e-4:
        _, sm, _ = trace(fieldset, (h, w), p, sign=-1.0, payload=out, length_scale=1.0)
        if p.bidirectional:
            _, sm2, _ = trace(fieldset, (h, w), p, sign=1.0, payload=out, length_scale=1.0)
            sm = 0.5 * (sm + sm2)
        out = out * (1.0 - (p.smear * amp)[..., None]) + sm * (p.smear * amp)[..., None]

    # --- 発展: 流線に沿った発光 ---
    if p.glow > 1e-4:
        l = luma(out)
        hi = np.clip((l - 0.55) / 0.45, 0.0, 1.0)[..., None] * out
        _, gl, _ = trace(fieldset, (h, w), p, sign=-1.0, payload=hi, length_scale=2.2)
        _, gl2, _ = trace(fieldset, (h, w), p, sign=1.0, payload=hi, length_scale=2.2)
        g = (gl + gl2) * 0.5 * (p.glow * 2.0) * amp[..., None]
        out = 1.0 - (1.0 - np.clip(out, 0, 1)) * (1.0 - np.clip(g, 0, 1))  # screen

    # --- 発展: 力線そのものを描く ---
    if p.line_draw > 1e-4:
        tex = field_lines(fieldset, (h, w), p, density=p.line_density)
        gate = (amp * fieldset["res"])[..., None]
        t = (tex - 0.5)[..., None] * (p.line_draw * gate) * 1.7
        base = np.clip(out, 0.0, 1.0)
        # soft light 風: 明部では明るく、暗部では暗く乗る
        out = np.clip(base + t * (0.35 + 0.65 * (1.0 - np.abs(2.0 * base - 1.0))), 0.0, None)

    # --- 発展: 流線に沿った明度差 ---
    if p.shade > 1e-4:
        sh = _sample(amp, sy, sx) - amp
        out = out * (1.0 + p.shade * 1.2 * sh[..., None])

    out = linear_to_srgb(np.clip(out, 0.0, 1.0))
    if p.posterize and p.posterize >= 2:
        lv = float(p.posterize) - 1.0
        out = np.round(out * lv) / lv
    if p.preserve_original > 1e-4:
        k = p.preserve_original
        out = out * (1.0 - k) + rgb_srgb * k
    return np.clip(out, 0.0, 1.0).astype(np.float32), fieldset


# --------------------------------------------------- field line visualisation
def field_lines(fieldset, shape, p: Params, length: float = None, density: float = 1.0):
    """LIC (line integral convolution) で場そのものを可視化 / 描画テクスチャ化。

    ノイズをエッジ近傍に寄せて撒くと、砂鉄のように「輪郭から生えて遠くで疎になる」線になる。
    """
    h, w = shape
    rng = np.random.default_rng(p.seed)
    noise = rng.random((h, w)).astype(np.float32)
    g = max(p.line_grain, 0.3)
    noise = gaussian_filter(noise, g, mode="reflect")
    noise = (noise - noise.mean()) / (noise.std() + EPS)

    if p.line_seed_edge > 1e-4:
        seed = fieldset["phi"] ** 0.7
        seed = seed / (seed.max() + EPS)
        noise = noise * (1.0 - p.line_seed_edge + p.line_seed_edge * (0.25 + 0.75 * seed))

    noise = noise * 0.5 + 0.5

    q = Params(**{**p.__dict__})
    q.flow_length = length if length is not None else max(p.flow_length * 1.8, 34.0)
    q.step_px = min(p.step_px, 1.0)
    q.steps = 220
    _, a, _ = trace(fieldset, (h, w), q, sign=-1.0, payload=noise)
    _, b, _ = trace(fieldset, (h, w), q, sign=1.0, payload=noise)
    lic = 0.5 * (a + b)

    # 局所コントラスト正規化（場の強弱で線の濃さが飛ばないように）
    lo = gaussian_filter(lic, 14.0, mode="reflect")
    hi = gaussian_filter((lic - lo) ** 2, 14.0, mode="reflect") ** 0.5
    # 分母に下限を置かないと、平坦部のわずかな揺らぎが増幅されてガサつく
    lic = (lic - lo) / (hi + 0.030)
    lic = np.clip(lic * 0.30 * density + 0.5, 0.0, 1.0)
    lic = gaussian_filter(lic, 0.5, mode="reflect")
    lic = np.clip(lic + 0.45 * (lic - gaussian_filter(lic, max(g, 1.0), mode="reflect")), 0.0, 1.0)
    return lic.astype(np.float32)

# --------------------------------------------------------------- supersample
def render_supersampled(rgb_srgb: np.ndarray, p: Params, ss: int = 2):
    """ss 倍で解像してから縮小する。静止画の仕上げ用。"""
    from dataclasses import replace
    if ss <= 1:
        return render(rgb_srgb, p)[0]
    h, w = rgb_srgb.shape[:2]
    big = np.stack([
        map_coordinates(rgb_srgb[..., c],
                        np.stack(np.meshgrid(np.arange(h * ss) / ss,
                                             np.arange(w * ss) / ss, indexing="ij")),
                        order=1, mode="reflect")
        for c in range(3)], -1).astype(np.float32)
    q = replace(p, radius=p.radius * ss, flow_length=p.flow_length * ss,
                base_sigma=p.base_sigma * ss, step_px=p.step_px * ss,
                line_grain=p.line_grain * ss, streamer_grain=p.streamer_grain * ss,
                stretch_scale=p.stretch_scale * ss, stretch_pick=p.stretch_pick * ss,
                steps=p.steps)
    out, _ = render(big, q)
    return out.reshape(h, ss, w, ss, 3).mean(axis=(1, 3)).astype(np.float32)
