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
    stretch_decay: float = 1.2     # 遠いサンプルの不利さ（大きいほど短い）
    stretch_scale: float = 0.0     # 優先度マップのぼかし [px]。**ストロークの太さ**
    stretch_drag: float = 0.35     # 遠いサンプルほど有利にする量。
                                   # 平坦な面は最遠点＝丸ごとドラッグされ、
                                   # 輪郭のある所は輪郭の色が居座って帯になる
    stretch_jitter: float = 0.0    # 流線ごとに長さをばらつかせる（筆の毛）
    stretch_jitter_scale: float = 6.0  # ばらつきの粒 [px]
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


# ------------------------------------------- 5c. flow hold (引き伸ばし本体)
def _priority_map(lin: np.ndarray, fieldset, mode: str) -> np.ndarray:
    """流線上で「どのサンプルを採用するか」を決める優先度。"""
    l = luma(lin)
    if mode == "edge":
        return fieldset["conf"] ** 1.2
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


def flow_hold(fieldset, lin: np.ndarray, p: Params, sign: float = -1.0,
              length_scale: float = 1.0):
    """流線をさかのぼり、最も優先度の高いサンプルの色を **1つだけ** 選んで塗る。

    平均しないので色が帯のまま伸び、優先度の順位が入れ替わる所で縁が立つ。
    これが参考画像のような「引き伸ばし」になる。平均（smear）はボケにしかならない。
    """
    h, w = lin.shape[:2]
    yy, xx = np.meshgrid(np.arange(h, dtype=np.float32), np.arange(w, dtype=np.float32), indexing="ij")
    px, py = xx.copy(), yy.copy()

    dx0, dy0 = fieldset["dx"], fieldset["dy"]
    d_x = (sign * dx0).copy()
    d_y = (sign * dy0).copy()

    prio = _priority_map(lin, fieldset, p.stretch_mode)
    # 優先度が高周波だと argmax が細かく切り替わって「引っ掻き傷」になる。
    # ぼかすと切り替わりが疎になり、ストロークが太くなる。
    if p.stretch_scale > 0.3:
        prio = gaussian_filter(prio, p.stretch_scale, mode="reflect")
    always = p.stretch_mode == "far"

    total = p.flow_length * length_scale
    n = _step_count(p, total)
    hstep = total / n

    jit = 1.0
    if p.stretch_jitter > 1e-4:
        rng = np.random.default_rng(p.seed + 991)
        nz = gaussian_filter(rng.random((h, w)).astype(np.float32),
                             max(p.stretch_jitter_scale, 0.4), mode="reflect")
        nz = (nz - nz.min()) / (np.ptp(nz) + EPS)
        jit = (1.0 - p.stretch_jitter + p.stretch_jitter * nz * 2.0)

    best_c = lin.copy()
    best_q = (prio * 1.0).astype(np.float32) if not always else np.full((h, w), -1e9, np.float32)

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

        px = px + d_x * hstep * gate * jit
        py = py + d_y * hstep * gate * jit

        t = (i + 1) / n
        w_i = float(np.exp(-p.stretch_decay * t))
        q = (float(i) if always
             else _sample(prio, py, px) * w_i + p.stretch_drag * t)
        c = _sample(lin, py, px)

        better = q > best_q
        best_q = np.where(better, q, best_q).astype(np.float32)
        best_c = np.where(better[..., None], c, best_c)

    return best_c.astype(np.float32)


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
        st = flow_hold(fieldset, out, p, sign=-1.0)
        if p.bidirectional:
            st2 = flow_hold(fieldset, out, p, sign=1.0)
            st = np.where(luma(st)[..., None] >= luma(st2)[..., None], st, st2)
        k = np.clip(p.stretch * (0.25 + 0.75 * amp), 0.0, 1.0)[..., None]
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
                steps=p.steps)
    out, _ = render(big, q)
    return out.reshape(h, ss, w, ss, 3).mean(axis=(1, 3)).astype(np.float32)
