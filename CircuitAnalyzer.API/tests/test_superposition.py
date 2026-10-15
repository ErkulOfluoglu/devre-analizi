"""
CircuitAnalyzer API — Süperpozisyon (Superposition) Yöntemi Testleri

Test edilen modüller:
- solver/superposition.py (build_subcircuits, solve_contributions, phasor_sum)
- explainer/superposition_narrative.py (build_superposition_sections)
- solver/frequency_check.py (check_source_frequencies, superposition flag)
- solver/circuit_solver.py (SUPERPOSITION entegrasyonu, API ve anlatım)
"""

import pytest

from parser.netlist_parser import ElementType, parse_netlist
from solver.superposition import build_subcircuits, phasor_sum, solve_contributions
from tests.conftest import as_complex

GND = "* GND1 — Referans toprak (Node 0)"


def section_by_title(sections, prefix):
    """Başlığı verilen ön ek ile başlayan ilk bölümü bulur."""
    for s in sections:
        if s.title.startswith(prefix):
            return s
    return None


def all_texts(sections):
    """Tüm bölümlerdeki blok metinlerini düz liste olarak döndürür."""
    return [b.text for s in sections for b in s.blocks]


# ═══════════════════════════════════════════════════════
#  5. build_subcircuits TESTLERİ
# ═══════════════════════════════════════════════════════

def test_build_subcircuits():
    """
    5. build_subcircuits:
       V1 + V2 + I1 devresi:
         V1 1 0 DC 10
         V2 2 0 DC 5
         I1 3 0 DC 1m
         R1 1 2 1k
         R2 2 3 1k
       - 3 bağımsız kaynak olduğundan 3 alt devre oluşur.
       - Her alt devrede yalnızca aktif kaynak orijinal değerini korur.
       - Diğer gerilim kaynakları 0 V DC yapılır (kısa devre) ve
         params["superposition_zeroed"] = True olarak işaretlenir.
       - Diğer akım kaynakları devreden çıkarılır (açık devre, kept listesinde yer almaz).
       - zeroed listesinde gerilim kaynakları için "kısa devre",
         akım kaynakları için "açık devre" açıklamaları yer alır.
    """
    net = (
        f"{GND}\n"
        "V1 1 0 DC 10\n"
        "V2 2 0 DC 5\n"
        "I1 3 0 DC 1m\n"
        "R1 1 2 1k\n"
        "R2 2 3 1k\n"
    )
    parsed = parse_netlist(net)
    subs = build_subcircuits(parsed, global_frequency=None)

    assert len(subs) == 3

    # 1. Alt devre: Yalnız V1 aktif
    c1 = subs[0]
    assert c1.source.id == "V1"
    assert c1.is_dc is True
    assert c1.frequency is None
    c1_elms = {e.id: e for e in c1.parsed.elements}
    assert c1_elms["V1"].value == 10.0
    assert c1_elms["V2"].value == 0.0
    assert c1_elms["V2"].params.get("superposition_zeroed") is True
    assert "I1" not in c1_elms  # Akım kaynağı açık devre -> çıkarıldı
    assert any("kısa devre" in z and "V2" in z for z in c1.zeroed)
    assert any("açık devre" in z and "I1" in z for z in c1.zeroed)

    # 2. Alt devre: Yalnız V2 aktif
    c2 = subs[1]
    assert c2.source.id == "V2"
    c2_elms = {e.id: e for e in c2.parsed.elements}
    assert c2_elms["V2"].value == 5.0
    assert c2_elms["V1"].value == 0.0
    assert c2_elms["V1"].params.get("superposition_zeroed") is True
    assert "I1" not in c2_elms
    assert any("kısa devre" in z and "V1" in z for z in c2.zeroed)
    assert any("açık devre" in z and "I1" in z for z in c2.zeroed)

    # 3. Alt devre: Yalnız I1 aktif
    c3 = subs[2]
    assert c3.source.id == "I1"
    c3_elms = {e.id: e for e in c3.parsed.elements}
    assert c3_elms["I1"].value == 0.001
    assert c3_elms["V1"].value == 0.0
    assert c3_elms["V1"].params.get("superposition_zeroed") is True
    assert c3_elms["V2"].value == 0.0
    assert c3_elms["V2"].params.get("superposition_zeroed") is True
    assert any("kısa devre" in z and "V1" in z for z in c3.zeroed)
    assert any("kısa devre" in z and "V2" in z for z in c3.zeroed)


