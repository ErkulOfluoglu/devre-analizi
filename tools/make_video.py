#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Devre Analizi tanıtım videosu oluşturucu (Bölüm B).
Uygulama ekran görüntülerinden (shots.json) 1920x1080 30fps MP4 tanıtım videosu,
iletişim sayfası (contact_sheet.png) ve kapak görseli (poster.png) üretir.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------------------
# Görsel Tasarım Sabitleri ("Işık" stili)
# ---------------------------------------------------------------------------
VIDEO_W = 1920
VIDEO_H = 1080
DEFAULT_FPS = 30

COLOR_BG = (245, 245, 247)           # #F5F5F7
COLOR_TEXT = (29, 29, 31)            # #1D1D1F
COLOR_TEXT_SEC = (110, 110, 115)     # #6E6E73
COLOR_ACCENT = (0, 113, 227)         # #0071E3
COLOR_BORDER = (210, 210, 215)       # #D2D2D7
COLOR_PILL_BG = (232, 241, 252)      # #E8F1FC
COLOR_WHITE = (255, 255, 255)

CARD_W = 1500
CARD_X = (VIDEO_W - CARD_W) // 2     # 210
CARD_Y = 205
CARD_RADIUS = 16
MAX_ZOOM = 2.0

FONT_PATHS = {
    "regular": "C:/Windows/Fonts/segoeui.ttf",
    "semibold": "C:/Windows/Fonts/seguisb.ttf",
    "bold": "C:/Windows/Fonts/segoeuib.ttf",
}

LOGO_PATH = Path("assets/logo-1024.png")

# ---------------------------------------------------------------------------
# Hikâye Panosu (Storyboard) Veri Yapısı
# ---------------------------------------------------------------------------
STORYBOARD: Dict[str, Any] = {
    "s1_intro": {
        "duration": 3.0,
        "crossfade_out": 0.4,
        "title": "Devre Analizi",
        "tagline": "Devreyi çizin. Program çözsün. Her adımı Türkçe anlatsın.",
    },
    "s2_build": {
        "chip": "1",
        "title": "Devreyi çizin",
        "subtitle": "Elemanları yerleştirin, uçlarını tel ile bağlayın.",
        "empty_duration": 0.65,
        "step_duration": 0.46,
        "crossfade": 0.15,
        "padding_dip": 80.0,
    },
    "s3_solve": {
        "chip": "2",
        "title": "Çöz'e basın",
        "subtitle": "Program devreyi kesin olarak çözer; değerler devrenin üzerinde görünür.",
        "method_duration": 1.1,
        "solved_duration": 2.0,
        "crossfade": 0.3,
    },
    "s4_explain": {
        "chip": None,
        "title": "Her adım Türkçe anlatılır",
        "subtitle": "Düğüm, çevre, Thevenin, süperpozisyon… tıpkı ders kitabındaki gibi.",
        "step_duration": 0.95,
        "results_duration": 1.0,
        "crossfade": 0.35,
    },
    "s5_practice": {
        "chip": "3",
        "title": "Kendinizi deneyin",
        "subtitle": "Cevabınızı yazın; yanlışsa nedenini söyler.",
        "blank_duration": 1.0,
        "typed_duration": 0.9,
        "checked_duration": 1.1,
        "wrong_duration": 1.5,
        "crossfade": 0.3,
    },
    "s6_classroom": {
        "part1": {
            "chip": None,
            "title": "Bütün sınıf aynı soruyu açar",
            "subtitle": "Öğretmen 4 haneli soru kodunu paylaşır.",
            "duration": 1.9,
            "crossfade": 0.3,
        },
        "part2": {
            "chip": None,
            "title": "Alıştırma yaprağı",
            "subtitle": "Cevapsız soru kâğıdını yazdırın ya da PDF kaydedin.",
            "slide_duration": 0.6,
            "hold_duration": 1.7,
        },
    },
    "s7_extras": {
        "dark": {
            "chip": None,
            "title": "Koyu tema",
            "subtitle": "",
            "duration": 1.7,
            "crossfade": 0.3,
        },
        "ai": {
            "chip": None,
            "title": "İsteğe bağlı yapay zekâ",
            "subtitle": "Tamamen bilgisayarınızda çalışır; sorularınız hiçbir yere gitmez.",
            "duration": 2.1,
            "crossfade": 0.3,
        },
    },
    "s8_outro": {
        "duration": 5.5,
        "crossfade_in": 0.5,
        "static_tail": 1.5,
        "title": "Devre Analizi",
        "pills": ["Ücretsiz", "Açık kaynak", "İnternetsiz"],
        "repo": "github.com/ErkulOfluoglu/devre-analizi",
        "license": "MIT Lisansı · © 2026 Erkul Ofluoğlu",
    },
}


# ---------------------------------------------------------------------------
# Matematik, Yumuşatma (Easing) ve Kamera Yardımcıları
# ---------------------------------------------------------------------------
def clamp(val: float, lo: float, hi: float) -> float:
    """Değeri [lo, hi] aralığına sınırlar."""
    return max(lo, min(hi, val))


def lerp(a: float, b: float, t: float) -> float:
    """Doğrusal ara değer (linear interpolation) hesaplar."""
    return a + (b - a) * t


def ease_in_out_cubic(t: float) -> float:
    """Kübik giriş-çıkış yumuşatma fonksiyonu (0..1 -> 0..1)."""
    t = clamp(t, 0.0, 1.0)
    if t < 0.5:
        return 4.0 * t * t * t
    p = -2.0 * t + 2.0
    return 1.0 - (p * p * p) / 2.0


def ease_out_cubic(t: float) -> float:
    """Kübik çıkış yumuşatma fonksiyonu (0..1 -> 0..1)."""
    t = clamp(t, 0.0, 1.0)
    p = 1.0 - t
    return 1.0 - p * p * p


Rect = Tuple[float, float, float, float]  # (x, y, w, h)


def rect_center(r: Rect) -> Tuple[float, float]:
    """Dikdörtgenin merkez koordinatlarını döndürür."""
    return (r[0] + r[2] * 0.5, r[1] + r[3] * 0.5)


def union_rects(rects: List[Rect]) -> Optional[Rect]:
    """Birden fazla dikdörtgenin birleşim kutusunu hesaplar."""
    if not rects:
        return None
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[0] + r[2] for r in rects)
    y1 = max(r[1] + r[3] for r in rects)
    return (x0, y0, max(1.0, x1 - x0), max(1.0, y1 - y0))


def fit_view_rect(
    target: Optional[Rect],
    win_w: float,
    win_h: float,
    padding: float = 48.0,
    max_zoom: float = MAX_ZOOM,
) -> Rect:
    """
    Hedef DIP dikdörtgenini + dolgu payını (padding) pencere en-boy oranını koruyarak,
    maksimum yakınlaştırmayı (max_zoom) aşmadan ve pencere sınırları içinde kalarak
    bir kamera görünüm dikdörtgenine (vx, vy, vw, vh) dönüştürür.
    """
    if target is None or win_w <= 0 or win_h <= 0:
        return (0.0, 0.0, float(win_w), float(win_h))

    tx, ty, tw, th = target
    tx -= padding
    ty -= padding
    tw += 2.0 * padding
    th += 2.0 * padding

    aspect = win_w / win_h
    min_w = win_w / max_zoom
    min_h = win_h / max_zoom

    # Hedefi kapsayacak şekilde en-boy oranını koru
    if tw / max(1e-6, th) > aspect:
        vw = tw
        vh = vw / aspect
    else:
        vh = th
        vw = vh * aspect

    # Maksimum zoom ve tam pencere sınırlarını uygula
    vw = clamp(vw, min_w, win_w)
    vh = vw / aspect
    if vh > win_h:
        vh = win_h
        vw = vh * aspect

    cx = tx + tw * 0.5
    cy = ty + th * 0.5
    vx = clamp(cx - vw * 0.5, 0.0, win_w - vw)
    vy = clamp(cy - vh * 0.5, 0.0, win_h - vh)
    return (vx, vy, vw, vh)


def lerp_rect(r1: Rect, r2: Rect, t: float) -> Rect:
    """İki dikdörtgen arasında doğrusal geçiş yapar."""
    return (
        lerp(r1[0], r2[0], t),
        lerp(r1[1], r2[1], t),
        lerp(r1[2], r2[2], t),
        lerp(r1[3], r2[3], t),
    )


