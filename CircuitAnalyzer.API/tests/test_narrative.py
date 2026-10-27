"""
CircuitAnalyzer API — Türkçe Anlatım Motoru Testleri

Test edilen modül: explainer/narrative.py (build_explanation)
- DC gerilim bölücü (KCL, Ohm yasası, güç hesabı, kontrol, prob)
- Merdiven devresi düğüm analizi (Cramer kuralı, 2 bilinmeyenli sistem)
- Thevenin ve Norton eşdeğeri anlatımları (Vth, Rth, In, Rn, Maksimum Güç Transferi)
- AC RC devresi (empedanslar, fazörler, zaman domeni sin/cos, güç faktörü)
- Süperdüğüm devresi ve kısıt denklemleri
- DC bobin (kısa devre, süperdüğüm sebebi) ve AC analizde DC kaynak sıfırlanması
- Muhafız Testi (Guard Test): Yanlış ara değerlerde cebirsel türetme iptali ve güvenli geri dönüş
- Değişmezler (Invariants): Geçerli blok tipleri, biçimlendirme hataları (e-0, j-, nan, inf) kontrolü
- Çözülemeyen devre dayanıklılığı ve FastAPI /analyze uç noktası entegrasyonu
"""

import re
from typing import List, Optional

import pytest

from explainer.narrative import build_explanation
from models.request import AnalysisMode, AnalysisType, TheveninTerminals
from models.response import ExplanationBlock, ExplanationSection
from parser.netlist_parser import parse_netlist
from solver.circuit_solver import solve_circuit
from tests.test_thevenin import BRIDGE, GND


# ═══════════════════════════════════════════════════════
#  YARDIMCI FONKSİYONLAR
# ═══════════════════════════════════════════════════════

def section_by_title(
    sections: List[ExplanationSection], prefix: str
) -> Optional[ExplanationSection]:
    """Başlığı verilen ön ek ile başlayan ilk bölümü bulur."""
    for s in sections:
        if s.title.startswith(prefix):
            return s
    return None


def all_texts(sections: List[ExplanationSection]) -> List[str]:
    """Tüm bölümlerdeki tüm blok metinlerini düz liste olarak döndürür."""
    return [b.text for s in sections for b in s.blocks]


def section_texts(section: Optional[ExplanationSection]) -> List[str]:
    """Belirli bir bölümdeki blok metinlerini döndürür."""
    if section is None:
        return []
    return [b.text for b in section.blocks]


def blocks_of_kind(
    section: Optional[ExplanationSection], kind: str
) -> List[ExplanationBlock]:
    """Belirli bir bölümdeki istenen türdeki blokları döndürür."""
    if section is None:
        return []
    return [b for b in section.blocks if b.kind == kind]


# ═══════════════════════════════════════════════════════
#  3.a: DC BÖLÜCÜ (Voltage Divider)
# ═══════════════════════════════════════════════════════