# ═══════════════════════════════════════════════════════
#  6. DC SÜPERPOZİSYON TESTLERİ
# ═══════════════════════════════════════════════════════

def test_superposition_dc_two_voltage_sources(solve):
    """
    6. DC devresi: İki gerilim kaynağı
       V1 1 0 DC 12, R1 1 2 1k, R2 2 0 2k, R3 2 3 1k, V2 3 0 DC 6
       El hesabı:
         1. Adım (Yalnız V1 aktif, V2=0 V kısa devre):
            Düğüm 3 topraklandığından R2 ve R3 paraleldir:
            R_eş = R2 || R3 = (2k · 1k) / (2k + 1k) = 2/3 kΩ ≈ 666.67 Ω
            Düğüm 2 gerilimi (gerilim bölücü):
            V₂′ = V1 · R_eş / (R1 + R_eş) = 12 · (2/3) / (1 + 2/3)
                = 12 · (2/5) = 4.8 V
         2. Adım (Yalnız V2 aktif, V1=0 V kısa devre):
            Düğüm 1 topraklandığından R1 ve R2 paraleldir:
            R_eş = R1 || R2 = (1k · 2k) / (1k + 2k) = 2/3 kΩ ≈ 666.67 Ω
            Düğüm 2 gerilimi (gerilim bölücü):
            V₂″ = V2 · R_eş / (R3 + R_eş) = 6 · (2/3) / (1 + 2/3)
                = 6 · (2/5) = 2.4 V
         Toplam:
            V₂ = V₂′ + V₂″ = 4.8 V + 2.4 V = 7.2 V (tam çözümle aynı)

       Anlatım kontrolleri:
         - Toplam bölümü: "V₂ = V₂′ + V₂″ = 4.8 V + 2.4 V = 7.2 V"
         - Doğrulama onayı: "tam çözümle aynı ✓"
         - Alt adım başlığı: "1. Adım — Yalnız V1 Aktif (DC)"
         - Alt adım metni: "V2 bu adımda sıfırlandı" (ve "AC analizde" kelimeleri GEÇMEZ)
    """
    net = (
        f"{GND}\n"
        "V1 1 0 DC 12\n"
        "R1 1 2 1k\n"
        "R2 2 0 2k\n"
        "R3 2 3 1k\n"
        "V2 3 0 DC 6\n"
    )
    res, steps, errs = solve(net, "DC", None, "SUPERPOSITION")
    assert not errs

    # results.superposition katkıları
    contribs = {c.source_id: c for c in res.superposition}
    assert "V1" in contribs and "V2" in contribs
    assert contribs["V1"].node_voltages["2"].real == pytest.approx(4.8, abs=1e-4)
    assert contribs["V2"].node_voltages["2"].real == pytest.approx(2.4, abs=1e-4)

    # Tam çözüm düğüm gerilimi
    assert res.node_voltages["2"].value == pytest.approx(7.2, abs=1e-4)

    # Anlatım metinleri kontrolü
    toplam_sec = section_by_title(res.explanation, "Toplam: Katkıların Toplanması")
    assert toplam_sec is not None
    toplam_texts = [b.text for b in toplam_sec.blocks]
    assert any("V₂ = V₂′ + V₂″ = 4.8 V + 2.4 V = 7.2 V" in t for t in toplam_texts)
    assert any("tam çözümle aynı ✓" in t for t in toplam_texts)

    # 1. Adım anlatımında DC'de sıfırlanma ifadesi
    adim1_sec = section_by_title(res.explanation, "1. Adım — Yalnız V1 Aktif (DC)")
    assert adim1_sec is not None
    adim1_texts = [b.text for b in adim1_sec.blocks]
    assert any("V2 bu adımda sıfırlandı" in t for t in adim1_texts)
    assert all("AC analizde" not in t for t in adim1_texts)