def dip_to_video_px(
    dip_pt: Tuple[float, float],
    view_rect: Rect,
    card_rect: Tuple[int, int, int, int] = (CARD_X, CARD_Y, CARD_W, 844),
) -> Tuple[float, float]:
    """
    Pencere DIP koordinatındaki bir noktayı mevcut kamera görünümü (view_rect)
    üzerinden video piksel koordinatlarına (1920x1080 içinde) eşler.
    """
    vx, vy, vw, vh = view_rect
    cx, cy, cw, ch = card_rect
    ux = (dip_pt[0] - vx) / max(1e-6, vw)
    uy = (dip_pt[1] - vy) / max(1e-6, vh)
    return (cx + ux * cw, cy + uy * ch)


# ---------------------------------------------------------------------------
# Yazı Tipi (Font) Yükleyici
# ---------------------------------------------------------------------------
_FONT_CACHE: Dict[Tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def get_font(weight: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """İstenen ağırlık ve boyutta yazı tipini önbellekten döndürür."""
    key = (weight, size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    path = FONT_PATHS.get(weight, FONT_PATHS["regular"])
    try:
        font = ImageFont.truetype(path, size=size)
    except Exception:
        font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


# ---------------------------------------------------------------------------
# Veri Yapıları: Manifest, Vuruşlar (Beats) ve Zaman Çizelgesi (Timeline)
# ---------------------------------------------------------------------------
@dataclass
class ShotInfo:
    name: str
    file: str
    kind: str = "window"
    label: str = ""
    targets: Dict[str, Rect] = field(default_factory=dict)
    page_size: Optional[Tuple[int, int]] = None


@dataclass
class Manifest:
    version: int
    scale: float
    win_w: float
    win_h: float
    shots_dir: Path
    shots: Dict[str, ShotInfo]
    build_names: List[str]


def load_manifest(shots_dir: Path) -> Manifest:
    """shots.json dosyasını okur ve ayrıştırır."""
    json_path = shots_dir / "shots.json"
    with open(json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    scale = float(raw.get("scale", 2.0))
    win = raw.get("window", {"width": 1600, "height": 900})
    win_w = float(win.get("width", 1600))
    win_h = float(win.get("height", 900))

    shots: Dict[str, ShotInfo] = {}
    build_names: List[str] = []

    for item in raw.get("shots", []):
        name = item.get("name", "")
        if not name:
            continue
        targets: Dict[str, Rect] = {}
        raw_targets = item.get("targets") or {}
        for k, v in raw_targets.items():
            if isinstance(v, (list, tuple)) and len(v) == 4:
                targets[k] = (float(v[0]), float(v[1]), float(v[2]), float(v[3]))
        page_info = item.get("page")
        page_size = None
        if isinstance(page_info, dict) and "width" in page_info and "height" in page_info:
            page_size = (int(page_info["width"]), int(page_info["height"]))

        info = ShotInfo(
            name=name,
            file=item.get("file", f"{name}.png"),
            kind=item.get("kind", "window"),
            label=item.get("label", ""),
            targets=targets,
            page_size=page_size,
        )
        shots[name] = info
        if name.startswith("build_"):
            build_names.append(name)

    return Manifest(
        version=int(raw.get("version", 1)),
        scale=scale,
        win_w=win_w,
        win_h=win_h,
        shots_dir=shots_dir,
        shots=shots,
        build_names=build_names,
    )


@dataclass
class CaptionSpan:
    t0: float
    t1: float
    title: str
    subtitle: str = ""
    chip: Optional[str] = None


@dataclass
class ShotBeat:
    t0: float
    t1: float
    shot_name: str
    prev_shot_name: Optional[str]
    crossfade: float
    cam_start: Rect
    cam_end: Rect
    cam_anim_dur: float
    print_page_overlay: bool = False
    print_slide_dur: float = 0.6


@dataclass
class CursorKeyframe:
    t0: float
    t1: float
    p0: Tuple[float, float]
    p1: Tuple[float, float]
    visible: bool = True


@dataclass
class ClickEvent:
    t: float
    dip_pos: Tuple[float, float]


@dataclass
class Timeline:
    total_duration: float
    intro_duration: float
    intro_crossfade: float
    outro_start: float
    outro_duration: float
    outro_crossfade: float
    beats: List[ShotBeat]
    captions: List[CaptionSpan]
    cursor_keys: List[CursorKeyframe]
    clicks: List[ClickEvent]


def build_timeline(manifest: Manifest) -> Timeline:
    """
    Manifest içindeki mevcut ekran görüntülerine ve hedeflere göre
    eksik görüntü/hedefleri zarifçe atlayan tam zaman çizelgesini oluşturur.
    """
    win_w, win_h = manifest.win_w, manifest.win_h
    full_view: Rect = (0.0, 0.0, win_w, win_h)

    def has_shot(name: str) -> bool:
        if name not in manifest.shots:
            return False
        s_path = manifest.shots_dir / manifest.shots[name].file
        return s_path.exists() or len(manifest.shots) > 0

    def get_target(shot_name: str, key: str, fallback_key: Optional[str] = None) -> Optional[Rect]:
        s = manifest.shots.get(shot_name)
        if not s:
            return None
        if key in s.targets:
            return s.targets[key]
        if fallback_key and fallback_key in s.targets:
            return s.targets[fallback_key]
        return None

    beats: List[ShotBeat] = []
    captions: List[CaptionSpan] = []
    cursor_keys: List[CursorKeyframe] = []
    clicks: List[ClickEvent] = []

    cur_cam: Rect = full_view
    cur_cursor: Tuple[float, float] = (win_w * 0.5, win_h * 0.5)
    last_shot: Optional[str] = None

    # S1: Giriş (Intro)
    s1_cfg = STORYBOARD["s1_intro"]
    intro_dur = float(s1_cfg["duration"])
    intro_xfade = float(s1_cfg["crossfade_out"])
    # S2 görüntüsü intro'nun son 0.4 saniyesinde görünmeye başlar
    t = intro_dur - intro_xfade

    def add_beat(
        shot_name: str,
        duration: float,
        target_cam: Optional[Rect] = None,
        crossfade: float = 0.3,
        cam_anim_dur: float = 0.8,
        print_overlay: bool = False,
        print_slide_dur: float = 0.6,
    ) -> Tuple[float, float]:
        nonlocal t, cur_cam, last_shot
        cam_next = target_cam if target_cam is not None else cur_cam
        prev = last_shot if last_shot is not None else shot_name
        xf = crossfade if last_shot is not None and last_shot != shot_name else 0.0
        b = ShotBeat(
            t0=t,
            t1=t + duration,
            shot_name=shot_name,
            prev_shot_name=prev,
            crossfade=xf,
            cam_start=cur_cam,
            cam_end=cam_next,
            cam_anim_dur=min(cam_anim_dur, duration),
            print_page_overlay=print_overlay,
            print_slide_dur=print_slide_dur,
        )
        beats.append(b)
        cur_cam = cam_next
        last_shot = shot_name
        t0, t1 = t, t + duration
        t = t1
        return t0, t1

    def move_cursor(t0: float, t1: float, dest: Optional[Tuple[float, float]], click_at_end: bool = False, visible: bool = True) -> None:
        nonlocal cur_cursor
        target_pt = dest if dest is not None else cur_cursor
        dur = max(0.05, t1 - t0)
        # İmleç hareketi vuruşun sonuna doğru tamamlanır ve tıklama tam sonda gerçekleşir
        move_dur = min(0.45, max(0.20, dur - 0.12)) if dur > 0.25 else dur * 0.8
        cursor_keys.append(CursorKeyframe(t0=t0, t1=t0 + move_dur, p0=cur_cursor, p1=target_pt, visible=visible))
        if t0 + move_dur < t1:
            cursor_keys.append(CursorKeyframe(t0=t0 + move_dur, t1=t1, p0=target_pt, p1=target_pt, visible=visible))
        cur_cursor = target_pt
        if click_at_end and visible:
            clicks.append(ClickEvent(t=t0 + move_dur, dip_pos=target_pt))

    # Devre alanı birleşim dikdörtgenini hesapla (tüm build_* lastAdded hedefleri)
    build_rects: List[Rect] = []
    for bname in manifest.build_names:
        r = get_target(bname, "lastAdded")
        if r:
            build_rects.append(r)
    if not build_rects and "empty" in manifest.shots:
        c_rect = get_target("empty", "canvas")
        if c_rect:
            build_rects.append(c_rect)

    circuit_union = union_rects(build_rects)
    circuit_cam = fit_view_rect(
        circuit_union, win_w, win_h, padding=float(STORYBOARD["s2_build"]["padding_dip"])
    ) if circuit_union else full_view

    # Kamerayı çizim alanının içinde tut (soldaki kenar çubuğu kadraja girmesin)
    canvas_rect = get_target("empty", "canvas") if has_shot("empty") else None
    if circuit_union and canvas_rect:
        vx, vy, vw, vh = circuit_cam
        min_x = canvas_rect[0]
        max_x = canvas_rect[0] + canvas_rect[2] - vw
        if max_x >= min_x:
            circuit_cam = (clamp(vx, min_x, max_x), vy, vw, vh)

    def practice_cam(shot: str) -> Rect:
        """Alıştırma karesi: cevap kutuları ve Kontrol et düğmesine yakınlaş (tüm panel çok uzun)."""
        rs = [r for r in (get_target(shot, "answer1"), get_target(shot, "answer2"),
                          get_target(shot, "checkButton")) if r]
        focus = union_rects(rs) if rs else get_target(shot, "panel")
        return fit_view_rect(focus, win_w, win_h, padding=70.0) if focus else cur_cam

    def explain_cam(shot: str) -> Rect:
        """Anlatım karesi: çözülmüş devre ile anlatım paneli yan yana görünsün."""
        exp = get_target(shot, "explanation", fallback_key="panel")
        focus = union_rects([r for r in (circuit_union, exp) if r])
        return fit_view_rect(focus, win_w, win_h, padding=30.0) if focus else cur_cam

    # S2: Devreyi çizin
    s2_cfg = STORYBOARD["s2_build"]
    s2_start = t
    if has_shot("empty"):
        b_t0, b_t1 = add_beat("empty", float(s2_cfg["empty_duration"]), target_cam=circuit_cam, crossfade=0.0, cam_anim_dur=0.6)
        move_cursor(b_t0, b_t1, cur_cursor, click_at_end=False)

    for bname in manifest.build_names:
        if not has_shot(bname):
            continue
        step_dur = float(s2_cfg["step_duration"])
        b_t0, b_t1 = add_beat(bname, step_dur, target_cam=circuit_cam, crossfade=float(s2_cfg["crossfade"]), cam_anim_dur=0.4)
        sb_rect = get_target(bname, "sidebarItem")
        la_rect = get_target(bname, "lastAdded")
        if sb_rect and la_rect:
            # Eleman ekleme: kenar çubuğundan devre elemanına git ve tıkla
            cur_cursor = rect_center(sb_rect)
            move_cursor(b_t0, b_t1, rect_center(la_rect), click_at_end=True)
        elif la_rect:
            # Tel bağlama: doğrudan eklenen tele git ve tıkla
            move_cursor(b_t0, b_t1, rect_center(la_rect), click_at_end=True)
        else:
            move_cursor(b_t0, b_t1, None, click_at_end=False)

    if t > s2_start:
        captions.append(CaptionSpan(s2_start, t, s2_cfg["title"], s2_cfg["subtitle"], s2_cfg["chip"]))

    # S3: Çöz'e basın
    s3_cfg = STORYBOARD["s3_solve"]
    s3_start = t
    if has_shot("method_set"):
        b_t0, b_t1 = add_beat("method_set", float(s3_cfg["method_duration"]), target_cam=full_view, crossfade=float(s3_cfg["crossfade"]), cam_anim_dur=0.8)
        solve_rect = get_target("method_set", "solveButton")
        move_cursor(b_t0, b_t1, rect_center(solve_rect) if solve_rect else None, click_at_end=(solve_rect is not None))

    if has_shot("solved"):
        b_t0, b_t1 = add_beat("solved", float(s3_cfg["solved_duration"]), target_cam=circuit_cam, crossfade=float(s3_cfg["crossfade"]), cam_anim_dur=0.85)
        move_cursor(b_t0, b_t1, None, click_at_end=False, visible=False)

    if t > s3_start:
        captions.append(CaptionSpan(s3_start, t, s3_cfg["title"], s3_cfg["subtitle"], s3_cfg["chip"]))

    # S4: Her adım Türkçe anlatılır
    s4_cfg = STORYBOARD["s4_explain"]
    s4_start = t
    explain_shots = ["explain_1", "explain_2", "explain_3", "explain_4"]
    for ename in explain_shots:
        if not has_shot(ename):
            continue
        exp_rect = get_target(ename, "explanation", fallback_key="panel")
        exp_cam = explain_cam(ename)
        b_t0, b_t1 = add_beat(ename, float(s4_cfg["step_duration"]), target_cam=exp_cam, crossfade=float(s4_cfg["crossfade"]), cam_anim_dur=0.75)
        move_cursor(b_t0, b_t1, rect_center(exp_rect) if exp_rect else None, click_at_end=False, visible=False)

    if has_shot("results_tab"):
        res_cam = explain_cam("results_tab")
        b_t0, b_t1 = add_beat("results_tab", float(s4_cfg["results_duration"]), target_cam=res_cam, crossfade=float(s4_cfg["crossfade"]), cam_anim_dur=0.7)
        move_cursor(b_t0, b_t1, None, click_at_end=False, visible=False)

    if t > s4_start:
        captions.append(CaptionSpan(s4_start, t, s4_cfg["title"], s4_cfg["subtitle"], s4_cfg["chip"]))

    # S5: Kendinizi deneyin
    s5_cfg = STORYBOARD["s5_practice"]
    s5_start = t
    if has_shot("practice_blank"):
        p_cam = practice_cam("practice_blank")
        b_t0, b_t1 = add_beat("practice_blank", float(s5_cfg["blank_duration"]), target_cam=p_cam, crossfade=float(s5_cfg["crossfade"]), cam_anim_dur=0.8)
        ans1 = get_target("practice_blank", "answer1")
        move_cursor(b_t0, b_t1, rect_center(ans1) if ans1 else None, click_at_end=(ans1 is not None))

    if has_shot("practice_typed"):
        p_cam = practice_cam("practice_typed")
        b_t0, b_t1 = add_beat("practice_typed", float(s5_cfg["typed_duration"]), target_cam=p_cam, crossfade=float(s5_cfg["crossfade"]), cam_anim_dur=0.5)
        chk = get_target("practice_typed", "checkButton")
        move_cursor(b_t0, b_t1, rect_center(chk) if chk else None, click_at_end=(chk is not None))

    if has_shot("practice_checked"):
        p_cam = practice_cam("practice_checked")
        b_t0, b_t1 = add_beat("practice_checked", float(s5_cfg["checked_duration"]), target_cam=p_cam, crossfade=float(s5_cfg["crossfade"]), cam_anim_dur=0.5)
        ans2 = get_target("practice_checked", "answer2")
        move_cursor(b_t0, b_t1, rect_center(ans2) if ans2 else None, click_at_end=(ans2 is not None))

    if has_shot("practice_wrong"):
        p_cam = practice_cam("practice_wrong")
        b_t0, b_t1 = add_beat("practice_wrong", float(s5_cfg["wrong_duration"]), target_cam=p_cam, crossfade=float(s5_cfg["crossfade"]), cam_anim_dur=0.5)
        move_cursor(b_t0, b_t1, None, click_at_end=False)

    if t > s5_start:
        captions.append(CaptionSpan(s5_start, t, s5_cfg["title"], s5_cfg["subtitle"], s5_cfg["chip"]))

    # S6: Sınıf kodu ve Alıştırma yaprağı
    s6_p1 = STORYBOARD["s6_classroom"]["part1"]
    if has_shot("practice_blank"):
        p1_start = t
        cc_rect = get_target("practice_blank", "codeCard", fallback_key="panel")
        cc_cam = fit_view_rect(cc_rect, win_w, win_h, padding=60.0) if cc_rect else cur_cam
        b_t0, b_t1 = add_beat("practice_blank", float(s6_p1["duration"]), target_cam=cc_cam, crossfade=float(s6_p1["crossfade"]), cam_anim_dur=0.8)
        move_cursor(b_t0, b_t1, rect_center(cc_rect) if cc_rect else None, click_at_end=False, visible=False)
        captions.append(CaptionSpan(p1_start, t, s6_p1["title"], s6_p1["subtitle"], s6_p1["chip"]))

    s6_p2 = STORYBOARD["s6_classroom"]["part2"]
    if has_shot("print_page"):
        p2_start = t
        bg_shot = last_shot if last_shot else ("practice_blank" if has_shot("practice_blank") else "print_page")
        tot_p2 = float(s6_p2["slide_duration"]) + float(s6_p2["hold_duration"])
        b_t0, b_t1 = add_beat(
            bg_shot,
            tot_p2,
            target_cam=full_view,  # sayfa sakin, tam pencere görünümünün üzerine gelsin
            crossfade=0.0,
            cam_anim_dur=0.6,
            print_overlay=True,
            print_slide_dur=float(s6_p2["slide_duration"]),
        )
        move_cursor(b_t0, b_t1, None, click_at_end=False, visible=False)
        captions.append(CaptionSpan(p2_start, t, s6_p2["title"], s6_p2["subtitle"], s6_p2["chip"]))

    # S7: Koyu tema ve Yapay zekâ
    s7_dark = STORYBOARD["s7_extras"]["dark"]
    if has_shot("dark_solved"):
        d_start = t
        b_t0, b_t1 = add_beat("dark_solved", float(s7_dark["duration"]), target_cam=full_view, crossfade=float(s7_dark["crossfade"]), cam_anim_dur=0.75)
        move_cursor(b_t0, b_t1, None, click_at_end=False, visible=False)
        captions.append(CaptionSpan(d_start, t, s7_dark["title"], s7_dark["subtitle"], s7_dark["chip"]))

    s7_ai = STORYBOARD["s7_extras"]["ai"]
    if has_shot("ai_setup"):
        ai_start = t
        ob_rect = get_target("ai_setup", "onboardingCard")
        ob_cam = fit_view_rect(ob_rect, win_w, win_h, padding=60.0) if ob_rect else full_view
        b_t0, b_t1 = add_beat("ai_setup", float(s7_ai["duration"]), target_cam=ob_cam, crossfade=float(s7_ai["crossfade"]), cam_anim_dur=0.8)
        move_cursor(b_t0, b_t1, rect_center(ob_rect) if ob_rect else None, click_at_end=False, visible=False)
        captions.append(CaptionSpan(ai_start, t, s7_ai["title"], s7_ai["subtitle"], s7_ai["chip"]))

    # S8: Çıkış (Outro)
    s8_cfg = STORYBOARD["s8_outro"]
    outro_xfade = float(s8_cfg["crossfade_in"])
    outro_dur = float(s8_cfg["duration"])
    outro_start = max(intro_dur, t - outro_xfade)
    total_duration = outro_start + outro_dur

    return Timeline(
        total_duration=total_duration,
        intro_duration=intro_dur,
        intro_crossfade=intro_xfade,
        outro_start=outro_start,
        outro_duration=outro_dur,
        outro_crossfade=outro_xfade,
        beats=beats,
        captions=captions,
        cursor_keys=cursor_keys,
        clicks=clicks,
    )


# ---------------------------------------------------------------------------
# Görsel Oluşturucu (Renderer) ve Önbellek (Cache)
# ---------------------------------------------------------------------------
class VideoRenderer:
    """Kareleri önbellekli olarak çizen sınıf."""

    def __init__(self, manifest: Manifest, timeline: Timeline):
        self.manifest = manifest
        self.timeline = timeline
        self.card_w = CARD_W
        self.card_h = int(round(CARD_W * manifest.win_h / max(1.0, manifest.win_w)))
        self.card_rect = (CARD_X, CARD_Y, self.card_w, self.card_h)

        self._shot_images: Dict[str, Image.Image] = {}
        self._card_cache: Dict[Tuple[str, int, int, int, int], Image.Image] = {}
        self._caption_cache: Dict[Tuple[str, str, Optional[str]], Image.Image] = {}

        # Yuvarlatılmış kart maskesi ve kenarlığı (bir kez oluşturulur)
        self._card_mask = self._make_rounded_mask(self.card_w, self.card_h, CARD_RADIUS)
        self._card_border_overlay = self._make_card_border(self.card_w, self.card_h, CARD_RADIUS)
        # Kart gölgesi (bir kez oluşturulur ve önbelleklenir)
        self._base_with_shadow = self._make_base_with_shadow()
        self._cursor_sprite = self._make_cursor_sprite()
        self._logo_orig = self._load_logo()
        self._print_sheet_sprite: Optional[Image.Image] = None

    def _load_logo(self) -> Image.Image:
        if LOGO_PATH.exists():
            try:
                return Image.open(LOGO_PATH).convert("RGBA")
            except Exception:
                pass
        # Yedek logo
        img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((16, 16, 240, 240), radius=48, fill=COLOR_ACCENT)
        return img

    def _make_rounded_mask(self, w: int, h: int, radius: int) -> Image.Image:
        # 2x süper örnekleme ile pürüzsüz köşe maskesi
        mask2x = Image.new("L", (w * 2, h * 2), 0)
        d = ImageDraw.Draw(mask2x)
        d.rounded_rectangle((0, 0, w * 2 - 1, h * 2 - 1), radius=radius * 2, fill=255)
        return mask2x.resize((w, h), Image.Resampling.LANCZOS)

    def _make_card_border(self, w: int, h: int, radius: int) -> Image.Image:
        border2x = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
        d = ImageDraw.Draw(border2x)
        d.rounded_rectangle(
            (1, 1, w * 2 - 2, h * 2 - 2),
            radius=radius * 2,
            outline=(*COLOR_BORDER, 255),
            width=2,
        )
        return border2x.resize((w, h), Image.Resampling.LANCZOS)

    def _make_base_with_shadow(self) -> Image.Image:
        """Arka plan + kart yumuşak düşme gölgesini BİR KEZ oluşturur."""
        bg = Image.new("RGBA", (VIDEO_W, VIDEO_H), (*COLOR_BG, 255))
        shadow = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(shadow)
        sx0 = CARD_X
        sy0 = CARD_Y + 16
        sx1 = CARD_X + self.card_w
        sy1 = CARD_Y + self.card_h + 16
        alpha = int(round(255 * 0.12))
        d.rounded_rectangle((sx0, sy0, sx1, sy1), radius=CARD_RADIUS, fill=(0, 0, 0, alpha))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=40))
        return Image.alpha_composite(bg, shadow)

    def _make_cursor_sprite(self) -> Image.Image:
        """~30 piksel yüksekliğinde ok imlecini (gölge + siyah dış çizgi + beyaz dolgu) üretir."""
        size = 64
        # 2x çözünürlükte çizip küçültelim
        canvas = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
        pts = [
            (16, 16),
            (16, 76),
            (32, 62),
            (44, 86),
            (54, 81),
            (42, 57),
            (62, 57),
        ]
        # Gölge katmanı
        sh = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        sh_pts = [(x + 3, y + 5) for (x, y) in pts]
        sd.polygon(sh_pts, fill=(0, 0, 0, 95))
        sh = sh.filter(ImageFilter.GaussianBlur(radius=5))

        # İmleç katmanı
        d = ImageDraw.Draw(canvas)
        d.polygon(pts, fill=(*COLOR_WHITE, 255), outline=(*COLOR_TEXT, 255))
        # 2px kalınlığında kenarlık için çizgileri birleştirelim
        d.line(pts + [pts[0]], fill=(*COLOR_TEXT, 255), width=4, joint="curve")

        out = Image.alpha_composite(sh, canvas)
        return out.resize((size, size), Image.Resampling.LANCZOS)

    def _get_shot_image(self, shot_name: str) -> Image.Image:
        if shot_name in self._shot_images:
            return self._shot_images[shot_name]
        info = self.manifest.shots.get(shot_name)
        if info:
            p = self.manifest.shots_dir / info.file
            if p.exists():
                img = Image.open(p).convert("RGB")
                self._shot_images[shot_name] = img
                return img
        # Eksik dosya durumunda zarif yedek görüntü
        w = int(round(self.manifest.win_w * self.manifest.scale))
        h = int(round(self.manifest.win_h * self.manifest.scale))
        fallback = Image.new("RGB", (w, h), (235, 235, 240))
        self._shot_images[shot_name] = fallback
        return fallback

    def render_card_content(self, shot_name: str, view_rect: Rect) -> Image.Image:
        """
        Verilen ekran görüntüsünü (shot_name) ve DIP kamera dikdörtgenini (view_rect)
        kullanarak kart içeriğini kırpar, LANCZOS ile boyutlandırır ve önbellekler.
        """
        scale = self.manifest.scale
        vx, vy, vw, vh = view_rect
        # Önbellek anahtarı: alt piksel titremesini önlemek ve sabit kareleri yakalamak için yuvarla
        qx = int(round(vx * scale * 2))
        qy = int(round(vy * scale * 2))
        qw = int(round(vw * scale * 2))
        qh = int(round(vh * scale * 2))
        key = (shot_name, qx, qy, qw, qh)
        if key in self._card_cache:
            return self._card_cache[key]

        src = self._get_shot_image(shot_name)
        sw, sh = src.size
        box = (
            clamp(vx * scale, 0.0, sw - 1.0),
            clamp(vy * scale, 0.0, sh - 1.0),
            clamp((vx + vw) * scale, 1.0, float(sw)),
            clamp((vy + vh) * scale, 1.0, float(sh)),
        )
        cropped = src.crop((int(round(box[0])), int(round(box[1])), int(round(box[2])), int(round(box[3]))))
        resized = cropped.resize((self.card_w, self.card_h), Image.Resampling.LANCZOS)

        # Önbellek boyutunu makul sınırda tut
        if len(self._card_cache) > 48:
            # Sabit olmayan ara geçiş karelerini temizle
            first_key = next(iter(self._card_cache))
            del self._card_cache[first_key]
        self._card_cache[key] = resized
        return resized

    def _get_print_sheet_sprite(self) -> Image.Image:
        if self._print_sheet_sprite is not None:
            return self._print_sheet_sprite
        src = self._get_shot_image("print_page")
        sw, sh = src.size
        target_h = 800
        target_w = int(round(target_h * (sw / max(1.0, float(sh)))))
        sheet = src.resize((target_w, target_h), Image.Resampling.LANCZOS).convert("RGBA")

        pad = 60
        canvas = Image.new("RGBA", (target_w + pad * 2, target_h + pad * 2), (0, 0, 0, 0))
        sd = ImageDraw.Draw(canvas)
        sd.rounded_rectangle(
            (pad, pad + 12, pad + target_w, pad + target_h + 12),
            radius=8,
            fill=(0, 0, 0, 55),
        )
        canvas = canvas.filter(ImageFilter.GaussianBlur(radius=24))
        canvas.paste(sheet, (pad, pad))
        d = ImageDraw.Draw(canvas)
        d.rectangle((pad, pad, pad + target_w - 1, pad + target_h - 1), outline=(*COLOR_BORDER, 255), width=1)
        self._print_sheet_sprite = canvas
        return canvas

    def _get_caption_strip(self, title: str, subtitle: str, chip: Optional[str]) -> Image.Image:
        key = (title, subtitle, chip)
        if key in self._caption_cache:
            return self._caption_cache[key]

        strip = Image.new("RGBA", (VIDEO_W, 195), (0, 0, 0, 0))
        d = ImageDraw.Draw(strip)
        f_title = get_font("semibold", 52)
        f_sub = get_font("regular", 28)
        f_chip = get_font("bold", 24)

        tb = d.textbbox((0, 0), title, font=f_title)
        tw = tb[2] - tb[0]

        chip_diam = 44
        chip_gap = 16
        total_w = tw + (chip_diam + chip_gap if chip else 0)
        start_x = (VIDEO_W - total_w) // 2
        title_y = 56

        if chip:
            center_y = title_y + (tb[1] + tb[3]) * 0.5
            cy = int(round(center_y - chip_diam * 0.5))
            d.ellipse((start_x, cy, start_x + chip_diam, cy + chip_diam), fill=(*COLOR_ACCENT, 255))
            cb = d.textbbox((0, 0), chip, font=f_chip)
            cw = cb[2] - cb[0]
            ch = cb[3] - cb[1]
            d.text(
                (start_x + (chip_diam - cw) / 2.0 - cb[0], cy + (chip_diam - ch) / 2.0 - cb[1]),
                chip,
                font=f_chip,
                fill=(*COLOR_WHITE, 255),
            )
            text_x = start_x + chip_diam + chip_gap
        else:
            text_x = start_x

        d.text((text_x, title_y), title, font=f_title, fill=(*COLOR_TEXT, 255))

        if subtitle:
            sb = d.textbbox((0, 0), subtitle, font=f_sub)
            sw = sb[2] - sb[0]
            sub_x = (VIDEO_W - sw) // 2
            sub_y = title_y + 68
            d.text((sub_x, sub_y), subtitle, font=f_sub, fill=(*COLOR_TEXT_SEC, 255))

        self._caption_cache[key] = strip
        return strip

    def _render_scene_frame(self, t: float) -> Image.Image:
        """Uygulama kartı, başlıklar, imleç ve tıklama halkalarını içeren sahne karesini çizer."""
        frame = self._base_with_shadow.copy()

        # Mevcut vuruşu (beat) bul
        beats = self.timeline.beats
        if not beats:
            return frame

        active_beat = beats[-1]
        for b in beats:
            if b.t0 <= t <= b.t1:
                active_beat = b
                break
            if t < b.t0:
                active_beat = b
                break

        local_t = max(0.0, t - active_beat.t0)
        cam_u = ease_in_out_cubic(local_t / max(1e-6, active_beat.cam_anim_dur))
        cur_view = lerp_rect(active_beat.cam_start, active_beat.cam_end, cam_u)

        card_curr = self.render_card_content(active_beat.shot_name, cur_view)
        if active_beat.crossfade > 0.0 and active_beat.prev_shot_name and local_t < active_beat.crossfade:
            alpha = ease_in_out_cubic(local_t / active_beat.crossfade)
            card_prev = self.render_card_content(active_beat.prev_shot_name, cur_view)
            card_rgb = Image.blend(card_prev, card_curr, alpha)
        else:
            card_rgb = card_curr

        # Kartı yuvarlatılmış maske ve kenarlıkla ana kareye yerleştir
        frame.paste(card_rgb.convert("RGBA"), (CARD_X, CARD_Y), self._card_mask)
        frame.alpha_composite(self._card_border_overlay, dest=(CARD_X, CARD_Y))

        # S6 2. Bölüm: Alıştırma yaprağı (print_page) sağdan kayarak gelir
        if active_beat.print_page_overlay:
            sheet = self._get_print_sheet_sprite()
            sw, sh = sheet.size
            u_slide = ease_out_cubic(local_t / max(1e-6, active_beat.print_slide_dur))
            # Kartın üzerine arka plan renginde yarı saydam bir perde: sayfa öne çıksın
            veil_alpha = int(round(150 * u_slide))
            if veil_alpha > 0:
                veil = Image.new("RGBA", self._card_mask.size, (*COLOR_BG, 0))
                veil.putalpha(self._card_mask.point(lambda p: p * veil_alpha // 255))
                frame.alpha_composite(veil, dest=(CARD_X, CARD_Y))
            target_x = (VIDEO_W - sw) // 2
            start_x = VIDEO_W + 40
            cur_x = int(round(lerp(start_x, target_x, u_slide)))
            cur_y = CARD_Y + (self.card_h - sh) // 2
            frame.alpha_composite(sheet, dest=(cur_x, cur_y))

        # Tıklama dalgalarını (ripple) çiz
        for clk in self.timeline.clicks:
            dt = t - clk.t
            if 0.0 <= dt <= 0.45:
                u_clk = dt / 0.45
                radius = lerp(2.0, 36.0, ease_out_cubic(u_clk))
                alpha = int(round(255 * 0.6 * (1.0 - u_clk)))
                if alpha > 0:
                    px, py = dip_to_video_px(clk.dip_pos, cur_view, self.card_rect)
                    r_int = int(round(radius)) + 6
                    ring = Image.new("RGBA", (r_int * 2, r_int * 2), (0, 0, 0, 0))
                    rd = ImageDraw.Draw(ring)
                    rd.ellipse(
                        (6, 6, r_int * 2 - 6, r_int * 2 - 6),
                        outline=(*COLOR_ACCENT, alpha),
                        width=3,
                    )
                    frame.alpha_composite(
                        ring,
                        dest=(int(round(px)) - r_int, int(round(py)) - r_int),
                    )

        # İmleci çiz
        cur_kf: Optional[CursorKeyframe] = None
        for kf in self.timeline.cursor_keys:
            if kf.t0 <= t <= kf.t1:
                cur_kf = kf
                break
        if cur_kf and cur_kf.visible:
            u_cur = ease_in_out_cubic((t - cur_kf.t0) / max(1e-6, cur_kf.t1 - cur_kf.t0))
            dip_x = lerp(cur_kf.p0[0], cur_kf.p1[0], u_cur)
            dip_y = lerp(cur_kf.p0[1], cur_kf.p1[1], u_cur)
            px, py = dip_to_video_px((dip_x, dip_y), cur_view, self.card_rect)
            # İmlecin ucu sprite içinde (8, 8) noktasındadır
            frame.alpha_composite(self._cursor_sprite, dest=(int(round(px)) - 8, int(round(py)) - 8))

        # Üst başlıkları (Captions) çiz (giriş: 0.35s y +14->0, çıkış: 0.25s)
        for cap in self.timeline.captions:
            if cap.t0 <= t <= cap.t1:
                in_dt = t - cap.t0
                out_dt = cap.t1 - t
                alpha = 1.0
                y_off = 0.0
                if in_dt < 0.35:
                    u_in = ease_out_cubic(in_dt / 0.35)
                    alpha = min(alpha, u_in)
                    y_off = lerp(14.0, 0.0, u_in)
                if out_dt < 0.25:
                    u_out = clamp(out_dt / 0.25, 0.0, 1.0)
                    alpha = min(alpha, u_out)

                strip = self._get_caption_strip(cap.title, cap.subtitle, cap.chip)
                if alpha < 0.999:
                    strip = strip.copy()
                    a_ch = strip.getchannel("A").point(lambda p: int(p * alpha))
                    strip.putalpha(a_ch)
                frame.alpha_composite(strip, dest=(0, int(round(y_off))))
                break

        return frame

    def _render_intro_frame(self, t: float) -> Image.Image:
        """S1: Giriş sahnesini çizer."""
        frame = Image.new("RGBA", (VIDEO_W, VIDEO_H), (*COLOR_BG, 255))
        s1_cfg = STORYBOARD["s1_intro"]

        # Logo: 240px, y≈400 merkezli. İlk kare de tam görünür olmalı: GitHub videonun
        # ilk karesini kapak resmi olarak gösterir. Yalnızca hafif bir büyüme (0.96→1.0).
        u_logo = 1.0
        scale = lerp(0.96, 1.0, ease_out_cubic(clamp(t / 1.2, 0.0, 1.0)))
        logo_sz = max(1, int(round(240 * scale)))
        logo = self._logo_orig.resize((logo_sz, logo_sz), Image.Resampling.LANCZOS)
        frame.alpha_composite(logo, dest=((VIDEO_W - logo_sz) // 2, 400 - logo_sz // 2))

        # Başlık ve Slogan
        txt_layer = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(txt_layer)

        f_title = get_font("bold", 96)
        title = s1_cfg["title"]
        tb = d.textbbox((0, 0), title, font=f_title)
        tw = tb[2] - tb[0]
        title_alpha = int(round(255 * u_logo))
        d.text(((VIDEO_W - tw) // 2, 555), title, font=f_title, fill=(*COLOR_TEXT, title_alpha))

        # Slogan: baştan görünür, y≈690
        u_tag = 1.0
        if u_tag > 0.0:
            f_tag = get_font("regular", 34)
            tagline = s1_cfg["tagline"]
            sb = d.textbbox((0, 0), tagline, font=f_tag)
            sw = sb[2] - sb[0]
            tag_alpha = int(round(255 * u_tag))
            d.text(((VIDEO_W - sw) // 2, 690), tagline, font=f_tag, fill=(*COLOR_TEXT_SEC, tag_alpha))

        frame.alpha_composite(txt_layer)
        return frame

    def _render_outro_frame(self, local_t: float) -> Image.Image:
        """S8: Çıkış (Outro) sahnesini çizer."""
        frame = Image.new("RGBA", (VIDEO_W, VIDEO_H), (*COLOR_BG, 255))
        s8_cfg = STORYBOARD["s8_outro"]

        # İlk 0.6 saniyede yumuşak giriş, son 1.5 saniye tamamen sabit
        u_in = ease_out_cubic(clamp(local_t / 0.6, 0.0, 1.0))

        logo_sz = 160
        logo = self._logo_orig.resize((logo_sz, logo_sz), Image.Resampling.LANCZOS)
        if u_in < 0.999:
            logo = logo.copy()
            logo.putalpha(logo.getchannel("A").point(lambda p: int(p * u_in)))
        frame.alpha_composite(logo, dest=((VIDEO_W - logo_sz) // 2, 230))

        layer = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        alpha = int(round(255 * u_in))

        # "Devre Analizi" 72px bold
        f_title = get_font("bold", 72)
        title = s8_cfg["title"]
        tb = d.textbbox((0, 0), title, font=f_title)
        tw = tb[2] - tb[0]
        d.text(((VIDEO_W - tw) // 2, 420), title, font=f_title, fill=(*COLOR_TEXT, alpha))

        # Üç hap (pills): "Ücretsiz", "Açık kaynak", "İnternetsiz" — ortak taban çizgisi (baseline)
        f_pill = get_font("semibold", 26)
        pills: List[str] = s8_cfg["pills"]
        pill_pad_x = 28
        pill_h = 52
        pill_gap = 20
        pill_widths: List[int] = []
        ref_bbox = d.textbbox((0, 0), "Ücretsizİnternetsiz", font=f_pill)
        ref_h = ref_bbox[3] - ref_bbox[1]
        ref_top = ref_bbox[1]

        for p_txt in pills:
            pb = d.textbbox((0, 0), p_txt, font=f_pill)
            pill_widths.append((pb[2] - pb[0]) + pill_pad_x * 2)

        total_pills_w = sum(pill_widths) + pill_gap * (len(pills) - 1)
        px = (VIDEO_W - total_pills_w) // 2
        py = 545
        text_y = py + (pill_h - ref_h) / 2.0 - ref_top
        for p_txt, pw in zip(pills, pill_widths):
            d.rounded_rectangle(
                (px, py, px + pw, py + pill_h),
                radius=pill_h // 2,
                fill=(*COLOR_PILL_BG, alpha),
            )
            pb = d.textbbox((0, 0), p_txt, font=f_pill)
            tw_p = pb[2] - pb[0]
            d.text(
                (px + (pw - tw_p) / 2.0 - pb[0], text_y),
                p_txt,
                font=f_pill,
                fill=(*COLOR_ACCENT, alpha),
            )
            px += pw + pill_gap

        # GitHub adresi 34px accent
        f_repo = get_font("semibold", 34)
        repo = s8_cfg["repo"]
        rb = d.textbbox((0, 0), repo, font=f_repo)
        rw = rb[2] - rb[0]
        d.text(((VIDEO_W - rw) // 2, 650), repo, font=f_repo, fill=(*COLOR_ACCENT, alpha))

        # Lisans 22px secondary
        f_lic = get_font("regular", 22)
        lic = s8_cfg["license"]
        lb = d.textbbox((0, 0), lic, font=f_lic)
        lw = lb[2] - lb[0]
        d.text(((VIDEO_W - lw) // 2, 735), lic, font=f_lic, fill=(*COLOR_TEXT_SEC, alpha))

        frame.alpha_composite(layer)
        return frame

    def render_frame(self, t: float) -> Image.Image:
        """Zaman çizelgesindeki t (saniye) anına ait 1920x1080 RGB kareyi döndürür."""
        tl = self.timeline
        s1_end = tl.intro_duration
        s1_xf_start = tl.intro_duration - tl.intro_crossfade

        # S1 Giriş ve S2'ye geçiş
        if t < s1_xf_start:
            return self._render_intro_frame(t).convert("RGB")
        if t < s1_end:
            u = ease_in_out_cubic((t - s1_xf_start) / max(1e-6, tl.intro_crossfade))
            f_intro = self._render_intro_frame(t).convert("RGB")
            f_scene = self._render_scene_frame(t).convert("RGB")
            return Image.blend(f_intro, f_scene, u)

        # S8 Çıkış ve geçişi
        if t >= tl.outro_start:
            local_outro_t = t - tl.outro_start
            if local_outro_t < tl.outro_crossfade:
                u = ease_in_out_cubic(local_outro_t / max(1e-6, tl.outro_crossfade))
                f_scene = self._render_scene_frame(t).convert("RGB")
                f_outro = self._render_outro_frame(local_outro_t).convert("RGB")
                return Image.blend(f_scene, f_outro, u)
            return self._render_outro_frame(local_outro_t).convert("RGB")

        return self._render_scene_frame(t).convert("RGB")


# ---------------------------------------------------------------------------
# İletişim Sayfası (Contact Sheet), Poster ve FFmpeg Kodlayıcı
# ---------------------------------------------------------------------------
def write_contact_sheet_and_poster(
    renderer: VideoRenderer,
    contact_sheet_path: Path,
    poster_path: Path,
    sampled_seconds: Optional[Dict[int, Image.Image]] = None,
) -> None:
    """
    Saniyede bir kareden oluşan 6 sütunlu (320x180 küçük resimli) contact_sheet.png
    ve çıkış sahnesinden poster.png dosyalarını kaydeder.
    """
    total_sec = int(math.ceil(renderer.timeline.total_duration))
    cols = 6
    rows = max(1, int(math.ceil(total_sec / cols)))
    thumb_w, thumb_h = 320, 180

    sheet = Image.new("RGB", (cols * thumb_w, rows * thumb_h), COLOR_BG)
    f_lbl = get_font("semibold", 16)

    for sec in range(total_sec):
        if sampled_seconds and sec in sampled_seconds:
            full_img = sampled_seconds[sec]
        else:
            full_img = renderer.render_frame(float(sec))
        thumb = full_img.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        d = ImageDraw.Draw(thumb)
        label = f"t={sec}s"
        tb = d.textbbox((0, 0), label, font=f_lbl)
        lw = tb[2] - tb[0]
        lh = tb[3] - tb[1]
        d.rounded_rectangle((8, 8, 18 + lw, 16 + lh), radius=4, fill=(29, 29, 31))
        d.text((13, 10 - tb[1]), label, font=f_lbl, fill=COLOR_WHITE)

        c = sec % cols
        r = sec // cols
        sheet.paste(thumb, (c * thumb_w, r * thumb_h))

    contact_sheet_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(contact_sheet_path, format="PNG")

    # Poster: çıkış sahnesinin sabit kısmından bir kare
    poster_t = max(0.0, renderer.timeline.total_duration - 1.0)
    poster_img = renderer.render_frame(poster_t)
    poster_path.parent.mkdir(parents=True, exist_ok=True)
    poster_img.save(poster_path, format="PNG")


def mux_music_into_video(video_path: Path, music_path: Path) -> None:
    """
    Kodlanmış MP4 videosuna verilen WAV ses dosyasını (AAC 160k) ffmpeg ile
    geçici dosya üzerinden birleştirir (muxing) ve hedef dosyanın üzerine yazar.
    """
    if not music_path.exists():
        raise FileNotFoundError(f"Müzik dosyası bulunamadı: {music_path}")
    tmp_mux = video_path.with_suffix(".mux.mp4")
    mux_cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-i", str(music_path),
        "-map", "0:v",
        "-map", "1:a",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "160k",
        "-shortest",
        "-movflags", "+faststart",
        str(tmp_mux),
    ]
    subprocess.run(mux_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    tmp_mux.replace(video_path)


def encode_video(
    renderer: VideoRenderer,
    out_path: Path,
    fps: int = DEFAULT_FPS,
    music_path: Optional[Path] = None,
) -> Tuple[int, int]:
    """
    Ham RGB kareleri subprocess üzerinden ffmpeg'e aktararak MP4 üretir.
    İsteğe bağlı olarak --music ile verilen WAV dosyasını AAC olarak birleştirir.
    Dosya boyutu 9.5 MB sınırını aşarsa CRF değerini +3 artırarak yeniden kodlar.
    Döndürür: (toplam_kare_sayısı, dosya_boyutu_bayt).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total_frames = int(round(renderer.timeline.total_duration * fps))
    sampled_seconds: Dict[int, Image.Image] = {}

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{VIDEO_W}x{VIDEO_H}",
        "-r", str(fps),
        "-i", "-",
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out_path),
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert proc.stdin is not None

    # Ardışık aynı t anları veya sabit kareler için son ham baytları önbellekle
    for idx in range(total_frames):
        t = idx / float(fps)
        frame = renderer.render_frame(t)
        if idx % fps == 0:
            sampled_seconds[idx // fps] = frame
        proc.stdin.write(frame.tobytes())

    proc.stdin.close()
    stderr_out = proc.stderr.read() if proc.stderr else b""
    ret = proc.wait()
    if ret != 0:
        raise RuntimeError(f"ffmpeg hatası (kod {ret}): {stderr_out.decode('utf-8', errors='replace')}")

    # İletişim sayfası ve posteri kaydet
    contact_path = out_path.parent / "contact_sheet.png"
    poster_path = out_path.parent / "poster.png"
    write_contact_sheet_and_poster(renderer, contact_path, poster_path, sampled_seconds)

    # Müzik birleştirme (muxing) varsa boyut kontrolünden önce uygula
    if music_path is not None:
        mux_music_into_video(out_path, music_path)

    # 9.5 MB (9_961_472 bayt) boyut kontrolü (muxing sonrasında anlamlı kalır)
    max_bytes = int(9.5 * 1024 * 1024)
    crf = 20
    while out_path.stat().st_size > max_bytes and crf < 40:
        crf += 3
        tmp_path = out_path.with_suffix(f".crf{crf}.mp4")
        re_cmd = [
            "ffmpeg",
            "-y",
            "-i", str(out_path),
            "-c:v", "libx264",
            "-preset", "slow",
            "-crf", str(crf),
            "-pix_fmt", "yuv420p",
        ]
        if music_path is not None:
            re_cmd += ["-c:a", "copy"]
        re_cmd += ["-movflags", "+faststart", str(tmp_path)]
        subprocess.run(re_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        tmp_path.replace(out_path)

    return total_frames, out_path.stat().st_size


# ---------------------------------------------------------------------------
# Sentetik Test Verisi Üretici (--synthetic DIR)
# ---------------------------------------------------------------------------
def generate_synthetic_shots(target_dir: Path) -> None:
    """
    Geliştirme ve test için 3200x1800 piksel boyutunda sahte uygulama ekran görüntüleri,
    1587x2245 piksel boyutunda print_page.png ve eşleşen shots.json dosyası üretir.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    win_w, win_h = 1600, 900
    scale = 2
    img_w, img_h = win_w * scale, win_h * scale

    f_huge = get_font("bold", 96)
    f_med = get_font("semibold", 36)
    f_small = get_font("regular", 26)

    # Pencere DIP bölgeleri
    sidebar_dip = [16, 64, 240, 816]
    canvas_dip = [272, 64, 860, 816]
    panel_dip = [1148, 64, 436, 816]
    solve_btn_dip = [980, 14, 140, 40]
    theme_btn_dip = [1520, 14, 60, 40]

    shots_meta: List[Dict[str, Any]] = []

    def draw_window_shot(
        name: str,
        label: str,
        targets: Dict[str, List[int]],
        dark: bool = False,
        extra_draw: Optional[Callable[[ImageDraw.ImageDraw], None]] = None,
    ) -> None:
        bg_col = (28, 28, 32) if dark else (240, 242, 246)
        panel_col = (40, 40, 46) if dark else (255, 255, 255)
        canvas_col = (22, 22, 26) if dark else (250, 251, 253)
        fg_col = (240, 240, 245) if dark else (29, 29, 31)
        border_col = (70, 70, 80) if dark else (210, 214, 220)

        img = Image.new("RGB", (img_w, img_h), bg_col)
        d = ImageDraw.Draw(img)

        def srect(r: List[int]) -> Tuple[int, int, int, int]:
            return (r[0] * scale, r[1] * scale, (r[0] + r[2]) * scale, (r[1] + r[3]) * scale)

        # Üst çubuk, kenar çubuğu, tuval ve sağ panel
        d.rectangle((0, 0, img_w, 56 * scale), fill=panel_col, outline=border_col, width=2)
        d.rounded_rectangle(srect(sidebar_dip), radius=16, fill=panel_col, outline=border_col, width=3)
        d.rounded_rectangle(srect(canvas_dip), radius=16, fill=canvas_col, outline=border_col, width=3)
        d.rounded_rectangle(srect(panel_dip), radius=16, fill=panel_col, outline=border_col, width=3)

        # Tuval ızgarası
        cx0, cy0, cx1, cy1 = srect(canvas_dip)
        for gx in range(cx0 + 80, cx1, 80):
            d.line((gx, cy0, gx, cy1), fill=(45, 45, 52) if dark else (235, 238, 242), width=1)
        for gy in range(cy0 + 80, cy1, 80):
            d.line((cx0, gy, cx1, gy), fill=(45, 45, 52) if dark else (235, 238, 242), width=1)

        if extra_draw:
            extra_draw(d)

        # Hedef bölgeleri renklendirilmiş bloklar olarak çiz
        palette = [
            (0, 113, 227),
            (52, 199, 89),
            (255, 149, 0),
            (175, 82, 222),
            (255, 59, 48),
        ]
        for idx, (tkey, trect) in enumerate(targets.items()):
            if tkey in ("canvas", "panel", "sidebar"):
                continue
            col = palette[idx % len(palette)]
            bx0, by0, bx1, by1 = srect(trect)
            d.rounded_rectangle((bx0, by0, bx1, by1), radius=12, fill=col, outline=fg_col, width=3)
            d.text((bx0 + 14, by0 + 10), tkey, font=f_small, fill=COLOR_WHITE)

        # Ekran görüntüsü adını devre alanı içinde kesilmeyecek şekilde yaz
        d.text((cx0 + 210, cy0 + 200), name.upper(), font=f_huge, fill=fg_col)
        d.text((cx0 + 210, cy0 + 310), label, font=f_med, fill=COLOR_ACCENT)

        file_name = f"{name}.png"
        img.save(target_dir / file_name, format="PNG")
        shots_meta.append({
            "name": name,
            "file": file_name,
            "kind": "window",
            "label": label,
            "targets": targets,
        })

    base_targets = {
        "sidebar": sidebar_dip,
        "canvas": canvas_dip,
        "panel": panel_dip,
        "solveButton": solve_btn_dip,
        "themeButton": theme_btn_dip,
    }

    # 1. empty
    draw_window_shot("empty", "Boş devre tuvali", dict(base_targets))

    # 2. build_01..build_10 (ilk 5 eleman, son 5 tel)
    placed_boxes: List[List[int]] = []
    elem_positions = [
        [450, 260, 110, 70],
        [640, 220, 110, 70],
        [830, 260, 110, 70],
        [640, 420, 110, 70],
        [830, 420, 110, 70],
        [520, 290, 130, 30],
        [740, 250, 100, 30],
        [680, 290, 40, 130],
        [870, 290, 40, 130],
        [520, 450, 350, 35],
    ]
    for i in range(1, 11):
        bname = f"build_{i:02d}"
        lrect = elem_positions[i - 1]
        placed_boxes.append(lrect)
        t_dict = dict(base_targets)
        t_dict["lastAdded"] = lrect
        if i <= 5:
            t_dict["sidebarItem"] = [40, 110 + (i - 1) * 90, 190, 64]
            lbl = f"Eleman eklendi #{i}"
        else:
            lbl = f"Tel bağlandı #{i - 5}"

        def draw_prev(d: ImageDraw.ImageDraw, boxes: List[List[int]] = list(placed_boxes[:-1])) -> None:
            for r in boxes:
                d.rounded_rectangle(
                    (r[0] * scale, r[1] * scale, (r[0] + r[2]) * scale, (r[1] + r[3]) * scale),
                    radius=8,
                    fill=(180, 205, 235),
                    outline=(60, 90, 130),
                    width=3,
                )

        draw_window_shot(bname, lbl, t_dict, extra_draw=draw_prev)

    # 3. method_set & solved
    draw_window_shot("method_set", "Yöntem seçildi", dict(base_targets))
    solved_targets = dict(base_targets)
    solved_targets["lastAdded"] = [640, 320, 160, 90]
    draw_window_shot("solved", "Devre çözüldü (V1=12V, I1=2.4A)", solved_targets)

    # 4. explain_1..explain_4 & results_tab
    for i in range(1, 5):
        exp_t = dict(base_targets)
        exp_t["explanation"] = [1164, 120, 404, 680]
        draw_window_shot(f"explain_{i}", f"Adım {i}: Türkçe çözüm açıklaması", exp_t)

    res_t = dict(base_targets)
    res_t["explanation"] = [1164, 120, 404, 680]
    draw_window_shot("results_tab", "Sonuçlar sekmesi", res_t)

    # 5. practice_blank, practice_typed, practice_checked, practice_wrong
    prac_t = dict(base_targets)
    prac_t["answer1"] = [1180, 240, 360, 56]
    prac_t["answer2"] = [1180, 330, 360, 56]
    prac_t["checkButton"] = [1180, 420, 220, 54]
    prac_t["codeCard"] = [1170, 620, 390, 180]
    draw_window_shot("practice_blank", "Alıştırma modu (boş)", dict(prac_t))
    draw_window_shot("practice_typed", "Cevap yazıldı: 2.4 A", dict(prac_t))
    draw_window_shot("practice_checked", "Doğru cevap onaylandı", dict(prac_t))
    draw_window_shot("practice_wrong", "Yanlış cevap geri bildirimi", dict(prac_t))

    # 6. dark_solved
    draw_window_shot("dark_solved", "Koyu tema görünümü", dict(base_targets), dark=True)

    # 7. print_page (1587x2245 A4 sayfa)
    pw, ph = 1587, 2245
    page_img = Image.new("RGB", (pw, ph), COLOR_WHITE)
    pd = ImageDraw.Draw(page_img)
    pd.rectangle((80, 80, pw - 80, ph - 80), outline=COLOR_TEXT, width=4)
    pd.text((140, 140), "DEVRE ANALİZİ - ALIŞTIRMA YAPRAĞI", font=get_font("bold", 54), fill=COLOR_TEXT)
    pd.text((140, 230), "Soru Kodu: 4829   |   Ad Soyad: _______________________", font=f_med, fill=COLOR_TEXT_SEC)
    pd.rectangle((140, 340, pw - 140, 1240), outline=COLOR_BORDER, width=4)
    pd.text((480, 740), "[ Devre Şeması Alanı ]", font=f_huge, fill=COLOR_ACCENT)
    for idx in range(4):
        yy = 1340 + idx * 180
        pd.rounded_rectangle((140, yy, pw - 140, yy + 130), radius=12, outline=COLOR_BORDER, width=3)
        pd.text((170, yy + 40), f"Soru {idx + 1}: Düğüm gerilimini hesaplayınız: ____________ V", font=f_med, fill=COLOR_TEXT)
    page_img.save(target_dir / "print_page.png", format="PNG")
    shots_meta.append({
        "name": "print_page",
        "file": "print_page.png",
        "kind": "page",
        "label": "Yazdırılabilir A4 çalışma yaprağı",
        "page": {"width": pw, "height": ph},
    })

    # 8. ai_setup
    ai_t = dict(base_targets)
    ai_t["onboardingCard"] = [420, 170, 760, 560]
    draw_window_shot("ai_setup", "Yerel yapay zekâ kurulum kartı", ai_t)

    manifest_data = {
        "version": 1,
        "scale": scale,
        "window": {"width": win_w, "height": win_h},
        "shots": shots_meta,
    }
    with open(target_dir / "shots.json", "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Komut Satırı Arayüzü (CLI)
# ---------------------------------------------------------------------------
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Devre Analizi tanıtım videosu oluşturucu.")
    parser.add_argument("--shots", type=Path, default=Path("build/video/shots"), help="shots.json dizini")
    parser.add_argument("--out", type=Path, default=Path("build/video/devre-analizi-tanitim.mp4"), help="Çıktı MP4 yolu")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS, help="Kare hızı (varsayılan: 30)")
    parser.add_argument("--music", type=Path, default=None, help="Videoya eklenecek WAV ses dosyası (isteğe bağlı)")
    parser.add_argument("--preview", action="store_true", help="Yalnızca iletişim sayfasını ve posteri üret (hızlı)")
    parser.add_argument("--synthetic", type=Path, default=None, help="Sahte test görüntülerini belirtilen dizine üret ve çık")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if args.synthetic is not None:
        t0 = time.perf_counter()
        generate_synthetic_shots(args.synthetic)
        dt = time.perf_counter() - t0
        print(f"Sentetik test verisi oluşturuldu: {args.synthetic} ({dt:.2f}s)")
        return 0

    manifest = load_manifest(args.shots)
    timeline = build_timeline(manifest)
    renderer = VideoRenderer(manifest, timeline)

    t0 = time.perf_counter()
    if args.preview:
        contact_path = args.out.parent / "contact_sheet.png"
        poster_path = args.out.parent / "poster.png"
        write_contact_sheet_and_poster(renderer, contact_path, poster_path)
        dt = time.perf_counter() - t0
        total_frames = int(round(timeline.total_duration * args.fps))
        print(
            f"Önizleme tamamlandı: süre={timeline.total_duration:.2f}s, "
            f"kare={total_frames}, geçen_süre={dt:.2f}s"
        )
        return 0

    total_frames, size_bytes = encode_video(renderer, args.out, fps=args.fps, music_path=args.music)
    dt = time.perf_counter() - t0
    size_mb = size_bytes / (1024 * 1024)
    print(
        f"Video hazır: süre={timeline.total_duration:.2f}s, "
        f"kare={total_frames}, boyut={size_mb:.2f} MB ({size_bytes} bayt), "
        f"üretim_süresi={dt:.2f}s -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