def test_dc_divider_narrative(solve):
    net = (
        "V1 1 0 DC 12\n"
        "R1 1 2 1k\n"
        "R2 2 0 2k\n"
        "* PROBE VP1 V(2)\n"
        f"{GND}"
    )
    results, steps, errors = solve(net, "DC")
    explanation = results.explanation
    assert len(explanation) > 0, errors

    # Bölüm başlıkları sırasıyla belirtilenlerle başlamalı
    expected_title_prefixes = [
        "Devreyi Tanıyalım",
        "Bilinen Düğüm Gerilimleri",
        "Düğüm Denklemleri (KCL)",
        "Denklemlerin Çözümü",
        "Eleman Akımları (Ohm Yasası)",
    ]
    actual_titles = [s.title for s in explanation]
    for i, exp_pfx in enumerate(expected_title_prefixes):
        assert actual_titles[i].startswith(exp_pfx), (
            f"Adım {i}: '{actual_titles[i]}' beklenen ön ek '{exp_pfx}' ile başlamıyor"
        )

    texts = all_texts(explanation)

    # Birebir bulunması gereken satırlar
    assert "Düğüm 2: (V₂ − V₁)/R1 + V₂/R2 = 0" in texts
    assert "⇒ (V₂ − 12)/1000 + V₂/2000 = 0" in texts
    assert "V₂ · (1/R1 + 1/R2) = V₁/R1" in texts
    assert "V₂ · 1.5 mS = 12 mA" in texts
    assert "I_R1 = (V₁ − V₂)/R1 = (12 V − 8 V) / 1 kΩ = 4 mA  (Düğüm 1 → Düğüm 2)" in texts
    assert "P_R2 = I²·R = (4 mA)² · 2 kΩ = 32 mW" in texts

    # "Denklemlerin Çözümü" içindeki result bloğu
    sol_sec = section_by_title(explanation, "Denklemlerin Çözümü")
    assert sol_sec is not None
    sol_results = [b.text for b in blocks_of_kind(sol_sec, "result")]
    assert any("V₂ = 12 mA / 1.5 mS = 8 V" == r for r in sol_results)

    # Güç dengesi kontrol bloğu: "48 mW" ve "✓" içermeli
    check_blocks = [b.text for s in explanation for b in s.blocks if b.kind == "check"]
    assert any("48 mW" in c and "✓" in c for c in check_blocks)

    # Sonuç bölümü prob değerini içermeli
    summary_sec = section_by_title(explanation, "Sonuç")
    assert summary_sec is not None
    summary_texts = section_texts(summary_sec)
    assert any("VP1 (gerilim probu) = 8 V" in t for t in summary_texts)


# ═══════════════════════════════════════════════════════
#  3.b: LADDER NODAL (2 Bilinmeyenli Cramer Çözümü)
# ═══════════════════════════════════════════════════════

def test_ladder_nodal_cramer_narrative(solve):
    net = (
        "V1 1 0 DC 12\n"
        "R1 1 2 1k\n"
        "R2 2 0 2k\n"
        "R3 2 3 1k\n"
        "R4 3 0 1k\n"
        f"{GND}"
    )
    results, steps, errors = solve(net, "DC")
    explanation = results.explanation
    texts = all_texts(explanation)

    # Doğrusal denklem satırı
    assert any("2.5·V₂ − V₃ = 12" in t for t in texts)

    # Cramer kuralı adımları
    # Kesirlerden kurtulma: Düğüm 2 satırı ×2 → 5·V₂ − 2·V₃ = 24
    assert any("Düğüm 2 denklemini 2 ile çarpalım" in t for t in texts)
    assert any("Δ = a₁₁·a₂₂ − a₁₂·a₂₁ = 5·2 − (−2)·(−1) = 8" in t for t in texts)
    assert any("V₂ = Δ₁/Δ = 48 / 8 = 6 V" in t for t in texts)
    assert any("V₃ = Δ₂/Δ = 24 / 8 = 3 V" in t for t in texts)


# ═══════════════════════════════════════════════════════
#  3.c: LADDER THEVENIN & NORTON (Port 3–0)
# ═══════════════════════════════════════════════════════

def test_ladder_thevenin_narrative(solve):
    net = (
        "V1 1 0 DC 12\n"
        "R1 1 2 1k\n"
        "R2 2 0 2k\n"
        "R3 2 3 1k\n"
        "R4 3 0 1k\n"
        f"{GND}"
    )
    results, steps, errors = solve(
        net, "DC", analysis_type="THEVENIN", terminals=("3", "0")
    )
    explanation = results.explanation
    assert len(explanation) > 0, errors

    # 1. Adım — Vth
    sec_vth = section_by_title(explanation, "1. Adım — Vth (Açık Devre Gerilimi)")
    assert sec_vth is not None
    vth_results = [b.text for b in blocks_of_kind(sec_vth, "result")]
    assert any("Vth = 3 V" in r for r in vth_results)

    # 2. Adım — Rth
    sec_rth = section_by_title(explanation, "2. Adım — Rth (Eşdeğer Direnç)")
    assert sec_rth is not None
    rth_results = [b.text for b in blocks_of_kind(sec_rth, "result")]
    assert any("Rth = 625 Ω" in r for r in rth_results)

    # Maksimum Güç Transferi
    sec_pmax = section_by_title(explanation, "Maksimum Güç Transferi")
    assert sec_pmax is not None
    pmax_texts = section_texts(sec_pmax)
    assert any("3.6 mW" in t for t in pmax_texts)