def test_superposition_dc_voltage_and_current_source(solve):
    """
    6. DC devresi: Gerilim + Akım kaynağı (V + I)
       V1 1 0 DC 10, R1 1 2 1k, R2 2 0 1k, I1 0 2 DC 2m
       El hesabı:
         1. Adım (Yalnız V1 aktif, I1 açık devre):
            R1 ve R2 seri gerilim bölücü:
            V₂′ = 10 · 1k / (1k + 1k) = 5 V
            I_R1′ = (10 - 5) / 1k = 5 mA
         2. Adım (Yalnız I1 aktif, V1=0 V kısa devre):
            Düğüm 1 topraklandı, R1 ve R2 paralel:
            R_eş = 1k || 1k = 500 Ω
            V₂″ = I1 · R_eş = 2 mA · 500 Ω = 1 V
            I_R1″ (1'den 2'ye doğru): (0 - 1) / 1k = -1 mA
         Toplam:
            V₂ = 5 V + 1 V = 6 V
            I_R1 = I_R1′ + I_R1″ = 5 mA + (−1 mA) = 4 mA
    """
    net = (
        f"{GND}\n"
        "V1 1 0 DC 10\n"
        "R1 1 2 1k\n"
        "R2 2 0 1k\n"
        "I1 0 2 DC 2m\n"
    )
    res, steps, errs = solve(net, "DC", None, "SUPERPOSITION")
    assert not errs

    # Düğüm gerilimleri ve katkıları
    contribs = {c.source_id: c for c in res.superposition}
    assert contribs["V1"].node_voltages["2"].real == pytest.approx(5.0, abs=1e-4)
    assert contribs["I1"].node_voltages["2"].real == pytest.approx(1.0, abs=1e-4)
    assert res.node_voltages["2"].value == pytest.approx(6.0, abs=1e-4)

    # Akım toplam satırı kontrolü
    texts = all_texts(res.explanation)
    assert any("I_R1 = I_R1′ + I_R1″ = 5 mA + (−1 mA) = 4 mA" in t for t in texts)


# ═══════════════════════════════════════════════════════
#  7. AYNI FREKANSLI AC SÜPERPOZİSYON
# ═══════════════════════════════════════════════════════

def test_superposition_same_frequency_ac(solve):
    """
    7. Aynı frekanslı AC devresi:
       İki AC_PHASOR kaynağı f = 50 Hz'de çalışır.
       VAC1 1 0 AC_PHASOR(10, 0)
       VAC2 3 0 AC_PHASOR(5, 90)
       R1 1 2 100, C1 2 0 100u, R2 2 3 100
       El hesabı:
         Doğrusal sistemde aynı frekanstaki katkıların fazörel toplamı,
         tüm kaynaklar devredeyken çözülen tam fazör çözümüne eşittir.
         Bağıl fark <= 1e-6 olmalıdır.
    """
    net = (
        f"{GND}\n"
        "VAC1 1 0 AC_PHASOR(10, 0)\n"
        "VAC2 3 0 AC_PHASOR(5, 90)\n"
        "R1 1 2 100\n"
        "C1 2 0 100u\n"
        "R2 2 3 100\n"
    )
    parsed = parse_netlist(net)
    contribs = solve_contributions(parsed, global_frequency=50)

    # 50 Hz fazör toplamı
    v2_sums = phasor_sum(contribs, "2", "v")
    assert 50.0 in v2_sums
    v2_phasor_total = v2_sums[50.0]

    # Tam çözüm (NODAL) ile karşılaştırma
    res_full, _, _ = solve(net, "AC_PHASOR", 50, "NODAL")
    full_v2 = as_complex(res_full.node_voltages["2"].value)

    # Bağıl fark rel <= 1e-6
    diff = abs(v2_phasor_total - full_v2)
    assert diff <= 1e-6 * max(abs(full_v2), 1e-9)


# ═══════════════════════════════════════════════════════
#  8. FARKLI FREKANSLI AC SÜPERPOZİSYON
# ═══════════════════════════════════════════════════════

