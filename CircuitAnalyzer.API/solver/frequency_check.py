"""
CircuitAnalyzer API — Kaynak Frekansı Denetimi

Fazör analizi TEK bir açısal frekans (ω) için geçerlidir. Bu modül
devredeki kaynakların frekanslarını inceler ve:

    • Analiz frekansını belirler (istekte yoksa SINE kaynağından alır)
    • Farklı frekanslı kaynaklar varsa süperpozisyon uyarısı üretir
    • AC analizde DC kaynak / SINE ofseti (0 Hz bileşeni) varsa bildirir
    • Frekans bilinmeden reaktif eleman çözülemeyeceğini hata olarak döndürür

★ Kaynak frekansları:
    SINE(off amp FREQ ...) → kaynağın kendi frekansı
    AC_PHASOR(mag, phase)  → frekans taşımaz, global analiz frekansını kullanır
    DC                     → 0 Hz
    E/G/H/F (bağımlı)      → kendi frekansı yoktur, yok sayılır (kazanç gerçek
                             sabittir; DC ve AC modlarının ikisinde de geçerli)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from models.request import AnalysisMode
from explainer.formatting import num
from models.response import SolutionStep
from parser.netlist_parser import (
    ParsedCircuit, ElementType, DC_SOURCES, SINE_SOURCES, PHASOR_SOURCES,
)


@dataclass
class FrequencyCheck:
    """Denetim sonucu."""
    frequency: Optional[float]                       # Analizde kullanılacak frekans
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)  # Çözümü engelleyen hatalar
    steps: List[SolutionStep] = field(default_factory=list)
    source_frequencies: Dict[str, float] = field(default_factory=dict)


def _fmt_hz(f: float) -> str:
    return "DC (0 Hz)" if f == 0 else f"{num(f)} Hz"


def check_source_frequencies(
    parsed: ParsedCircuit,
    mode: AnalysisMode,
    frequency: Optional[float],
    superposition: bool = False,
) -> FrequencyCheck:
    """
    Kaynak frekanslarını denetler ve analiz frekansını belirler.

    Mesaj önekleri (projedeki kural):
        '⚠' → sonuçlar geçersiz/eksik olabilir (status = warning)
        'ℹ' → bilgilendirme
    """
    check = FrequencyCheck(frequency=frequency)

    sine = [e for e in parsed.elements
            if e.element_type in SINE_SOURCES]
    phasor = [e for e in parsed.elements
              if e.element_type in PHASOR_SOURCES]
    dc = [e for e in parsed.elements
          if e.element_type in DC_SOURCES]
    offsets = [e for e in sine if abs(e.params.get("offset", 0)) > 0]

    # ── DC analiz ──
    if mode == AnalysisMode.DC:
        if sine or phasor:
            ids = ", ".join(e.id for e in sine + phasor)
            check.warnings.append(
                f"ℹ DC analizde AC kaynaklar ({ids}) sıfırlandı "
                "(gerilim kaynağı → kısa devre, akım kaynağı → açık devre). "
                "Sonuçlar yalnızca DC bileşenidir."
            )
        if offsets:
            ids = ", ".join(
                f"{e.id}: {num(e.params['offset'])} V" for e in offsets)
            check.warnings.append(
                f"⚠ SINE kaynak ofseti ({ids}) DC analizde hesaba "
                "katılmadı. Ofseti DC kaynak olarak ayrıca modelleyin."
            )
        return check

    # ── AC analiz: kaynakların frekanslarını topla ──
    sine_freqs = {
        e.id: float(e.params["frequency"])
        for e in sine if e.params.get("frequency", 0) > 0
    }
    check.source_frequencies = dict(sine_freqs)

    if frequency is None and sine_freqs:
        distinct = sorted(set(sine_freqs.values()))
        frequency = distinct[0]
        check.frequency = frequency
        if len(distinct) == 1:
            ids = ", ".join(sine_freqs)
            check.warnings.append(
                "ℹ Analiz frekansı belirtilmedi; kaynak frekansı "
                f"kullanıldı: f = {num(frequency)} Hz ({ids})."
            )

    # Her kaynağın gerçek frekansı
    groups: Dict[float, List[str]] = {}
    for e in sine + phasor:
        f = sine_freqs.get(e.id, frequency)
        if f is not None:
            groups.setdefault(f, []).append(e.id)
    for e in dc:
        groups.setdefault(0.0, []).append(e.id)
    for e in offsets:
        groups.setdefault(0.0, []).append(f"{e.id} (ofset)")

    ac_freqs = sorted(f for f in groups if f > 0)

    if len(ac_freqs) > 1:
        listing = ", ".join(
            f"{_fmt_hz(f)}: {', '.join(groups[f])}" for f in sorted(groups))
        if superposition:
            check.warnings.append(
                f"ℹ Devrede farklı frekanslarda kaynaklar var — {listing}. "
                "Süperpozisyon yöntemi her kaynağı kendi frekansında çözüp "
                "sonuçları zaman domeninde topluyor (Anlatım bölümüne bakın). "
                "Tablodaki tek frekanslı sonuçlar yalnızca bilgi amaçlıdır."
            )
        else:
            check.warnings.append(
                f"⚠ Devrede farklı frekanslarda kaynaklar var — {listing}.\n"
                "Fazör analizi tek bir ω için geçerlidir; farklı frekanslı "
                "fazörler doğrudan toplanamaz. Bu sonuçlar tüm AC kaynaklar "
                f"f = {num(frequency)} Hz kabul edilerek hesaplandı ve fiziksel "
                "olarak GEÇERSİZDİR.\n"
                "Doğru çözüm için yöntem olarak Süperpozisyon'u seçin: program "
                "her kaynağı kendi frekansında çözüp sonuçları zaman domeninde toplar."
            )
    else:
        if (ac_freqs and frequency is not None
                and sine_freqs and ac_freqs[0] != frequency):
            ids = ", ".join(sine_freqs)
            check.warnings.append(
                f"⚠ Kaynak frekansı ({ids}: {num(ac_freqs[0])} Hz) analiz "
                f"frekansından ({num(frequency)} Hz) farklı. Analiz "
                f"{num(frequency)} Hz'de yapıldı; kaynağın gerçek yanıtı için "
                f"frequency = {num(ac_freqs[0])} gönderin."
            )
        if 0.0 in groups and ac_freqs:
            is_rms = getattr(parsed, "value_basis", "PEAK") == "RMS"
            amp_txt = "√2·|V|" if is_rms else "|V|"
            check.warnings.append(
                f"ℹ AC analizde DC bileşenler ({', '.join(groups[0.0])}) "
                "sıfırlandı (gerilim kaynağı → kısa devre, akım kaynağı → "
                "açık devre). Sonuçlar yalnızca "
                f"f = {num(ac_freqs[0])} Hz AC bileşenidir; toplam yanıt için "
                "DC analizini ayrıca yapıp süperpozisyonla ekleyin: "
                f"v(t) = V_DC + {amp_txt}·cos(ωt + θ)."
            )
        if dc and not (sine or phasor):
            check.warnings.append(
                "⚠ AC analiz seçildi ama devrede AC kaynak yok. DC "
                f"kaynaklar ({', '.join(e.id for e in dc)}) fazör "
                "analizinde sıfırlandığı için tüm sonuçlar 0 olur. "
                "Bu devre için DC modunu kullanın."
            )

    if len(groups) > 1:
        is_rms = getattr(parsed, "value_basis", "PEAK") == "RMS"
        amp_k = "√2·|V_k|" if is_rms else "|V_k|"
        latex_amp = "\\sqrt{2}\\,|V_k|" if is_rms else "|V_k|"
        check.steps.append(SolutionStep(
            step_number=0,
            title="Frekans Analizi — Süperpozisyon",
            description=(
                "Fazör (frekans alanı) analizi yalnızca tek bir frekansta "
                "geçerlidir. Farklı frekanslı kaynaklar içeren devrelerde "
                "süperpozisyon teoremi uygulanır:\n"
                "1. Her frekans grubu için diğer tüm bağımsız kaynakları "
                "sıfırla (gerilim kaynağı → kısa devre, akım kaynağı → açık devre).\n"
                "2. O frekansta empedansları hesapla (Z_L = jωL, "
                "Z_C = 1/(jωC); DC'de C açık, L kısa devre) ve devreyi çöz.\n"
                "3. Her sonucu zaman alanına çevir ve topla: "
                f"v(t) = V_DC + Σ {amp_k}·cos(ω_k t + θ_k)."
            ),
            equations=[
                f"{_fmt_hz(f)}: {', '.join(ids)}"
                for f, ids in sorted(groups.items())
            ],
            latex_formula=(
                f"v(t) = V_{{DC}} + \\sum_k {latex_amp} \\cos(\\omega_k t + \\theta_k)"
            ),
            result_snapshot={
                "frequency_groups": {
                    _fmt_hz(f): ids for f, ids in sorted(groups.items())
                },
                "analysis_frequency": frequency,
            },
        ))

    # ── Frekans hiç belirlenemedi ──
    if frequency is None:
        reactive = [e.id for e in parsed.elements if e.element_type in (
            ElementType.CAPACITOR, ElementType.INDUCTOR)]
        if reactive:
            check.errors.append(
                "⚠ AC analiz için frekans gerekli: istekte 'frequency' "
                "verilmedi ve kaynaklarda frekans tanımlı değil "
                "(AC_PHASOR kaynaklar frekans taşımaz).\n"
                f"Reaktif elemanların ({', '.join(reactive)}) empedansı "
                "Z_L = jωL, Z_C = 1/(jωC) frekansa bağlıdır — "
                "frekans olmadan devre çözülemez."
            )

    return check