def test_ladder_norton_narrative(solve):
    net = (
        "V1 1 0 DC 12\n"
        "R1 1 2 1k\n"
        "R2 2 0 2k\n"
        "R3 2 3 1k\n"
        "R4 3 0 1k\n"
        f"{GND}"
    )
    results, steps, errors = solve(
        net, "DC", analysis_type="NORTON", terminals=("3", "0")
    )
    explanation = results.explanation
    assert len(explanation) > 0, errors

    texts = all_texts(explanation)
    assert any("In = 4.8 mA" in t for t in texts)
    assert any("Rn = Rth" in t for t in texts)


# ═══════════════════════════════════════════════════════
#  3.d: AC RC (SINE Kaynağı, Fazörler, Zaman Domeni)
# ═══════════════════════════════════════════════════════

def test_ac_rc_narrative(solve):
    net = (
        "VAC1 1 0 SINE(0 10 50 0 0 0)\n"
        "R1 1 2 100\n"
        "C1 2 0 100u\n"
        f"{GND}"
    )
    results, steps, errors = solve(net, "AC_TIME", frequency=None)
    explanation = results.explanation
    assert len(explanation) > 0, errors

    # Empedanslar ve Fazörler
    sec_z = section_by_title(explanation, "Empedanslar ve Fazörler")
    assert sec_z is not None
    z_texts = section_texts(sec_z)
    assert any("Z_C1 = 1/(jωC)" in t and "−j31.83 Ω" in t for t in z_texts)

    # Zaman Domenine Dönüş (sinüs referansı)
    sec_t = section_by_title(explanation, "Zaman Domenine Dönüş")
    assert sec_t is not None
    t_texts = section_texts(sec_t)
    assert any("sin(314.2t − 72.34°)" in t for t in t_texts)

    # Güç Hesabı — güç faktörü yönü "ileri" olmalı (kapasitif devre)
    sec_pw = section_by_title(explanation, "Güç Hesabı")
    assert sec_pw is not None
    pw_texts = section_texts(sec_pw)
    assert any("ileri" in t for t in pw_texts)

    # Düğüm gerilimi V₂ kutupsal sonucu
    sol_sec = section_by_title(explanation, "Denklemlerin Çözümü")
    assert sol_sec is not None
    sol_texts = section_texts(sol_sec)
    assert any("3.033∠−72.34° V" in t for t in sol_texts)


# ═══════════════════════════════════════════════════════
#  3.e: SUPERNODE (Süperdüğüm ve Kısıt)
# ═══════════════════════════════════════════════════════

def test_supernode_narrative(solve):
    net = (
        "V1 1 0 DC 12\n"
        "R1 1 2 1k\n"
        "V2 2 3 DC 5\n"
        "R2 3 0 2k\n"
        "R3 2 0 4k\n"
        f"{GND}"
    )
    results, steps, errors = solve(net, "DC")
    explanation = results.explanation
    assert len(explanation) > 0, errors

    # KCL metninde "süperdüğüm" geçmeli
    sec_kcl = section_by_title(explanation, "Düğüm Denklemleri (KCL)")
    assert sec_kcl is not None
    kcl_texts = section_texts(sec_kcl)
    assert any("süperdüğüm" in t.lower() for t in kcl_texts)
    assert any("Kısıt (V2): V₂ − V₃ = 5" in t for t in kcl_texts)

    # Denklemlerin çözümü "birlikte çözülünce" fallback metnini kullanmalı
    sec_sol = section_by_title(explanation, "Denklemlerin Çözümü")
    assert sec_sol is not None
    sol_texts = section_texts(sec_sol)
    assert any("birlikte çözülünce" in t for t in sol_texts)
    assert any("V₂ = 8.286 V" in t for t in sol_texts)


# ═══════════════════════════════════════════════════════
#  3.f: DC BOBİN KISA DEVRE & AC'DE DC KAYNAK SIFIRLANMASI
# ═══════════════════════════════════════════════════════