def test_superposition_different_frequencies(client, solve):
    """
    8. Farklı frekanslı AC devresi:
       VAC1 SINE(0 10 50 0 0 0) [f = 50 Hz, ω = 314.159 rad/s]
       VAC2 SINE(0 5 60 0 0 0)  [f = 60 Hz, ω = 376.991 rad/s]
       R1 1 2 100, C1 2 0 100u, R2 2 3 100
       El hesabı:
         - 50 Hz bileşeni (Yalnız VAC1 aktif, VAC2=0 V kısa):
           Z_C1(50Hz) = -j31.831 Ω
           V2 = VAC1 · (Z_C1 || R2) / (R1 + (Z_C1 || R2))
              = 1.442 - j2.265 V = 2.685∠-57.52° V
         - 60 Hz bileşeni (Yalnız VAC2 aktif, VAC1=0 V kısa):
           Z_C1(60Hz) = -j26.526 Ω
           V2 = VAC2 · (Z_C1 || R1) / (R2 + (Z_C1 || R1))
              = 0.549 - j1.035 V = 1.172∠-62.05° V
         - Zaman domeni toplamı:
           v₂(t) = 2.685·sin(314.2t − 57.52°) + 1.172·sin(377t − 62.05°) V

       API kontrolleri:
         - SUPERPOSITION ile çözüldüğünde:
           status = "success"
           warnings listesinde '⚠' YOK, 'ℹ' bilgilendirme uyarısı VAR.
         - NODAL ile çözüldüğünde:
           status = "warning"
           warnings listesinde '⚠' VAR ve "Süperpozisyon" önerisi yer alır.
    """
    net = (
        f"{GND}\n"
        "VAC1 1 0 SINE(0 10 50 0 0 0)\n"
        "VAC2 3 0 SINE(0 5 60 0 0 0)\n"
        "R1 1 2 100\n"
        "C1 2 0 100u\n"
        "R2 2 3 100\n"
    )
    parsed = parse_netlist(net)
    contribs = solve_contributions(parsed, global_frequency=None)

    assert len(contribs) == 2
    c50 = [c for c in contribs if c.frequency == 50.0][0]
    c60 = [c for c in contribs if c.frequency == 60.0][0]

    # Her katkı, o frekansta bağımsız tek kaynaklı çözümle aynıdır:
    # 50 Hz için VAC2 kısa devre edilmiş tek kaynaklı netlist:
    net_vac1_alone = (
        f"{GND}\n"
        "VAC1 1 0 SINE(0 10 50 0 0 0)\n"
        "R1 1 2 100\n"
        "C1 2 0 100u\n"
        "R2 2 3 100\n"
        "VAC2 3 0 DC 0\n"
    )
    res_single_50, _, _ = solve(net_vac1_alone, "AC_TIME", 50, "NODAL")
    v2_single_50 = as_complex(res_single_50.node_voltages["2"].value)
    assert abs(c50.node_voltages["2"] - v2_single_50) <= 1e-6

    # 60 Hz için VAC1 kısa devre edilmiş tek kaynaklı netlist:
    net_vac2_alone = (
        f"{GND}\n"
        "VAC1 1 0 DC 0\n"
        "R1 1 2 100\n"
        "C1 2 0 100u\n"
        "R2 2 3 100\n"
        "VAC2 3 0 SINE(0 5 60 0 0 0)\n"
    )
    res_single_60, _, _ = solve(net_vac2_alone, "AC_TIME", 60, "NODAL")
    v2_single_60 = as_complex(res_single_60.node_voltages["2"].value)
    assert abs(c60.node_voltages["2"] - v2_single_60) <= 1e-6

    # Toplam bölümü zaman domeni formülü kontrolü
    res_sup, _, _ = solve(net, "AC_TIME", None, "SUPERPOSITION")
    texts = all_texts(res_sup.explanation)
    assert any(
        "v₂(t) = 2.685·sin(314.2t − 57.52°) + 1.172·sin(377t − 62.05°) V" in t
        for t in texts
    )

    # API üzerinden SUPERPOSITION ve NODAL karşılaştırması
    resp_sup = client.post("/analyze", json={
        "netlist": net,
        "mode": "AC_TIME",
        "analysis_type": "SUPERPOSITION",
    })
    data_sup = resp_sup.json()
    assert data_sup["status"] == "success"
    assert all("⚠" not in w for w in data_sup["warnings"])
    assert any("ℹ" in w for w in data_sup["warnings"])

    resp_nod = client.post("/analyze", json={
        "netlist": net,
        "mode": "AC_TIME",
        "analysis_type": "NODAL",
    })
    data_nod = resp_nod.json()
    assert data_nod["status"] == "warning"
    assert any("⚠" in w for w in data_nod["warnings"])
    assert any("Süperpozisyon" in w for w in data_nod["warnings"])


