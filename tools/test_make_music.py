# -*- coding: utf-8 -*-
"""
tools/make_music.py için birim testleri (pytest).
"""

from pathlib import Path
import math
import wave
import numpy as np
import pytest

from tools.make_music import (
    SAMPLE_RATE,
    STYLE_SPECS,
    generate_music,
    is_freq_in_scale,
    midi_to_freq,
    note_to_midi,
    write_report_png,
    write_wav,
)


@pytest.mark.parametrize("style", ["A", "B", "C"])
def test_short_render_properties_and_harmony(style: str, tmp_path: Path):
    """
    Her stil (A, B, C) için kısa süreli (8.0s, groove=1.0s, outro=6.0s) üretimin:
    - Örnek sayısını ve 2 kanallı (stereo) yapısını,
    - NaN/Inf içermediğini,
    - Tepe değerinin <= -1 dBFS olduğunu,
    - Sessiz olmadığını (RMS > -40 dBFS),
    - Son 50 ms'nin sessizliğe çok yakın olduğunu,
    - Deterministik olduğunu (iki üretimin birebir aynı olduğunu),
    - Seçilen BPM'in stilin aralığında olduğunu,
    - Üretilen her nota frekansının beyan edilen diziye (C Majör) ait olduğunu doğrular.
    """
    duration = 8.0
    groove_start = 1.0
    outro_start = 6.0

    res1 = generate_music(
        style=style,
        duration=duration,
        groove_start=groove_start,
        outro_start=outro_start,
    )
    res2 = generate_music(
        style=style,
        duration=duration,
        groove_start=groove_start,
        outro_start=outro_start,
    )

    expected_samples = int(round(duration * SAMPLE_RATE))
    assert res1.audio.shape == (expected_samples, 2)
    assert res1.pcm16.shape == (expected_samples, 2)
    assert res1.pcm16.dtype == np.int16

    # NaN veya sonsuz değer bulunmamalı
    assert not np.isnan(res1.audio).any()
    assert not np.isinf(res1.audio).any()

    # Deterministik çıktı kontrolü
    assert np.array_equal(res1.pcm16, res2.pcm16)
    assert np.allclose(res1.audio, res2.audio)

    # Peak <= -1.0 dBFS ve RMS > -40.0 dBFS
    max_lin = float(np.max(np.abs(res1.audio)))
    peak_db = 20.0 * math.log10(max(1e-12, max_lin))
    rms_lin = float(np.sqrt(np.mean(res1.audio ** 2)))
    rms_db = 20.0 * math.log10(max(1e-12, rms_lin))

    assert peak_db <= -1.0 + 1e-6
    assert res1.peak_dbfs <= -1.0 + 1e-6
    assert rms_db > -40.0
    assert res1.rms_dbfs > -40.0

    # Son 50 ms neredeyse tamamen sessiz olmalı
    last_50ms_samples = int(round(0.050 * SAMPLE_RATE))
    tail_audio = res1.audio[-last_50ms_samples:, :]
    tail_peak = float(np.max(np.abs(tail_audio)))
    assert tail_peak < 1e-4

    # Seçilen BPM stilin izin verilen aralığında olmalı
    spec = STYLE_SPECS[style]
    lo_bpm, hi_bpm = spec.bpm_range
    assert lo_bpm <= res1.bpm <= hi_bpm

    # Üretilen her notanın frekansı beyan edilen dizinin (C Majör) içinde olmalı
    assert len(res1.notes) > 0
    for ev in res1.notes:
        assert is_freq_in_scale(ev.freq_hz, res1.scale_semitones)
        expected_midi = note_to_midi(ev.note_name)
        assert ev.midi == expected_midi
        assert ev.freq_hz == pytest.approx(midi_to_freq(expected_midi), rel=1e-6)
        assert (ev.midi % 12) in res1.scale_semitones

    # WAV ve PNG rapor dosyası yazma kontrolü
    wav_path = tmp_path / f"test_{style}.wav"
    png_path = tmp_path / f"test_{style}.png"
    write_wav(wav_path, res1)
    write_report_png(png_path, res1)

    assert wav_path.exists()
    assert png_path.exists() and png_path.stat().st_size > 1000

    with wave.open(str(wav_path), "rb") as wf:
        assert wf.getnchannels() == 2
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == SAMPLE_RATE
        assert wf.getnframes() == expected_samples