def test_dc_inductor_narrative_is_short_circuit(solve):
    # Bilinmeyen düğümler arasındaki DC bobin kısa devre olarak tanımlanmalı
    net = (
        "V1 1 0 DC 12\n"
        "R1 1 2 1k\n"
        "L1 2 3 10m\n"
        "R2 3 0 2k\n"
        f"{GND}"
    )
    results, steps, errors = solve(net, "DC")
    explanation = results.explanation
    assert len(explanation) > 0, errors

    sec_kcl = section_by_title(explanation, "Düğüm Denklemleri (KCL)")
    assert sec_kcl is not None
    kcl_texts = section_texts(sec_kcl)

    # L1'in kısa devre olduğu söylenmeli, "gerilim kaynağı" denmemeli
    assert any("L1 DC'de kısa devredir" in t for t in kcl_texts)
    assert not any("L1 gerilim kaynağı" in t for t in kcl_texts)


def test_dc_source_in_ac_analysis_is_zeroed(solve):
    # AC analizde yer alan DC kaynak "sıfırlanır" şeklinde açıklanmalı
    net = (
        "VAC1 1 0 AC_PHASOR(10, 0)\n"
        "V2 2 0 DC 5\n"
        "R1 1 2 100\n"
        f"{GND}"
    )
    results, steps, errors = solve(net, "AC_PHASOR", frequency=50)
    explanation = results.explanation
    assert len(explanation) > 0, errors

    texts = all_texts(explanation)
    assert any("V2 bir DC kaynağıdır; AC analizde sıfırlanır" in t for t in texts)


# ═══════════════════════════════════════════════════════
#  3.g: GUARD TEST (Yanlış Değerlerde Cebirsel Türetme İptali)
# ═══════════════════════════════════════════════════════

def test_guard_wrong_derivations_never_shown():
    net = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n{GND}"
    parsed = parse_netlist(net)
    results, _, _ = solve_circuit(parsed, AnalysisMode.DC, None)

    # Düğüm 2'nin gerilimini kasıtlı olarak hatalı veriyoruz (8 yerine 7.9)
    raw_nodes = {"0": 0.0, "1": 12.0, "2": 7.9}
    raw_currents = {
        k: (v.value if isinstance(v.value, float)
            else complex(v.value.real, v.value.imaginary))
        for k, v in results.element_currents.items()
    }

    expl = build_explanation(
        parsed=parsed,
        is_dc=True,
        frequency=None,
        analysis_type=AnalysisType.NODAL,
        terminals=None,
        raw_nodes=raw_nodes,
        raw_currents=raw_currents,
        results=results,
    )

    sec_sol = section_by_title(expl, "Denklemlerin Çözümü")
    assert sec_sol is not None
    sol_texts = section_texts(sec_sol)

    # 1.5 mS cebirsel türetme adımı kesinlikle GÖSTERİLMEMELİ
    assert not any("1.5 mS" in t for t in sol_texts), (
        "Hatalı gerilimde 1.5 mS ara türetmesi gösterilmemeli!"
    )
    # Güvenli 'birlikte çözülünce' metnine düşmeli
    assert any("birlikte çözülünce" in t for t in sol_texts)
    assert any("V₂ = 7.9 V" in t for t in sol_texts)