# ═══════════════════════════════════════════════════════
#  9. AC + DC KARIŞIK DEVRE (MIXED AC+DC)
# ═══════════════════════════════════════════════════════

def test_superposition_ac_dc_mix(solve):
    """
    9. AC + DC karışık devre:
       SINE 50 Hz + DC 5 V:
       V1 1 0 DC 5
       R1 1 2 1k
       R2 2 0 1k
       C1 3 2 10u
       VAC1 3 0 SINE(0 10 50 0 0 0)
       El hesabı:
         DC analizinde:
           VAC1 sıfırlanır (0 V).
           C1 kapasitörü DC'de açık devredir (akım = 0).
           Düğüm 2'deki devre yalnızca V1, R1 ve R2'den ibarettir:
           V2_DC = 5 V · 1k / (1k + 1k) = 2.5 V.
         AC analizinde (50 Hz):
           V1 sıfırlanır (kısa devre).
           C1 üzerinden gelen AC sinyali R1||R2 üzerine düşer.
         Toplam sonuçta V₂ düğüm geriliminin DC bileşeni 2.5 V olmalıdır.
    """
    net = (
        f"{GND}\n"
        "V1 1 0 DC 5\n"
        "R1 1 2 1k\n"
        "R2 2 0 1k\n"
        "C1 3 2 10u\n"
        "VAC1 3 0 SINE(0 10 50 0 0 0)\n"
    )
    parsed = parse_netlist(net)
    contribs = solve_contributions(parsed, global_frequency=None)

    # Katkılardan DC bileşeninin 2.5 V olduğunu kontrol et
    sums = phasor_sum(contribs, "2", "v")
    assert 0.0 in sums
    assert sums[0.0].real == pytest.approx(2.5, abs=1e-4)

    # Anlatım Toplam bölümünde DC bileşen v₂(t) = 2.5 + ... olarak yer alır
    res, _, _ = solve(net, "AC_TIME", None, "SUPERPOSITION")
    texts = all_texts(res.explanation)
    assert any("v₂(t) = 2.5 +" in t for t in texts)


# ═══════════════════════════════════════════════════════
#  10. API results.superposition VE TEK KAYNAK UYARISI
# ═══════════════════════════════════════════════════════

def test_superposition_api_results_and_single_source_error(client):
    """
    10. API üzerinden results.superposition yapısı ve tek kaynak denetimi:
        a) İki kaynaklı devrede results.superposition:
           - Her kaynak için bir SourceContribution öğesi içerir.
           - zeroed_sources, node_voltages, frequency alanları mevcuttur (DC için frequency=None).
        b) Tek kaynaklı devrede SUPERPOSITION seçildiğinde:
           - errors listesine en az iki bağımsız kaynak gerektiğini belirten
             'ℹ' bilgilendirme mesajı eklenir.
    """
    # a) İki kaynaklı devre
    net_two = (
        f"{GND}\n"
        "V1 1 0 DC 10\n"
        "V2 2 0 DC 5\n"
        "R1 1 2 1k\n"
    )
    resp = client.post("/analyze", json={
        "netlist": net_two,
        "mode": "DC",
        "analysis_type": "SUPERPOSITION",
    })
    assert resp.status_code == 200
    data = resp.json()
    sup_list = data["results"]["superposition"]
    assert len(sup_list) == 2
    for entry in sup_list:
        assert "source_id" in entry
        assert "zeroed_sources" in entry
        assert "node_voltages" in entry
        assert entry["frequency"] is None

    # b) Tek kaynaklı devre
    net_single = (
        f"{GND}\n"
        "V1 1 0 DC 10\n"
        "R1 1 0 1k\n"
    )
    resp_single = client.post("/analyze", json={
        "netlist": net_single,
        "mode": "DC",
        "analysis_type": "SUPERPOSITION",
    })
    assert resp_single.status_code == 200
    data_single = resp_single.json()
    assert any(
        "ℹ" in err and "en az iki bağımsız kaynak" in err
        for err in data_single["errors"]
    )
