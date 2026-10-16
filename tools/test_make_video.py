# -*- coding: utf-8 -*-
"""
tools/make_video.py için birim testleri (pytest).
"""

from pathlib import Path
import json
import math
import pytest

from tools.make_video import (
    CARD_W,
    CARD_X,
    CARD_Y,
    MAX_ZOOM,
    Manifest,
    ShotInfo,
    VideoRenderer,
    build_timeline,
    dip_to_video_px,
    ease_in_out_cubic,
    ease_out_cubic,
    fit_view_rect,
    generate_synthetic_shots,
    load_manifest,
)


def test_easing_endpoints_and_monotonicity():
    """Yumuşatma (easing) fonksiyonlarının uç noktalarını ve monotonluğunu doğrular."""
    assert ease_in_out_cubic(0.0) == pytest.approx(0.0)
    assert ease_in_out_cubic(0.5) == pytest.approx(0.5)
    assert ease_in_out_cubic(1.0) == pytest.approx(1.0)
    assert ease_in_out_cubic(-0.5) == pytest.approx(0.0)
    assert ease_in_out_cubic(1.5) == pytest.approx(1.0)

    assert ease_out_cubic(0.0) == pytest.approx(0.0)
    assert ease_out_cubic(1.0) == pytest.approx(1.0)
    assert ease_out_cubic(-1.0) == pytest.approx(0.0)
    assert ease_out_cubic(2.0) == pytest.approx(1.0)

    # Monoton artış kontrolü
    prev_io = 0.0
    prev_o = 0.0
    for i in range(1, 21):
        t = i / 20.0
        cur_io = ease_in_out_cubic(t)
        cur_o = ease_out_cubic(t)
        assert cur_io >= prev_io
        assert cur_o >= prev_o
        prev_io, prev_o = cur_io, cur_o


def test_fit_view_rect_aspect_bounds_and_max_zoom():
    """Kamera görünüm dikdörtgeninin en-boy oranını, pencere sınırlarını ve maksimum yakınlaştırmayı koruduğunu doğrular."""
    win_w, win_h = 1600.0, 900.0
    aspect = win_w / win_h

    # Çok küçük hedef -> max_zoom (2.0) sınırına takılmalı (800x450)
    tiny_target = (750.0, 420.0, 20.0, 20.0)
    vx, vy, vw, vh = fit_view_rect(tiny_target, win_w, win_h, padding=10.0, max_zoom=MAX_ZOOM)
    assert vw == pytest.approx(win_w / MAX_ZOOM)
    assert vh == pytest.approx(win_h / MAX_ZOOM)
    assert (vw / vh) == pytest.approx(aspect)
    assert 0.0 <= vx <= win_w - vw
    assert 0.0 <= vy <= win_h - vh

    # Köşe dışı hedef -> pencere sınırları içinde kalmalı
    corner_target = (-50.0, 820.0, 300.0, 200.0)
    vx2, vy2, vw2, vh2 = fit_view_rect(corner_target, win_w, win_h, padding=40.0, max_zoom=MAX_ZOOM)
    assert (vw2 / vh2) == pytest.approx(aspect)
    assert vx2 >= 0.0
    assert vy2 >= 0.0
    assert vx2 + vw2 <= win_w + 1e-6
    assert vy2 + vh2 <= win_h + 1e-6
    assert vw2 >= win_w / MAX_ZOOM - 1e-6

    # Çok büyük hedef -> tam pencereyi aşmamalı
    huge_target = (0.0, 0.0, 2000.0, 1200.0)
    vx3, vy3, vw3, vh3 = fit_view_rect(huge_target, win_w, win_h, padding=80.0, max_zoom=MAX_ZOOM)
    assert (vx3, vy3, vw3, vh3) == pytest.approx((0.0, 0.0, win_w, win_h))


def test_dip_to_video_px_mapping():
    """DIP koordinatlarının kamera görünümü üzerinden video piksellerine doğru eşlendiğini doğrular."""
    win_w, win_h = 1600.0, 900.0
    card_h = int(round(CARD_W * win_h / win_w))  # 844
    card_rect = (CARD_X, CARD_Y, CARD_W, card_h)

    # Tam pencere görünümünde sol-üst, sağ-alt ve merkez
    full_view = (0.0, 0.0, win_w, win_h)
    assert dip_to_video_px((0.0, 0.0), full_view, card_rect) == pytest.approx((CARD_X, CARD_Y))
    assert dip_to_video_px((win_w, win_h), full_view, card_rect) == pytest.approx((CARD_X + CARD_W, CARD_Y + card_h))
    assert dip_to_video_px((win_w / 2, win_h / 2), full_view, card_rect) == pytest.approx(
        (CARD_X + CARD_W / 2.0, CARD_Y + card_h / 2.0)
    )

    # 2x yakınlaştırılmış görünümde sol-üst köşe kartın sol-üst köşesine denk gelmeli
    zoomed_view = (400.0, 225.0, 800.0, 450.0)
    assert dip_to_video_px((400.0, 225.0), zoomed_view, card_rect) == pytest.approx((CARD_X, CARD_Y))
    assert dip_to_video_px((800.0, 450.0), zoomed_view, card_rect) == pytest.approx(
        (CARD_X + CARD_W / 2.0, CARD_Y + card_h / 2.0)
    )


def test_synthetic_timeline_total_duration(tmp_path: Path):
    """Sentetik manifest için toplam sürenin 32–40 saniye aralığında olduğunu doğrular."""
    generate_synthetic_shots(tmp_path)
    manifest = load_manifest(tmp_path)
    timeline = build_timeline(manifest)
    assert 32.0 <= timeline.total_duration <= 40.0


def test_graceful_degradation_missing_shots_and_targets(tmp_path: Path):
    """Eksik ekran görüntüleri ve eksik hedefler içeren manifest'in hata vermeden çalıştığını doğrular."""
    # Yalnızca tek bir görüntüsü olan ve hiçbir hedefi (targets) bulunmayan minimal manifest
    partial_manifest_data = {
        "version": 1,
        "scale": 2,
        "window": {"width": 1600, "height": 900},
        "shots": [
            {"name": "empty", "file": "empty.png", "kind": "window", "targets": {}},
            {"name": "solved", "file": "missing_solved.png", "kind": "window"},
        ],
    }
    json_path = tmp_path / "shots.json"
    json_path.write_text(json.dumps(partial_manifest_data), encoding="utf-8")

    manifest = load_manifest(tmp_path)
    timeline = build_timeline(manifest)
    assert timeline.total_duration > 0.0
    assert len(timeline.beats) == 2

    renderer = VideoRenderer(manifest, timeline)
    # Başlangıç, orta ve çıkış karelerinin çökmeden üretildiğini doğrula
    f0 = renderer.render_frame(0.5)
    f1 = renderer.render_frame(timeline.intro_duration + 0.2)
    f2 = renderer.render_frame(timeline.total_duration - 0.5)
    assert f0.size == (1920, 1080)
    assert f1.size == (1920, 1080)
    assert f2.size == (1920, 1080)
