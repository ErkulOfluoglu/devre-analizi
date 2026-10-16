#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Devre Analizi tanıtım videosu için telifsiz, %100 saf sentez (pure synthesis)
arka plan müziği üreteci.

Yalnızca Python standart kütüphanesi (wave, struct, math, argparse) ve NumPy
kullanarak 48 kHz, 16-bit stereo WAV üretir; isteğe bağlı olarak Pillow ile
dalga formu + log-frekans spektrogram raporu (PNG) oluşturur.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Temel Ses ve Müzik Sabitleri
# ---------------------------------------------------------------------------
SAMPLE_RATE = 48000
A4_HZ = 440.0
DEFAULT_DURATION = 34.63
DEFAULT_GROOVE_START = 2.6
DEFAULT_OUTRO_START = 29.13

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
NAME_TO_SEMITONE: Dict[str, int] = {
    "C": 0, "B#": 0,
    "C#": 1, "DB": 1,
    "D": 2,
    "D#": 3, "EB": 3,
    "E": 4, "FB": 4,
    "F": 5, "E#": 5,
    "F#": 6, "GB": 6,
    "G": 7,
    "G#": 8, "AB": 8,
    "A": 9,
    "A#": 10, "BB": 10,
    "B": 11, "CB": 11,
}

# C Majör dizisi yarı ton sınıfları (C=0, D=2, E=4, F=5, G=7, A=9, B=11)
C_MAJOR_SEMITONES: Tuple[int, ...] = (0, 2, 4, 5, 7, 9, 11)
C_MAJOR_NOTE_NAMES: Tuple[str, ...] = ("C", "D", "E", "F", "G", "A", "B")
C_PENTATONIC_SEMITONES: Tuple[int, ...] = (0, 2, 4, 7, 9)

FONT_PATHS = {
    "regular": "C:/Windows/Fonts/segoeui.ttf",
    "semibold": "C:/Windows/Fonts/seguisb.ttf",
    "bold": "C:/Windows/Fonts/segoeuib.ttf",
    "mono": "C:/Windows/Fonts/consola.ttf",
}


@dataclass(frozen=True)
class StyleSpec:
    """Her müzik stilinin (A, B, C) müzikal ve akustik parametrelerini tanımlar."""
    code: str
    name: str
    bpm_range: Tuple[float, float]
    key: str
    scale_semitones: Tuple[int, ...]
    chord_names: Tuple[str, ...]
    chord_roots: Tuple[str, ...]
    chord_voicings: Tuple[Tuple[str, ...], ...]
    tonic_chord_name: str
    tonic_root: str
    tonic_voicing: Tuple[str, ...]
    reverb_rt60: float
    reverb_wet: float
    seed: int


STYLE_SPECS: Dict[str, StyleSpec] = {
    "A": StyleSpec(
        code="A",
        name="Sakin ve modern",
        bpm_range=(88.0, 96.0),
        key="C Major",
        scale_semitones=C_MAJOR_SEMITONES,
        chord_names=("Fmaj7", "G6", "Em7", "Am7"),
        chord_roots=("F2", "G2", "E2", "A2"),
        chord_voicings=(
            ("F3", "A3", "C4", "E4"),
            ("G3", "B3", "D4", "E4"),
            ("E3", "G3", "B3", "D4"),
            ("A3", "C4", "E4", "G4"),
        ),
        tonic_chord_name="Cmaj9",
        tonic_root="C2",
        tonic_voicing=("C3", "E3", "G3", "B3", "D4"),
        reverb_rt60=1.85,
        reverb_wet=0.20,
        seed=202601,
    ),
    "B": StyleSpec(
        code="B",
        name="Enerjik",
        bpm_range=(108.0, 118.0),
        key="C Major",
        scale_semitones=C_MAJOR_SEMITONES,
        chord_names=("C", "G", "Am", "F"),
        chord_roots=("C2", "G2", "A2", "F2"),
        chord_voicings=(
            ("C3", "E3", "G3", "C4"),
            ("G3", "B3", "D4", "G4"),
            ("A3", "C4", "E4", "A4"),
            ("F3", "A3", "C4", "F4"),
        ),
        tonic_chord_name="Cmaj9",
        tonic_root="C2",
        tonic_voicing=("C3", "E3", "G3", "B3", "D4"),
        reverb_rt60=1.65,
        reverb_wet=0.17,
        seed=202602,
    ),
    "C": StyleSpec(
        code="C",
        name="Minimal",
        bpm_range=(70.0, 80.0),
        key="C Major",
        scale_semitones=C_MAJOR_SEMITONES,
        chord_names=("Cmaj7", "Fmaj7", "Am7", "G6"),
        chord_roots=("C2", "F2", "A2", "G2"),
        chord_voicings=(
            ("C3", "E3", "G3", "B3"),
            ("F3", "A3", "C4", "E4"),
            ("A3", "C4", "E4", "G4"),
            ("G3", "B3", "D4", "E4"),
        ),
        tonic_chord_name="Cmaj9",
        tonic_root="C2",
        tonic_voicing=("C3", "E3", "G3", "B3", "D4"),
        reverb_rt60=2.80,
        reverb_wet=0.25,
        seed=202603,
    ),
}


@dataclass(frozen=True)
class NoteEvent:
    """Üretilen tek bir enstrüman notasının zaman, perde ve seviye bilgisi."""
    time: float
    duration: float
    instrument: str
    note_name: str
    midi: int
    freq_hz: float
    velocity: float
    pan: float = 0.0


@dataclass
class MusicResult:
    """Müzik üretim çıktısını, analiz metriklerini ve nota listesini tutar."""
    audio: np.ndarray          # (N, 2) float64, [-1, 1] aralığında normalize edilmiş
    pcm16: np.ndarray          # (N, 2) int16
    sample_rate: int
    style: str
    style_name: str
    bpm: float
    bpm_range: Tuple[float, float]
    key: str
    scale_semitones: Tuple[int, ...]
    chord_loop: Tuple[str, ...]
    bars: float
    duration: float
    groove_start: float
    outro_start: float
    peak_dbfs: float
    rms_dbfs: float
    notes: List[NoteEvent] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Nota, Frekans ve Tempo Yardımcıları
# ---------------------------------------------------------------------------
def note_to_midi(note: str) -> int:
    """'C4', 'F#3' gibi nota adını MIDI nota numarasına (C4=60, A4=69) çevirir."""
    s = note.strip().upper()
    if len(s) < 2:
        raise ValueError(f"Geçersiz nota adı: {note}")
    if s[1] in ("#", "B") and len(s) >= 3:
        pitch = s[:2]
        octave = int(s[2:])
    else:
        pitch = s[:1]
        octave = int(s[1:])
    semitone = NAME_TO_SEMITONE[pitch]
    return (octave + 1) * 12 + semitone