# ═══════════════════════════════════════════════════════
#  3.h: DEĞİŞMEZLER (Invariants over ≥6 circuits)
# ═══════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "net, mode, freq, atype, term",
    [
        # 1. DC Gerilim Bölücü
        (
            f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n{GND}",
            "DC", None, "NODAL", None,
        ),
        # 2. DC Merdiven
        (
            f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\nR3 2 3 1k\nR4 3 0 1k\n{GND}",
            "DC", None, "NODAL", None,
        ),
        # 3. DC Süperdüğüm
        (
            f"V1 1 0 DC 12\nR1 1 2 1k\nV2 2 3 DC 5\nR2 3 0 2k\nR3 2 0 4k\n{GND}",
            "DC", None, "NODAL", None,
        ),
        # 4. DC Merdiven Thevenin
        (
            f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\nR3 2 3 1k\nR4 3 0 1k\n{GND}",
            "DC", None, "THEVENIN", ("3", "0"),
        ),
        # 5. DC Merdiven Norton
        (
            f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\nR3 2 3 1k\nR4 3 0 1k\n{GND}",
            "DC", None, "NORTON", ("3", "0"),
        ),
        # 6. AC RC SINE
        (
            f"VAC1 1 0 SINE(0 10 50 0 0 0)\nR1 1 2 100\nC1 2 0 100u\n{GND}",
            "AC_TIME", None, "NODAL", None,
        ),
        # 7. AC Bridge Thevenin
        (
            BRIDGE,
            "AC_PHASOR", 1000, "THEVENIN", ("2", "3"),
        ),
    ],
)
def test_narrative_invariants(solve, net, mode, freq, atype, term):
    results, steps, errors = solve(
        net, mode, frequency=freq, analysis_type=atype, terminals=term
    )
    explanation = results.explanation
    assert len(explanation) > 0, f"Açıklama boş geldi: {errors}"

    sub_to_digit = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")

    for s in explanation:
        for b in s.blocks:
            # 1. Her blok türü izin verilen kümede olmalı
            assert b.kind in {"text", "math", "result", "note", "check"}, (
                f"Bilinmeyen blok türü: {b.kind} ('{b.text}')"
            )

            # 2. İstenmeyen gösterim kalıntıları bulunmamalı
            t = b.text.lower()
            for forbidden in ("e-0", "e+0", "j-", "nan", "inf"):
                assert forbidden not in t, (
                    f"Metinde yasaklı ibare '{forbidden}' bulundu: '{b.text}'"
                )

    # 3. DC için "Denklemlerin Çözümü" içindeki V<indis> = ... sonuç satırları
    # results.node_voltages ile uyuşmalı
    if mode == "DC":
        sol_sec = section_by_title(explanation, "Denklemlerin Çözümü")
        if sol_sec is not None:
            for b in sol_sec.blocks:
                if b.kind == "result":
                    m = re.match(
                        r"^V([₀₁₂₃₄₅₆₇₈₉]+)\s*=\s*(?:.*=\s*)?([−\-\d.]+)\s*(?:[a-zA-ZΩµ]*)$",
                        b.text,
                    )
                    if m:
                        node = m.group(1).translate(sub_to_digit)
                        val_str = m.group(2).replace("−", "-")
                        val = float(val_str)
                        expected = results.node_voltages[node].value
                        if isinstance(expected, complex):
                            expected = expected.real
                        assert abs(val - expected) < 0.02, (
                            f"Düğüm {node} gerilimi uyuşmazlığı: anlatım={val}, çözücü={expected}"
                        )


# ═══════════════════════════════════════════════════════
#  3.i: ÇÖZÜLEMEYEN DEVRE & FASTAPI /analyze UÇ NOKTASI
# ═══════════════════════════════════════════════════════

def test_unsolvable_circuit_returns_empty_explanation_without_exception(solve):
    # Boşta asılı kalan (floating) R9 elemanı nedeniyle tekil matris hatası
    net = (
        "V1 1 0 DC 12\n"
        "R1 1 2 1k\n"
        "R2 2 0 2k\n"
        "R9 5 6 1k\n"
        f"{GND}"
    )
    results, steps, errors = solve(net, "DC")
    assert isinstance(results.explanation, list)
    assert len(results.explanation) == 0
    assert len(errors) > 0


def test_api_analyze_returns_non_empty_explanation(client):
    net = (
        "V1 1 0 DC 12\n"
        "R1 1 2 1k\n"
        "R2 2 0 2k\n"
        f"{GND}"
    )
    resp = client.post("/analyze", json={"netlist": net, "mode": "DC"})
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    assert "explanation" in body["results"]
    explanation = body["results"]["explanation"]
    assert isinstance(explanation, list)
    assert len(explanation) > 0
    first_sec = explanation[0]
    assert "title" in first_sec
    assert "blocks" in first_sec