def midi_to_note(midi: int) -> str:
    """MIDI nota numarasını 'C4' biçiminde nota adına çevirir."""
    octave = (midi // 12) - 1
    name = NOTE_NAMES[midi % 12]
    return f"{name}{octave}"


def midi_to_freq(midi: int | float) -> float:
    """Eşit tampere sistemde (A4 = 440 Hz) MIDI notasını frekansa (Hz) dönüştürür."""
    return float(A4_HZ * (2.0 ** ((float(midi) - 69.0) / 12.0)))


def freq_to_midi(freq_hz: float) -> int:
    """Frekansı (Hz) en yakın MIDI nota numarasına yuvarlar."""
    return int(round(69.0 + 12.0 * math.log2(max(1e-9, freq_hz) / A4_HZ)))


def is_freq_in_scale(freq_hz: float, scale_semitones: Sequence[int] = C_MAJOR_SEMITONES, tol_cents: float = 5.0) -> bool:
    """Verilen frekansın eşit tampere bir notaya ve belirtilen diziye ait olup olmadığını denetler."""
    if freq_hz <= 0.0:
        return False
    exact_midi = 69.0 + 12.0 * math.log2(freq_hz / A4_HZ)
    nearest_midi = int(round(exact_midi))
    cents_err = abs(exact_midi - nearest_midi) * 100.0
    if cents_err > tol_cents:
        return False
    return (nearest_midi % 12) in set(scale_semitones)


def choose_bpm(style: str, groove_start: float, outro_start: float) -> Tuple[float, float]:
    """
    groove_start ile outro_start arasına tam sayıda ölçü (4/4) sığacak şekilde
    stilin BPM aralığı içinde en uygun tempoyu seçer.
    Döndürür: (bpm, bar_sayisi).
    """
    spec = STYLE_SPECS[style.upper()]
    lo, hi = spec.bpm_range
    mid = 0.5 * (lo + hi)
    groove_dur = max(0.5, outro_start - groove_start)

    # 1. Tam bar sayısı N için bpm = 240 * N / groove_dur aralığa düşüyor mu?
    valid_bars: List[Tuple[int, float]] = []
    for n_bars in range(1, 64):
        bpm = 240.0 * n_bars / groove_dur
        if lo <= bpm <= hi:
            valid_bars.append((n_bars, bpm))

    if valid_bars:
        # 4'ün katı olan bar sayılarını (tam 4-bar döngüsü) öncelikle tercih et
        mult4 = [item for item in valid_bars if item[0] % 4 == 0]
        pool = mult4 if mult4 else valid_bars
        best_n, best_bpm = min(pool, key=lambda x: abs(x[1] - mid))
        return best_bpm, float(best_n)

    # 2. Çok kısa test sürelerinde tam vuruş (beat) sayısı B için dene
    valid_beats: List[Tuple[int, float]] = []
    for n_beats in range(1, 256):
        bpm = 60.0 * n_beats / groove_dur
        if lo <= bpm <= hi:
            valid_beats.append((n_beats, bpm))

    if valid_beats:
        best_b, best_bpm = min(valid_beats, key=lambda x: abs(x[1] - mid))
        return best_bpm, best_b / 4.0

    # 3. Yedek: stilin orta temposu
    bars = groove_dur * mid / 240.0
    return mid, bars


# ---------------------------------------------------------------------------
# Vektörel DSP, Filtre, Panlama ve Zarf (Envelope) Fonksiyonları
# ---------------------------------------------------------------------------
def equal_power_pan(pan: float) -> Tuple[float, float]:
    """[-1.0, +1.0] aralığındaki pan değerini eşit güçlü (L, R) kazançlarına dönüştürür."""
    p = max(-1.0, min(1.0, float(pan)))
    angle = (p + 1.0) * (math.pi * 0.25)
    return math.cos(angle), math.sin(angle)


def mix_mono_into_stereo(
    stereo_buf: np.ndarray,
    mono_sig: np.ndarray,
    start_time: float,
    pan: float = 0.0,
    sr: int = SAMPLE_RATE,
) -> None:
    """Mono sinyali eşit güçlü panlama ile stereo tamponun ilgili zaman aralığına ekler."""
    if mono_sig.size == 0:
        return
    start_idx = int(round(start_time * sr))
    total_len = stereo_buf.shape[0]
    if start_idx >= total_len:
        return
    if start_idx < 0:
        mono_sig = mono_sig[-start_idx:]
        start_idx = 0
    end_idx = min(total_len, start_idx + mono_sig.shape[0])
    seg_len = end_idx - start_idx
    if seg_len <= 0:
        return

    g_l, g_r = equal_power_pan(pan)
    seg = mono_sig[:seg_len]
    stereo_buf[start_idx:end_idx, 0] += seg * g_l
    stereo_buf[start_idx:end_idx, 1] += seg * g_r


def adsr_envelope(
    num_samples: int,
    sr: int,
    attack: float,
    decay: float,
    sustain: float,
    release: float,
) -> np.ndarray:
    """Tıklamasız (click-free), yumuşak geçişli vektörel ADSR zarfı üretir."""
    if num_samples <= 0:
        return np.zeros(0, dtype=np.float64)

    n_att = max(1, int(round(attack * sr)))
    n_dec = max(1, int(round(decay * sr)))
    n_rel = max(1, int(round(release * sr)))

    # Toplam süre kısa ise bölümleri orantılı ölçekle
    if n_att + n_dec + n_rel > num_samples:
        scale = num_samples / float(n_att + n_dec + n_rel)
        n_att = max(1, int(n_att * scale))
        n_dec = max(1, int(n_dec * scale))
        n_rel = max(1, num_samples - n_att - n_dec)

    n_sus = max(0, num_samples - n_att - n_dec - n_rel)

    # Yarım kosinüs tabanlı yumuşak yükseliş, üstel düşüş ve yumuşak sönümleme
    att_curve = 0.5 * (1.0 - np.cos(np.linspace(0.0, math.pi, n_att, endpoint=False)))
    dec_curve = sustain + (1.0 - sustain) * np.exp(-np.linspace(0.0, 4.5, n_dec, endpoint=False))
    sus_curve = np.full(n_sus, sustain, dtype=np.float64)
    rel_curve = sustain * 0.5 * (1.0 + np.cos(np.linspace(0.0, math.pi, n_rel, endpoint=True)))

    return np.concatenate([att_curve, dec_curve, sus_curve, rel_curve])


def fft_filter_1d(
    sig: np.ndarray,
    sr: int = SAMPLE_RATE,
    lowpass_hz: Optional[float] = None,
    highpass_hz: Optional[float] = None,
    order: int = 2,
) -> np.ndarray:
    """FFT tabanlı yumuşak Butterworth-benzeri alçak/yüksek geçiren filtre (1B veya 2B stereo)."""
    n = sig.shape[0]
    if n == 0:
        return sig
    freqs = np.fft.rfftfreq(n, d=1.0 / sr)
    mask = np.ones_like(freqs, dtype=np.float64)
    if lowpass_hz is not None and lowpass_hz > 0.0:
        mask /= np.sqrt(1.0 + (freqs / float(lowpass_hz)) ** (2 * order))
    if highpass_hz is not None and highpass_hz > 0.0:
        safe_f = np.maximum(freqs, 1e-6)
        mask /= np.sqrt(1.0 + (float(highpass_hz) / safe_f) ** (2 * order))
        mask[0] = 0.0

    spec = np.fft.rfft(sig, axis=0)
    if sig.ndim == 2:
        spec *= mask[:, None]
    else:
        spec *= mask
    return np.fft.irfft(spec, n=n, axis=0)


# ---------------------------------------------------------------------------
# Enstrüman Sentezleyicileri (Shared Synthesis Engine)
# ---------------------------------------------------------------------------
def synth_pad_voice(
    freq_hz: float,
    duration: float,
    sr: int,
    rng: np.random.Generator,
    attack: float = 0.35,
    release: float = 0.65,
    cutoff_hz: float = 1400.0,
    detune_cents: Tuple[float, float, float] = (-7.0, 0.0, 7.0),
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Bant sınırlı (band-limited) toplamsal testere dişi (additive saw) pad sesi:
    3 detune ses (±7 cent), ADSR zarfı ve harmonik alçak geçiren yuvarlama.
    Sol ve sağ kanal dizilerini döndürür.
    """
    n = max(1, int(round(duration * sr)))
    t = np.arange(n, dtype=np.float64) / sr

    left = np.zeros(n, dtype=np.float64)
    right = np.zeros(n, dtype=np.float64)
    voice_pans = (-0.35, 0.0, 0.35)

    max_harm = min(14, int(min(sr * 0.45, 4500.0) // max(20.0, freq_hz)))
    harmonics = np.arange(1, max(2, max_harm + 1), dtype=np.float64)

    for c_cents, v_pan in zip(detune_cents, voice_pans):
        f_v = freq_hz * (2.0 ** (c_cents / 1200.0))
        h_freqs = harmonics * f_v
        # Testere dişi harmonik genlikleri + doğal alçak geçiren filtre tepkisi
        lp_roll = 1.0 / (1.0 + (h_freqs / cutoff_hz) ** 2.6)
        h_amps = ((-1.0) ** (harmonics + 1.0)) * (1.0 / harmonics) * lp_roll
        phases = rng.uniform(0.0, 2.0 * math.pi, size=harmonics.shape[0])

        phases_matrix = 2.0 * math.pi * np.outer(t, h_freqs) + phases[None, :]
        voice_sig = np.sin(phases_matrix) @ h_amps

        g_l, g_r = equal_power_pan(v_pan)
        left += voice_sig * g_l
        right += voice_sig * g_r

    env = adsr_envelope(n, sr, attack=attack, decay=0.45, sustain=0.72, release=release)
    scale = 0.14
    return left * env * scale, right * env * scale


def synth_fm_epiano(
    freq_hz: float,
    duration: float,
    sr: int = SAMPLE_RATE,
    velocity: float = 0.8,
) -> np.ndarray:
    """
    2-operatörlü FM elektrik piyano (Rhodes/DX tarzı):
    Azalan modülasyon indeksi, sıcak gövde + berrak tine vurgu harmonikleri.
    """
    n = max(1, int(round(duration * sr)))
    t = np.arange(n, dtype=np.float64) / sr

    mod_idx1 = (1.35 * velocity) * np.exp(-t / 0.20)
    mod_idx2 = (0.30 * velocity) * np.exp(-t / 0.055)

    mod1 = mod_idx1 * np.sin(2.0 * math.pi * (1.0 * freq_hz) * t)
    mod2 = mod_idx2 * np.sin(2.0 * math.pi * (4.0 * freq_hz) * t)
    carrier = np.sin(2.0 * math.pi * freq_hz * t + mod1 + mod2)
    warm_sub = 0.35 * np.sin(2.0 * math.pi * freq_hz * t)

    att = 0.006
    rel = min(0.18, duration * 0.35)
    env = adsr_envelope(n, sr, attack=att, decay=0.28, sustain=0.32, release=rel)
    decay_curve = np.exp(-t / 0.85)

    sig = (carrier + warm_sub) * env * decay_curve
    return sig * (0.28 * velocity)


def synth_fm_bell(
    freq_hz: float,
    duration: float,
    sr: int = SAMPLE_RATE,
    velocity: float = 0.75,
) -> np.ndarray:
    """
    2-operatörlü FM çan / celesta:
    1:2 harmonik oranlı berrak, sıcak ve yumuşak uzayan çan tınısı.
    """
    n = max(1, int(round(duration * sr)))
    t = np.arange(n, dtype=np.float64) / sr

    mod_idx = (1.20 * velocity) * np.exp(-t / 0.16)
    mod = mod_idx * np.sin(2.0 * math.pi * (2.0 * freq_hz) * t)
    carrier = np.sin(2.0 * math.pi * freq_hz * t + mod)
    overtone = 0.20 * np.exp(-t / 0.12) * np.sin(2.0 * math.pi * (3.0 * freq_hz) * t)

    att = 0.005
    rel = min(0.25, duration * 0.4)
    env = adsr_envelope(n, sr, attack=att, decay=0.32, sustain=0.28, release=rel)
    exp_tail = np.exp(-t / 0.70)

    sig = (carrier + overtone) * env * exp_tail
    return sig * (0.26 * velocity)


def synth_pluck(
    freq_hz: float,
    duration: float,
    sr: int = SAMPLE_RATE,
    velocity: float = 0.8,
) -> np.ndarray:
    """
    Vektörel Karplus-Strong / FM hibrit pluck sentezi:
    Üst harmonikleri daha hızlı sönümlenen tel modeli + parlak FM mızrap atağı.
    """
    n = max(1, int(round(duration * sr)))
    t = np.arange(n, dtype=np.float64) / sr

    sig = np.zeros(n, dtype=np.float64)
    for k in range(1, 8):
        fk = k * freq_hz
        if fk >= min(sr * 0.42, 4800.0):
            break
        tau_k = 0.22 / (1.0 + 0.60 * (k - 1))
        amp_k = (1.0 / (k ** 1.15)) * np.exp(-t / tau_k)
        sig += amp_k * np.sin(2.0 * math.pi * fk * t)

    fm_transient = 0.48 * np.exp(-t / 0.030) * np.sin(
        2.0 * math.pi * freq_hz * t + 1.5 * np.exp(-t / 0.022) * np.sin(2.0 * math.pi * 2.0 * freq_hz * t)
    )
    sig = sig + fm_transient

    env = adsr_envelope(
        n, sr,
        attack=0.004,
        decay=min(0.10, duration * 0.45),
        sustain=0.16,
        release=min(0.05, duration * 0.25),
    )
    return sig * env * (0.26 * velocity)


def synth_sub_bass(
    freq_hz: float,
    duration: float,
    sr: int = SAMPLE_RATE,
    velocity: float = 0.85,
    attack: float = 0.015,
    release: float = 0.055,
) -> np.ndarray:
    """Temiz sinüs sub-bass + küçük hoparlörlerde duyulabilirlik için hafif 2. harmonik."""
    n = max(1, int(round(duration * sr)))
    t = np.arange(n, dtype=np.float64) / sr

    fundamental = np.sin(2.0 * math.pi * freq_hz * t)
    second_harm = 0.16 * np.sin(2.0 * math.pi * (2.0 * freq_hz) * t)
    env = adsr_envelope(n, sr, attack=attack, decay=0.18, sustain=0.68, release=release)

    sig = (fundamental + second_harm) * env
    return sig * (0.28 * velocity)


def synth_kick(sr: int = SAMPLE_RATE, velocity: float = 0.85) -> np.ndarray:
    """Yumuşak kick davul: 120 Hz -> 45 Hz frekans süpürmesi (250 ms)."""
    dur = 0.250
    n = int(round(dur * sr))
    t = np.arange(n, dtype=np.float64) / sr

    f_t = 45.0 + (120.0 - 45.0) * np.exp(-t / 0.030)
    phase = 2.0 * math.pi * np.cumsum(f_t) / sr
    body = np.sin(phase)

    att_n = max(1, int(round(0.0025 * sr)))
    att = np.linspace(0.0, 1.0, att_n)
    env = np.exp(-t / 0.085)
    env[:att_n] *= att
    tail_n = max(1, int(round(0.040 * sr)))
    env[-tail_n:] *= 0.5 * (1.0 + np.cos(np.linspace(0.0, math.pi, tail_n)))

    sig = np.tanh(1.35 * body * env)
    sig = fft_filter_1d(sig, sr=sr, lowpass_hz=240.0)
    return sig * (0.48 * velocity)


def synth_hat(sr: int = SAMPLE_RATE, rng: Optional[np.random.Generator] = None, velocity: float = 0.5) -> np.ndarray:
    """Kapalı hi-hat: yüksek geçiren filtreli (high-passed) gürültü (50 ms)."""
    if rng is None:
        rng = np.random.default_rng(42)
    dur = 0.050
    n = int(round(dur * sr))
    t = np.arange(n, dtype=np.float64) / sr

    noise = rng.standard_normal(n)
    filtered = fft_filter_1d(noise, sr=sr, lowpass_hz=13500.0, highpass_hz=7200.0, order=3)

    att_n = max(1, int(round(0.0015 * sr)))
    env = np.exp(-t / 0.011)
    env[:att_n] *= np.linspace(0.0, 1.0, att_n)
    env[-int(0.010 * sr):] *= np.linspace(1.0, 0.0, int(0.010 * sr))

    return filtered * env * (0.14 * velocity)


def synth_snap_or_clap(
    sr: int = SAMPLE_RATE,
    rng: Optional[np.random.Generator] = None,
    kind: str = "snap",
    velocity: float = 0.65,
) -> np.ndarray:
    """Filtrelenmiş çoklu gürültü patlamalarından oluşan yumuşak snap/rim (Stil A) veya clap (Stil B)."""
    if rng is None:
        rng = np.random.default_rng(99)
    dur = 0.095 if kind == "snap" else 0.135
    n = int(round(dur * sr))
    t = np.arange(n, dtype=np.float64) / sr

    noise = rng.standard_normal(n)
    if kind == "snap":
        bp = fft_filter_1d(noise, sr=sr, lowpass_hz=2800.0, highpass_hz=950.0, order=2)
        env = 0.6 * np.exp(-t / 0.006) + 0.4 * np.exp(-np.maximum(0.0, t - 0.008) / 0.018)
        env[t < 0.008] = 0.6 * np.exp(-t[t < 0.008] / 0.006)
    else:
        bp = fft_filter_1d(noise, sr=sr, lowpass_hz=3200.0, highpass_hz=850.0, order=2)
        env = np.zeros(n, dtype=np.float64)
        for delay_s, amp in ((0.0, 0.55), (0.009, 0.70), (0.018, 1.0)):
            dt = t - delay_s
            mask = dt >= 0.0
            tau = 0.007 if delay_s < 0.015 else 0.032
            env[mask] += amp * np.exp(-dt[mask] / tau)

    att_n = max(1, int(round(0.0015 * sr)))
    env[:att_n] *= np.linspace(0.0, 1.0, att_n)
    tail_n = max(1, int(round(0.020 * sr)))
    env[-tail_n:] *= np.linspace(1.0, 0.0, tail_n)

    return bp * env * (0.20 * velocity)


def synth_riser(duration: float, sr: int, rng: np.random.Generator) -> np.ndarray:
    """
    Outro öncesi 1 ölçülük filtrelenmiş gürültü yükselişi (riser/fill).
    STFT overlap-add ile kesim frekansı 350 Hz'den 2800 Hz'e pürüzsüzce yükselir.
    """
    n = max(1, int(round(duration * sr)))
    if n < 512:
        return np.zeros((n, 2), dtype=np.float64)

    win_size = 1024
    hop = 256
    win = np.hanning(win_size)
    freqs = np.fft.rfftfreq(win_size, d=1.0 / sr)

    out = np.zeros((n + win_size, 2), dtype=np.float64)
    n_frames = max(1, (n - win_size) // hop + 1)

    for ch in range(2):
        raw = rng.standard_normal(n + win_size)
        for idx in range(n_frames):
            pos = idx * hop
            u = idx / max(1.0, float(n_frames - 1))
            f_center = 350.0 * ((2800.0 / 350.0) ** u)
            bw = f_center * 0.45
            bp_mask = np.exp(-0.5 * ((freqs - f_center) / bw) ** 2)
            frame = raw[pos:pos + win_size] * win
            spec = np.fft.rfft(frame) * bp_mask
            out[pos:pos + win_size, ch] += np.fft.irfft(spec, n=win_size) * win

    out = out[:n]
    u_t = np.linspace(0.0, 1.0, n)
    swell_env = (u_t ** 2.2)
    fade_end = max(1, int(round(0.035 * sr)))
    swell_env[-fade_end:] *= np.linspace(1.0, 0.0, fade_end)

    max_val = np.max(np.abs(out))
    if max_val > 1e-9:
        out = out / max_val
    return out * swell_env[:, None] * 0.085


# ---------------------------------------------------------------------------
# Sentetik Stereo Reverb (FFT Konvolüsyonu)
# ---------------------------------------------------------------------------
def build_synthetic_stereo_ir(rt60: float, sr: int, rng: np.random.Generator) -> np.ndarray:
    """
    Üstel sönümlenen, yüksek frekansları zamanla yumuşayan sentetik stereo
    dürtü yanıtı (Impulse Response) üretir.
    """
    ir_dur = min(3.4, max(1.2, rt60 * 1.1))
    n = int(round(ir_dur * sr))
    t = np.arange(n, dtype=np.float64) / sr

    decay_slow = np.exp(-6.907755 * t / max(0.2, rt60))
    decay_fast = np.exp(-6.907755 * t / max(0.1, rt60 * 0.45))

    ir = np.zeros((n, 2), dtype=np.float64)
    for ch in range(2):
        noise = rng.standard_normal(n)
        low_mid = fft_filter_1d(noise, sr=sr, lowpass_hz=1600.0, highpass_hz=160.0, order=2)
        highs = fft_filter_1d(noise, sr=sr, lowpass_hz=4800.0, highpass_hz=1600.0, order=2)
        tail = low_mid * decay_slow + highs * 0.45 * decay_fast

        early = np.zeros(n, dtype=np.float64)
        taps_ms = (11.0, 19.0, 29.0, 43.0, 59.0) if ch == 0 else (13.0, 23.0, 34.0, 47.0, 64.0)
        for tap_i, ms in enumerate(taps_ms):
            idx = int(round(ms * 0.001 * sr))
            if idx < n:
                early[idx] = (0.55 ** (tap_i + 1)) * (1.0 if tap_i % 2 == 0 else -1.0)
        early = fft_filter_1d(early, sr=sr, lowpass_hz=3500.0, highpass_hz=180.0)

        pre_n = max(1, int(round(0.012 * sr)))
        tail[:pre_n] *= np.linspace(0.0, 1.0, pre_n)
        ir[:, ch] = tail + early * 0.35

    fade_n = max(1, int(round(0.08 * sr)))
    ir[-fade_n:, :] *= np.linspace(1.0, 0.0, fade_n)[:, None]
    energy = float(np.sqrt(np.mean(np.sum(ir ** 2, axis=0))))
    if energy > 1e-12:
        ir /= (energy * 1.45)
    return ir


def fft_convolve_stereo(signal: np.ndarray, ir: np.ndarray) -> np.ndarray:
    """Stereo sinyali stereo IR ile FFT üzerinden hızlıca konvolüsyona sokar."""
    n_sig = signal.shape[0]
    n_ir = ir.shape[0]
    n_fft = 1 << int(math.ceil(math.log2(max(2, n_sig + n_ir - 1))))

    sig_spec = np.fft.rfft(signal, n=n_fft, axis=0)
    ir_spec = np.fft.rfft(ir, n=n_fft, axis=0)
    conv = np.fft.irfft(sig_spec * ir_spec, n=n_fft, axis=0)
    return conv[:n_sig]


def build_sidechain_envelope(
    num_samples: int,
    kick_times: Sequence[float],
    sr: int = SAMPLE_RATE,
    depth: float = 0.38,
) -> np.ndarray:
    """Kick vuruşlarında pad kanalını nazikçe kısan (sidechain ducking) zarfı üretir."""
    env = np.ones(num_samples, dtype=np.float64)
    duck_len = int(round(0.24 * sr))
    if duck_len <= 4:
        return env

    t_duck = np.arange(duck_len, dtype=np.float64) / sr
    att_n = max(1, int(round(0.012 * sr)))
    dip = np.ones(duck_len, dtype=np.float64)
    dip[:att_n] = np.linspace(0.0, 1.0, att_n)
    dip[att_n:] = np.exp(-t_duck[att_n:] / 0.075)
    duck_curve = 1.0 - depth * dip

    for kt in kick_times:
        idx = int(round(kt * sr))
        if 0 <= idx < num_samples:
            end = min(num_samples, idx + duck_len)
            env[idx:end] = np.minimum(env[idx:end], duck_curve[:end - idx])
    return env


# ---------------------------------------------------------------------------
# Ana Aranjman ve Müzik Üretici
# ---------------------------------------------------------------------------
def generate_music(
    style: str = "A",
    duration: float = DEFAULT_DURATION,
    groove_start: float = DEFAULT_GROOVE_START,
    outro_start: float = DEFAULT_OUTRO_START,
    sr: int = SAMPLE_RATE,
) -> MusicResult:
    """
    Belirtilen stil (A, B, C) ve zamanlama noktalarına göre
    Intro -> Main Groove (4-bar loop + riser) -> Outro yapısında
    tamamen sentetik stereo müzik parçasını üretir.
    """
    style_key = style.strip().upper()
    if style_key not in STYLE_SPECS:
        raise ValueError(f"Geçersiz stil '{style}'. Beklenen: A, B veya C.")

    spec = STYLE_SPECS[style_key]
    rng = np.random.default_rng(spec.seed)

    total_samples = max(1, int(round(duration * sr)))
    groove_start = max(0.0, min(groove_start, duration))
    outro_start = max(groove_start, min(outro_start, duration))

    bpm, bars_count = choose_bpm(style_key, groove_start, outro_start)
    beat_dur = 60.0 / bpm
    bar_dur = 4.0 * beat_dur

    # Ayrı veriyolu (bus) tamponları: pad, melodik/harmonik (reverb alacaklar) ve kuru (bas/davul)
    pad_bus = np.zeros((total_samples, 2), dtype=np.float64)
    melodic_bus = np.zeros((total_samples, 2), dtype=np.float64)
    dry_bus = np.zeros((total_samples, 2), dtype=np.float64)

    notes: List[NoteEvent] = []
    kick_times: List[float] = []

    def add_note(
        t_start: float,
        dur: float,
        instrument: str,
        note_str: str,
        velocity: float,
        pan: float = 0.0,
        attack: Optional[float] = None,
        release: Optional[float] = None,
    ) -> None:
        if t_start >= duration or dur <= 0.01:
            return
        midi = note_to_midi(note_str)
        freq = midi_to_freq(midi)
        ev = NoteEvent(
            time=float(t_start),
            duration=float(dur),
            instrument=instrument,
            note_name=midi_to_note(midi),
            midi=midi,
            freq_hz=freq,
            velocity=float(velocity),
            pan=float(pan),
        )
        notes.append(ev)

        if instrument == "pad":
            att = attack if attack is not None else min(0.35, dur * 0.25)
            rel = min(0.65, dur * 0.30)
            cutoff = 1200.0 if style_key == "C" else 1500.0
            l_sig, r_sig = synth_pad_voice(freq, dur, sr, rng, attack=att, release=rel, cutoff_hz=cutoff)
            idx0 = max(0, int(round(t_start * sr)))
            idx1 = min(total_samples, idx0 + l_sig.shape[0])
            seg = idx1 - idx0
            if seg > 0:
                pad_bus[idx0:idx1, 0] += l_sig[:seg] * velocity
                pad_bus[idx0:idx1, 1] += r_sig[:seg] * velocity
        elif instrument == "epiano":
            sig = synth_fm_epiano(freq, dur, sr=sr, velocity=velocity)
            mix_mono_into_stereo(melodic_bus, sig, t_start, pan=pan, sr=sr)
        elif instrument == "bell":
            sig = synth_fm_bell(freq, dur, sr=sr, velocity=velocity)
            mix_mono_into_stereo(melodic_bus, sig, t_start, pan=pan, sr=sr)
        elif instrument == "pluck":
            sig = synth_pluck(freq, dur, sr=sr, velocity=velocity)
            mix_mono_into_stereo(melodic_bus, sig, t_start, pan=pan, sr=sr)
        elif instrument == "bass":
            att = attack if attack is not None else 0.015
            rel = release if release is not None else 0.055
            sig = synth_sub_bass(freq, dur, sr=sr, velocity=velocity, attack=att, release=rel)
            mix_mono_into_stereo(dry_bus, sig, t_start, pan=pan, sr=sr)

    # -----------------------------------------------------------------------
    # 1. BÖLÜM: INTRO (0 .. groove_start) — yumuşak pad kabarması + 4 notalık çan motifi
    # -----------------------------------------------------------------------
    if groove_start > 0.05:
        intro_pad_dur = groove_start + 0.35
        intro_att = min(1.5, max(0.20, groove_start * 0.60))
        for n_str in spec.tonic_voicing:
            add_note(0.0, intro_pad_dur, "pad", n_str, velocity=0.46, pan=0.0, attack=intro_att)

        bell_motif = ("E4", "G4", "B4", "D5")
        bell_pans = (-0.30, 0.25, -0.20, 0.30)
        m_start = groove_start * 0.18
        m_step = (groove_start * 0.66) / len(bell_motif)
        for i, (b_note, b_pan) in enumerate(zip(bell_motif, bell_pans)):
            bt = m_start + i * m_step
            vel_b = 0.44 + 0.05 * i
            add_note(bt, max(0.45, groove_start - bt + 0.25), "bell", b_note, velocity=vel_b, pan=b_pan)

    # -----------------------------------------------------------------------
    # 2. BÖLÜM: MAIN GROOVE (groove_start .. outro_start)
    # -----------------------------------------------------------------------
    groove_dur = max(0.0, outro_start - groove_start)
    total_bars_int = int(math.ceil(groove_dur / bar_dur - 1e-6))

    kick_sample = synth_kick(sr=sr, velocity=0.88)
    hat_sample = synth_hat(sr=sr, rng=rng, velocity=0.45)
    snap_sample = synth_snap_or_clap(sr=sr, rng=rng, kind="snap", velocity=0.62)
    clap_sample = synth_snap_or_clap(sr=sr, rng=rng, kind="clap", velocity=0.66)

    for bar_idx in range(total_bars_int):
        bar_t0 = groove_start + bar_idx * bar_dur
        if bar_t0 >= outro_start - 1e-4:
            break
        cur_bar_dur = min(bar_dur, outro_start - bar_t0)
        chord_i = bar_idx % len(spec.chord_names)
        root_note = spec.chord_roots[chord_i]
        voicing = spec.chord_voicings[chord_i]

        if style_key == "A":
            for v_note in voicing:
                add_note(bar_t0, cur_bar_dur + 0.15, "pad", v_note, velocity=0.56, attack=0.25)

            for beat_off, vel, dur_beats in ((0.0, 0.78, 1.35), (1.5, 0.66, 1.75)):
                nt = bar_t0 + beat_off * beat_dur
                if nt < outro_start - 0.05:
                    ndur = min(dur_beats * beat_dur, outro_start - nt)
                    for vi, v_note in enumerate(voicing):
                        pan_v = -0.25 + 0.16 * vi
                        add_note(nt, ndur, "epiano", v_note, velocity=vel, pan=pan_v)

            fill_t = bar_t0 + 3.5 * beat_dur
            if fill_t < outro_start - 0.05:
                top_note = voicing[-1]
                add_note(fill_t, min(0.6 * beat_dur, outro_start - fill_t), "epiano", top_note, velocity=0.52, pan=0.25)

            for b_off, b_len, b_vel in ((0.0, 2.3, 0.76), (2.5, 1.35, 0.64)):
                bt = bar_t0 + b_off * beat_dur
                if bt < outro_start - 0.04:
                    add_note(bt, min(b_len * beat_dur, outro_start - bt), "bass", root_note, velocity=b_vel)

            for k_beat in (0.0, 2.0):
                kt = bar_t0 + k_beat * beat_dur
                if kt < outro_start - 0.02:
                    kick_times.append(kt)
                    mix_mono_into_stereo(dry_bus, kick_sample, kt, pan=0.0, sr=sr)

            for s_beat in (1.0, 3.0):
                st = bar_t0 + s_beat * beat_dur
                if st < outro_start - 0.02:
                    mix_mono_into_stereo(melodic_bus, snap_sample, st, pan=0.08, sr=sr)

            for h_beat in (0.5, 1.5, 2.5, 3.5):
                ht = bar_t0 + h_beat * beat_dur
                if ht < outro_start - 0.02:
                    mix_mono_into_stereo(dry_bus, hat_sample * 0.75, ht, pan=-0.15, sr=sr)

        elif style_key == "B":
            for v_note in voicing:
                add_note(bar_t0, cur_bar_dur + 0.10, "pad", v_note, velocity=0.48, attack=0.18)

            arp_pattern = (0, 1, 2, 3, 2, 1, 2, 3, 0, 1, 2, 3, 2, 3, 1, 2)
            step_16 = beat_dur * 0.25
            for step_i, v_idx in enumerate(arp_pattern):
                at = bar_t0 + step_i * step_16
                if at >= outro_start - 0.02:
                    break
                arp_note = voicing[v_idx % len(voicing)]
                if step_i in (7, 15):
                    arp_midi = note_to_midi(arp_note) + 12
                    arp_note = midi_to_note(arp_midi)
                pan_ping = -0.45 if (step_i % 2 == 0) else 0.45
                vel_16 = 0.76 if (step_i % 4 == 0) else 0.56
                add_note(at, min(step_16 * 1.35, outro_start - at), "pluck", arp_note, velocity=vel_16, pan=pan_ping)

            step_8 = beat_dur * 0.5
            for b_step in range(8):
                bt = bar_t0 + b_step * step_8
                if bt >= outro_start - 0.02:
                    break
                b_vel = 0.74 if (b_step % 2 == 0) else 0.60
                add_note(bt, min(step_8 * 0.90, outro_start - bt), "bass", root_note, velocity=b_vel)

            for k_beat in (0.0, 1.0, 2.0, 3.0):
                kt = bar_t0 + k_beat * beat_dur
                if kt < outro_start - 0.02:
                    kick_times.append(kt)
                    mix_mono_into_stereo(dry_bus, kick_sample * 0.95, kt, pan=0.0, sr=sr)

            for c_beat in (1.0, 3.0):
                ct = bar_t0 + c_beat * beat_dur
                if ct < outro_start - 0.02:
                    mix_mono_into_stereo(melodic_bus, clap_sample, ct, pan=0.05, sr=sr)

            for h_beat in (0.5, 1.5, 2.5, 3.5):
                ht = bar_t0 + h_beat * beat_dur
                if ht < outro_start - 0.02:
                    mix_mono_into_stereo(dry_bus, hat_sample * 0.95, ht, pan=0.18, sr=sr)

        else:  # style_key == "C"
            for v_note in voicing:
                add_note(bar_t0, cur_bar_dur + 0.45, "pad", v_note, velocity=0.62, attack=0.65)

            add_note(bar_t0, min(cur_bar_dur * 0.80, outro_start - bar_t0), "bass", root_note, velocity=0.60, attack=0.30)

            penta_phrases = (
                ((0.0, "E5", -0.35), (1.5, "G4", 0.30), (3.0, "C5", -0.20)),
                ((0.5, "A4", 0.35), (2.0, "D5", -0.30), (3.0, "E5", 0.25)),
                ((0.0, "C5", -0.25), (2.0, "E5", 0.35), (3.5, "D5", -0.30)),
                ((1.0, "G4", 0.25), (2.5, "A4", -0.35), (3.5, "G5", 0.30)),
            )
            phrase = penta_phrases[bar_idx % len(penta_phrases)]
            for beat_off, p_note, p_pan in phrase:
                pt = bar_t0 + beat_off * beat_dur
                if pt < outro_start - 0.05:
                    vel_p = 0.76 if beat_off == 0.0 else 0.64
                    add_note(pt, min(1.8 * beat_dur, outro_start - pt + 0.4), "bell", p_note, velocity=vel_p, pan=p_pan)

    # Outro'ya girerken 1 ölçülük filtrelenmiş gürültü yükselişi (riser/fill)
    if groove_dur >= 0.8:
        riser_dur = min(bar_dur, groove_dur * 0.5)
        riser_start = outro_start - riser_dur
        riser_stereo = synth_riser(riser_dur, sr=sr, rng=rng)
        r_idx0 = max(0, int(round(riser_start * sr)))
        r_idx1 = min(total_samples, r_idx0 + riser_stereo.shape[0])
        if r_idx1 > r_idx0:
            melodic_bus[r_idx0:r_idx1] += riser_stereo[:r_idx1 - r_idx0]

    # -----------------------------------------------------------------------
    # 3. BÖLÜM: OUTRO (outro_start .. duration) — tonik akor + çanlar + uzun kuyruk
    # -----------------------------------------------------------------------
    outro_dur = max(0.0, duration - outro_start)
    if outro_dur > 0.1:
        ring_dur = max(0.2, outro_dur - 0.15)
        # Kapanış basını sona kadar uzat ve yavaşça söndür (kısa sönüm, kuyruğun ortasında
        # basın birden kesilmesine yol açıyordu)
        add_note(outro_start, ring_dur, "bass", spec.tonic_root, velocity=0.68, attack=0.02,
                 release=min(2.2, ring_dur * 0.5))
        for vi, t_note in enumerate(spec.tonic_voicing):
            pan_v = -0.30 + 0.15 * vi
            add_note(outro_start, ring_dur, "pad", t_note, velocity=0.58, pan=pan_v, attack=0.10)
            add_note(outro_start, min(ring_dur, 2.6), "epiano", t_note, velocity=0.72, pan=-pan_v)

        outro_bells = ("G4", "B4", "D5", "E5")
        for bi, b_note in enumerate(outro_bells):
            bt = outro_start + bi * min(0.26, outro_dur * 0.08)
            if bt < duration - 0.12:
                b_pan = -0.35 if bi % 2 == 0 else 0.35
                add_note(bt, max(0.3, duration - bt - 0.1), "bell", b_note, velocity=0.66 - 0.06 * bi, pan=b_pan)

    # -----------------------------------------------------------------------
    # 4. MİKS, VERİYOLU FİLTRELERİ, SIDECHAIN, REVERB VE MASTERING
    # -----------------------------------------------------------------------
    pad_cutoff = 1250.0 if style_key == "C" else 1550.0
    pad_bus = fft_filter_1d(pad_bus, sr=sr, lowpass_hz=pad_cutoff, highpass_hz=75.0)
    melodic_bus = fft_filter_1d(melodic_bus, sr=sr, lowpass_hz=4600.0, highpass_hz=90.0)

    if kick_times:
        sc_depth = 0.38 if style_key == "A" else 0.30
        sc_env = build_sidechain_envelope(total_samples, kick_times, sr=sr, depth=sc_depth)
        pad_bus *= sc_env[:, None]

    ir = build_synthetic_stereo_ir(spec.reverb_rt60, sr=sr, rng=rng)
    reverb_send = pad_bus * 0.85 + melodic_bus * 1.0
    wet_reverb = fft_convolve_stereo(reverb_send, ir)

    wet = spec.reverb_wet
    dry = 1.0 - wet * 0.5
    mix = dry * (pad_bus + melodic_bus) + wet * wet_reverb + dry_bus

    # Yapısal dinamik zarfı:
    # - Intro (0 .. groove_start): yumuşak yükseliş (sakin giriş)
    # - Outro (outro_start .. duration): doğal üstel sönümleme + son ~2.5s kosinüs fade-out
    intro_n = min(total_samples, int(round(groove_start * sr)))
    if intro_n > 1:
        u_in = np.linspace(0.0, 1.0, intro_n)
        intro_env = 0.22 + 0.58 * (u_in ** 1.35)
        mix[:intro_n, :] *= intro_env[:, None]

    outro_idx = min(total_samples, int(round(outro_start * sr)))
    outro_n = total_samples - outro_idx
    if outro_n > 1:
        t_out = np.arange(outro_n, dtype=np.float64) / sr
        natural_decay = np.exp(-t_out / max(0.35, outro_dur * 0.48))
        mix[outro_idx:, :] *= natural_decay[:, None]

    # Başlangıçta 15 ms yumuşak fade-in
    fade_in_n = min(total_samples, max(1, int(round(0.015 * sr))))
    mix[:fade_in_n, :] *= np.linspace(0.0, 1.0, fade_in_n)[:, None]

    # Outro sonunda ~2.5 s yumuşak fade-out ve son 60 ms tam dijital sessizlik
    silence_tail_s = min(0.065, duration * 0.05)
    silence_tail_n = max(1, int(round(silence_tail_s * sr)))
    fade_out_s = min(2.5, max(0.25, outro_dur * 0.65)) if outro_dur > 0.1 else min(0.5, duration * 0.25)
    fade_out_n = min(total_samples - silence_tail_n, max(1, int(round(fade_out_s * sr))))

    if fade_out_n > 0:
        fo_start = total_samples - silence_tail_n - fade_out_n
        fo_end = total_samples - silence_tail_n
        u_fo = np.linspace(0.0, 1.0, fade_out_n)
        fo_curve = 0.5 * (1.0 + np.cos(math.pi * u_fo))
        mix[fo_start:fo_end, :] *= fo_curve[:, None]

    mix[total_samples - silence_tail_n:, :] = 0.0

    # Nazik tanh yumuşak kırpma (soft clip)
    raw_peak = float(np.max(np.abs(mix)))
    if raw_peak > 1e-12:
        mix = mix / raw_peak
    drive = 1.18
    mix = np.tanh(mix * drive) / math.tanh(drive)

    # Hedef ses yüksekliği (RMS ≈ -18.5 dBFS / ~-17 LUFS) ve True Peak <= -1.0 dBFS (-1.15 dBFS tavan):
    target_rms_lin = 10.0 ** (-18.5 / 20.0)
    target_peak_lin = 10.0 ** (-1.15 / 20.0)
    cur_rms = float(np.sqrt(np.mean(mix ** 2)))
    if cur_rms > 1e-12:
        mix = mix * (target_rms_lin / cur_rms)

    # Tepe noktası -1.15 dBFS'i aşarsa yumuşak sınırlayıcı ve tavan normalizasyonu uygula
    cur_peak = float(np.max(np.abs(mix)))
    if cur_peak > target_peak_lin:
        mix = target_peak_lin * np.tanh(mix / target_peak_lin)
        cur_peak = float(np.max(np.abs(mix)))
        if cur_peak > target_peak_lin:
            mix = mix * (target_peak_lin / cur_peak)

    # Son 60 ms'nin tam dijital sessizlik olduğundan emin ol
    mix[total_samples - silence_tail_n:, :] = 0.0

    final_peak = float(np.max(np.abs(mix)))
    final_rms = float(np.sqrt(np.mean(mix ** 2)))
    peak_dbfs = 20.0 * math.log10(max(1e-12, final_peak))
    rms_dbfs = 20.0 * math.log10(max(1e-12, final_rms))

    pcm16 = np.clip(np.round(mix * 32767.0), -32767, 32767).astype(np.int16)
    notes.sort(key=lambda e: (e.time, e.instrument, e.midi))

    return MusicResult(
        audio=mix,
        pcm16=pcm16,
        sample_rate=sr,
        style=spec.code,
        style_name=spec.name,
        bpm=bpm,
        bpm_range=spec.bpm_range,
        key=spec.key,
        scale_semitones=spec.scale_semitones,
        chord_loop=spec.chord_names,
        bars=bars_count,
        duration=duration,
        groove_start=groove_start,
        outro_start=outro_start,
        peak_dbfs=peak_dbfs,
        rms_dbfs=rms_dbfs,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# WAV Kaydedici, Özet Yazdırıcı ve PNG Rapor Oluşturucu
# ---------------------------------------------------------------------------
def write_wav(out_path: Path, result: MusicResult) -> None:
    """48 kHz, 16-bit PCM stereo WAV dosyasını standart wave modülü ile kaydeder."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(result.sample_rate)
        wf.writeframes(result.pcm16.tobytes())


def format_summary_text(result: MusicResult) -> str:
    """Standart çıktı (stdout) için parça özetini ve ilk 2 ölçüdeki nota olaylarını biçimlendirir."""
    chords_str = " | ".join(result.chord_loop)
    lines = [
        "=== Devre Analizi Müzik Özeti ===",
        f"Stil        : {result.style} ({result.style_name})",
        f"BPM         : {result.bpm:.2f} (hedef aralık: {result.bpm_range[0]:.0f}–{result.bpm_range[1]:.0f})",
        f"Ton / Dizi  : {result.key}",
        f"Akor Döngüsü: | {chords_str} |",
        f"Groove Ölçü : {result.bars:.2f} bar ({result.groove_start:.2f}s .. {result.outro_start:.2f}s)",
        f"Süre        : {result.duration:.2f} s ({result.audio.shape[0]} örnek @ {result.sample_rate} Hz)",
        f"Peak dBFS   : {result.peak_dbfs:.2f} dBFS",
        f"RMS dBFS    : {result.rms_dbfs:.2f} dBFS",
        "",
        "--- İlk 2 Bar Nota Olayları (zaman, enstrüman, nota, hız/velocity) ---",
    ]
    bar_dur = 240.0 / result.bpm
    cutoff_t = result.groove_start + 2.0 * bar_dur - 1e-4
    first_notes = [n for n in result.notes if n.time <= cutoff_t]
    for ev in first_notes[:64]:
        lines.append(
            f"  t={ev.time:6.2f}s | {ev.instrument:<7s} | {ev.note_name:<4s} "
            f"({ev.freq_hz:6.1f} Hz) | vel={ev.velocity:.2f}"
        )
    if len(first_notes) > 64:
        lines.append(f"  ... (ilk 2 barda toplam {len(first_notes)} nota olayı)")
    return "\n".join(lines)


def _load_font(weight: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = FONT_PATHS.get(weight, FONT_PATHS["regular"])
    try:
        return ImageFont.truetype(path, size=size)
    except Exception:
        return ImageFont.load_default()


def write_report_png(report_path: Path, result: MusicResult) -> None:
    """
    Her iki kanalın dalga formunu, log-frekans spektrogramını, groove-start ve
    outro-start dikey işaretçilerini ve metin özet bloğunu içeren PNG raporu üretir.
    """
    report_path.parent.mkdir(parents=True, exist_ok=True)
    img_w, img_h = 1600, 1000
    bg_col = (18, 20, 26)
    panel_col = (26, 29, 38)
    border_col = (58, 64, 82)
    text_col = (238, 240, 246)
    sec_col = (165, 172, 190)
    accent_l = (56, 166, 255)
    accent_r = (82, 214, 154)
    marker_col = (255, 184, 56)

    img = Image.new("RGB", (img_w, img_h), bg_col)
    draw = ImageDraw.Draw(img)

    f_title = _load_font("bold", 26)
    f_meta = _load_font("semibold", 18)
    f_small = _load_font("regular", 15)
    f_mono = _load_font("mono", 16)

    # 1. Üst Özet Metin Bloğu
    draw.rounded_rectangle((30, 20, img_w - 30, 155), radius=10, fill=panel_col, outline=border_col, width=2)
    draw.text(
        (50, 32),
        f"Devre Analizi Arka Plan Müziği Raporu — Stil {result.style}: {result.style_name}",
        font=f_title,
        fill=text_col,
    )

    chords_str = " | ".join(result.chord_loop)
    meta_line1 = (
        f"Stil: {result.style} ({result.style_name})    "
        f"BPM: {result.bpm:.2f}    "
        f"Ton: {result.key}    "
        f"Akor Döngüsü: | {chords_str} |    "
        f"Ölçü (Groove): {result.bars:.1f} bar"
    )
    meta_line2 = (
        f"Süre: {result.duration:.2f} s    "
        f"Groove Başlangıcı: {result.groove_start:.2f} s    "
        f"Outro Başlangıcı: {result.outro_start:.2f} s    "
        f"Peak: {result.peak_dbfs:.2f} dBFS    "
        f"RMS: {result.rms_dbfs:.2f} dBFS"
    )
    draw.text((50, 74), meta_line1, font=f_meta, fill=accent_l)
    draw.text((50, 108), meta_line2, font=f_mono, fill=sec_col)

    plot_x0, plot_x1 = 135, img_w - 45
    plot_w = plot_x1 - plot_x0

    def time_to_x(t_s: float) -> int:
        u = max(0.0, min(1.0, t_s / max(1e-6, result.duration)))
        return int(round(plot_x0 + u * plot_w))

    # 2. Sol ve Sağ Kanal Dalga Formu Panelleri
    wave_boxes = [
        ("Sol Kanal (L)", 180, 340, 0, accent_l),
        ("Sağ Kanal (R)", 360, 520, 1, accent_r),
    ]
    n_samples = result.audio.shape[0]
    samples_per_col = max(1, n_samples // plot_w)
    trimmed_n = samples_per_col * plot_w

    for label, y0, y1, ch_idx, col in wave_boxes:
        draw.rounded_rectangle((plot_x0, y0, plot_x1, y1), radius=6, fill=panel_col, outline=border_col, width=1)
        mid_y = (y0 + y1) // 2
        half_h = (y1 - y0) * 0.45
        draw.line((plot_x0, mid_y, plot_x1, mid_y), fill=(45, 50, 65), width=1)

        ch_data = result.audio[:trimmed_n, ch_idx].reshape(plot_w, samples_per_col)
        v_min = np.min(ch_data, axis=1)
        v_max = np.max(ch_data, axis=1)
        v_rms = np.sqrt(np.mean(ch_data ** 2, axis=1))

        rms_col = (col[0] // 2, col[1] // 2, col[2] // 2)
        for ix in range(plot_w):
            px = plot_x0 + ix
            py_top = int(round(mid_y - v_max[ix] * half_h))
            py_bot = int(round(mid_y - v_min[ix] * half_h))
            draw.line((px, py_top, px, py_bot), fill=rms_col, width=1)
            ry_top = int(round(mid_y - v_rms[ix] * half_h))
            ry_bot = int(round(mid_y + v_rms[ix] * half_h))
            draw.line((px, ry_top, px, ry_bot), fill=col, width=1)

        draw.text((28, mid_y - 10), label, font=f_small, fill=text_col)
        draw.text((plot_x0 + 8, y0 + 6), "+0 dBFS", font=f_small, fill=sec_col)
        draw.text((plot_x0 + 8, y1 - 22), "-0 dBFS", font=f_small, fill=sec_col)

    # 3. Log-Frekans Spektrogram Paneli
    spec_y0, spec_y1 = 555, 925
    spec_h = spec_y1 - spec_y0
    draw.rounded_rectangle((plot_x0, spec_y0, plot_x1, spec_y1), radius=6, fill=panel_col, outline=border_col, width=1)

    mono = 0.5 * (result.audio[:, 0] + result.audio[:, 1])
    n_fft = 2048
    win = np.hanning(n_fft)
    padded = np.pad(mono, (n_fft // 2, n_fft // 2))
    n_frames = plot_w
    frame_starts = np.linspace(0, max(0, padded.shape[0] - n_fft), n_frames).astype(int)
    frames = np.stack([padded[s:s + n_fft] * win for s in frame_starts], axis=0)
    stft_mag = np.abs(np.fft.rfft(frames, axis=1)) / (n_fft * 0.25)
    stft_db = 20.0 * np.log10(np.maximum(1e-6, stft_mag))

    # Logaritmik frekans eksenine (30 Hz .. 16000 Hz) ara değerleme (interpolasyon)
    f_min, f_max = 30.0, 16000.0
    fft_freqs = np.fft.rfftfreq(n_fft, d=1.0 / result.sample_rate)
    row_freqs = np.geomspace(f_max, f_min, spec_h)
    bin_indices = np.interp(row_freqs, fft_freqs, np.arange(fft_freqs.shape[0]))
    idx_lo = np.floor(bin_indices).astype(int)
    idx_hi = np.minimum(stft_db.shape[1] - 1, idx_lo + 1)
    frac = (bin_indices - idx_lo)[None, :]
    log_spec_db = stft_db[:, idx_lo] * (1.0 - frac) + stft_db[:, idx_hi] * frac  # (plot_w, spec_h)

    # [-85 dBFS .. -5 dBFS] -> RGB renk haritası (lacivert -> mor -> turuncu -> sarı)
    norm = np.clip((log_spec_db.T + 85.0) / 80.0, 0.0, 1.0)  # (spec_h, plot_w)
    r_ch = np.clip(norm * 1.45, 0.0, 1.0) ** 1.2 * 255.0
    g_ch = np.clip((norm - 0.25) * 1.35, 0.0, 1.0) ** 1.4 * 255.0
    b_ch = np.clip(np.sin(norm * math.pi) * 0.85 + (norm ** 3) * 0.6, 0.0, 1.0) * 255.0
    spec_rgb = np.stack([r_ch, g_ch, b_ch], axis=-1).astype(np.uint8)
    spec_img = Image.fromarray(spec_rgb, mode="RGB")
    img.paste(spec_img, (plot_x0, spec_y0))
    draw.rounded_rectangle((plot_x0, spec_y0, plot_x1, spec_y1), radius=6, outline=border_col, width=1)

    # Log-frekans ekseni etiketleri
    for f_tick in (50, 100, 250, 500, 1000, 2500, 5000, 10000):
        u_f = math.log(f_max / f_tick) / math.log(f_max / f_min)
        fy = int(round(spec_y0 + u_f * spec_h))
        draw.line((plot_x0 - 6, fy, plot_x0, fy), fill=sec_col, width=1)
        lbl = f"{f_tick // 1000}kHz" if f_tick >= 1000 else f"{f_tick}Hz"
        draw.text((55, fy - 8), lbl, font=f_small, fill=sec_col)

    # 4. groove-start ve outro-start dikey işaretçileri
    for m_time, m_label in (
        (result.groove_start, f"groove-start ({result.groove_start:.2f}s)"),
        (result.outro_start, f"outro-start ({result.outro_start:.2f}s)"),
    ):
        mx = time_to_x(m_time)
        for yy in range(180, spec_y1, 10):
            draw.line((mx, yy, mx, min(spec_y1, yy + 6)), fill=marker_col, width=2)
        draw.rounded_rectangle((mx + 4, 184, mx + 175, 208), radius=4, fill=(32, 28, 18), outline=marker_col, width=1)
        draw.text((mx + 10, 187), m_label, font=f_small, fill=marker_col)

    # Zaman ekseni çizgileri
    step_sec = 5 if result.duration >= 15.0 else 1
    for s_tick in range(0, int(math.ceil(result.duration)) + 1, step_sec):
        tx = time_to_x(float(s_tick))
        draw.line((tx, spec_y1, tx, spec_y1 + 6), fill=sec_col, width=1)
        draw.text((tx - 10, spec_y1 + 10), f"{s_tick}s", font=f_small, fill=sec_col)

    img.save(report_path, format="PNG")


# ---------------------------------------------------------------------------
# Komut Satırı Arayüzü (CLI)
# ---------------------------------------------------------------------------
def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Devre Analizi tanıtım videosu için telifsiz sentetik müzik üreteci."
    )
    parser.add_argument("--style", type=str, default="A", choices=["A", "B", "C", "a", "b", "c"], help="Müzik stili (A, B, C)")
    parser.add_argument("--out", type=Path, required=True, help="Çıktı WAV dosya yolu")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION, help="Toplam süre (saniye)")
    parser.add_argument("--groove-start", type=float, default=DEFAULT_GROOVE_START, help="Ritim/groove başlangıç saniyesi")
    parser.add_argument("--outro-start", type=float, default=DEFAULT_OUTRO_START, help="Outro başlangıç saniyesi")
    parser.add_argument("--report", type=Path, default=None, help="İsteğe bağlı analiz raporu PNG yolu")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    t0 = time.perf_counter()
    result = generate_music(
        style=args.style.upper(),
        duration=args.duration,
        groove_start=args.groove_start,
        outro_start=args.outro_start,
    )
    write_wav(args.out, result)
    if args.report is not None:
        write_report_png(args.report, result)
    dt = time.perf_counter() - t0

    print(format_summary_text(result))
    print(f"\nÜretim tamamlandı ({dt:.2f}s) -> {args.out}")
    if args.report is not None:
        print(f"Rapor kaydedildi -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
