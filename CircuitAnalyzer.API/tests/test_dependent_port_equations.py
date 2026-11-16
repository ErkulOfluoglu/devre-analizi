"""
Bağımlı kaynaklı Thevenin/Norton: kısa devre akımı (Isc) ve test kaynağı akımı (I_test)
çıplak sayı olarak verilmez; değiştirilmiş devrenin düğüm denklemleri, çözümü, eleman
akımları ve terminal düğümünde KCL gösterilir. Türetme çözücünün sayısını vermezse eski
metin kalır. Yardımcı kaynağın iç adı (Vsc_port…, Vtest_port…) öğrenciye gösterilmez.
"""

import pytest
from fastapi.testclient import TestClient

import solver.circuit_solver as cs
from main import app

GND = "* GND1 — Referans toprak (Node 0)"
MINUS = "−"
client = TestClient(app)

G_CIRCUIT = ("V1 1 0 DC 10\nR1 1 2 1000\nR2 2 0 2000\nG1 0 3 V(R2) 0.002\n"
             "R3 2 3 1000\nR4 3 0 4000")


def _sections(netlist, terminals=("3", "0"), method="THEVENIN", mode="DC", frequency=None):
    body = {"netlist": f"{netlist}\n{GND}", "mode": mode, "analysis_type": method,
            "thevenin_terminals": {"node_positive": terminals[0], "node_negative": terminals[1]}}
    if frequency is not None:
        body["frequency"] = frequency
        body["value_display"] = "PEAK"
    r = client.post("/analyze", json=body)
    assert r.status_code == 200, r.text
    return {s["title"]: [b["text"] for b in s["blocks"]]
            for s in r.json()["results"]["explanation"]}


def _step(secs, prefix):
    return next(v for k, v in secs.items() if k.startswith(prefix))


def _all_text(secs):
    return "\n".join(t for blocks in secs.values() for t in blocks)


def test_isc_route_shows_shorted_circuit_equations():
    """
    V1 = 10 V (1–0), R1 = 1 k (1–2), R2 = 2 k (2–0), G1 0 3 V(R2) 2 mS, R3 = 1 k (2–3),
    R4 = 4 k (3–0), port 3–0.
      Kısa devre: V₃ = V₀ = 0, bilinmeyen yalnız V₂:
        (V₂ − 10)/1000 + V₂/2000 + V₂/1000 = 0 → 2,5·V₂ = 10 (mS, mA) → V₂ = 4 V
      I_R3 = (4 − 0)/1 k = 4 mA (2 → 3), I_R4 = 0, G1 = 0,002·4 = 8 mA (0 → 3, Düğüm 3'e girer)
      Düğüm 3'te KCL: Isc = G1 + I_R3 − I_R4 = 8 + 4 − 0 = 12 mA
      Açık devre: V₂ = 100 V, V₃ = 240 V → Rth = 240 V / 12 mA = 20 kΩ
    """
    secs = _sections(G_CIRCUIT)
    sec = _step(secs, "2. Adım")
    assert any("Düğüm 3 ile Düğüm 0 aynı gerilimde olur (V₃ = V₀)" in t for t in sec)
    assert "V₃ = V₀ = 0 V" in sec
    assert "V_R2 = V₂ − V₀ = V₂" in sec
    assert "Düğüm 2: (V₂ − V₁)/R1 + V₂/R2 + (V₂ − V₃)/R3 = 0" in sec
    assert "V₂ = 10 / 2,5 = 4 V" in sec
    assert any(t.startswith("I_R3 = (V₂ − V₃)/R3 = (4 V − 0 V) / 1 kΩ = 4 mA") for t in sec)
    assert "G1 = 0,002·V_R2 = 0,002 · 4 V = 8 mA" in sec
    assert f"Isc = G1 + I_R3 {MINUS} I_R4 = 8 mA + 4 mA {MINUS} 0 mA = 12 mA" in sec
    # Eski satırlar korunur, türetmeden SONRA gelir
    assert sec.index("In = Isc = 12 mA") > sec.index(
        f"Isc = G1 + I_R3 {MINUS} I_R4 = 8 mA + 4 mA {MINUS} 0 mA = 12 mA")
    assert "Rth = 20 kΩ" in sec
    assert "_port" not in _all_text(secs)


def test_isc_route_with_voltage_source_at_terminal_uses_supernode_kcl():
    """
    V1 = 10 V (1–0), R1 = 1 k (1–2), E1 2 3 V(R2) 3, R2 = 1 k (3–0), port 3–0.
      Kısa devre: V₃ = 0 → V_R2 = 0 → kısıt V₂ − V₃ = 3·V_R2 = 0 → V₂ = 0
      Düğüm 3'te E1'in akımı bilinmez → Düğüm 2 ve 3 birlikte (süperdüğüm):
        Isc = I_R1 − I_R2 = (10 − 0)/1 k − 0 = 10 mA
      Açık devre: V₃ = 2 V → Rth = 2 V / 10 mA = 200 Ω
    """
    sec = _step(_sections("V1 1 0 DC 10\nR1 1 2 1000\nE1 2 3 V(R2) 3\nR2 3 0 1000"), "2. Adım")
    assert "Kısıt (E1): V₂ − V₃ = 3·V_R2" in sec
    assert any("Düğüm 2 ve 3 birlikte ele alınarak" in t for t in sec)
    assert f"Isc = I_R1 {MINUS} I_R2 = 10 mA {MINUS} 0 mA = 10 mA" in sec
    assert "Rth = 200 Ω" in sec


def test_isc_route_with_current_controlled_voltage_source():
    """
    V1 = 10 V (1–0), R1 = 1 k (1–2), H1 2 3 I(R1) 500 Ω, R2 = 1 k (3–0), port 3–0.
      Kısa devre: V₃ = 0, kısıt V₂ − V₃ = 500·I_R1 = 500·(10 − V₂)/1000
        → 1,5·V₂ = 5 → V₂ = 3,333 V, I_R1 = 6,667 mA
      Süperdüğüm {2, 3}: Isc = I_R1 − I_R2 = 6,667 − 0 = 6,667 mA
      Açık devre (tek çevre akımı I): V₃ = 1000·I, V₂ = 10 − 1000·I,
        H1: V₂ − V₃ = 500·I → 10 − 2000·I = 500·I → I = 4 mA, V₃ = 4 V
        → Rth = 4 V / 6,667 mA = 600 Ω
    """
    sec = _step(_sections("V1 1 0 DC 10\nR1 1 2 1000\nH1 2 3 I(R1) 500\nR2 3 0 1000"),
                "2. Adım")
    assert "Kısıt (H1): V₂ − V₃ = 500·I_R1" in sec
    assert "V₂ = 5 / 1,5 = 3,333 V" in sec
    assert f"Isc = I_R1 {MINUS} I_R2 = 6,667 mA {MINUS} 0 mA = 6,667 mA" in sec
    assert "Rth = 600 Ω" in sec


def test_isc_route_cut_containing_ground():
    """
    G1 devresi, port 1 (+) – 2 (−). Kısa devre: V₂ = V₁ = 10 V, V_R2 = 10 → G1 = 20 mA,
      Düğüm 3: (V₃ − 10)/1000 + V₃/4000 − 0,02 = 0 → 1,25·V₃ = 30 → V₃ = 24 V.
      Düğüm 1'deki V1'in akımı bilinmez → küme {0, 1}:
        R1 (1 → 2) çıkar: −0; R2 (2 → 0) girer: +5 mA; G1 (0 → 3) çıkar: −20 mA;
        R4 (3 → 0) girer: +6 mA → Isc = −9 mA
      Açık devre: V₁ − V₂ = 10 − 100 = −90 V → Rth = −90 / −0,009 = 10 kΩ
    """
    sec = _step(_sections(G_CIRCUIT, ("1", "2")), "2. Adım")
    assert any("Düğüm 0 ve 1 birlikte ele alınarak" in t for t in sec)
    assert (f"Isc = {MINUS}I_R1 + I_R2 {MINUS} G1 + I_R4 = 0 mA + 5 mA {MINUS} 20 mA + 6 mA "
            f"= {MINUS}9 mA") in sec
    assert "Rth = 10 kΩ" in sec


def test_kcl_sum_shows_enough_digits_under_cancellation():
    """
    R1 = 3 k (1–0), G1 0 1 V(R1) 0,33 mS, port 1–0 (test kaynağı yolu).
      V₁ = 1 V: I_R1 = 333,33 µA, G1 = 330 µA (0 → 1, Düğüm 1'e girer)
      I_test = 333,333 − 330 = 3,333 µA (4 basamakla 333,3 − 330 = 3,3 olurdu)
      Rth = 1 V / 3,333 µA = 300 kΩ
    """
    sec = _step(_sections("R1 1 0 3000\nG1 0 1 V(R1) 0.00033", ("1", "0")), "2. Adım")
    assert f"I_test = I_R1 {MINUS} G1 = 333,333 µA {MINUS} 330 µA = 3,333 µA" in sec
    assert "Rth = 300 kΩ" in sec


def test_isc_route_without_unknowns_and_with_current_source():
    """
    V1 = 10 V (1–0), R1 = 1 k (1–2), R2 = 2 k (2–0), G1 0 2 V(R1) 1 mS, I1 0 2 2 mA, port 2–0.
      Kısa devre: V₂ = 0, bilinmeyen düğüm kalmaz.
      I_R1 = 10 mA (1 → 2), I_R2 = 0, G1 = 0,001·(10 − 0) = 10 mA (0 → 2), I1 = 2 mA (0 → 2)
      Isc = I_R1 − I_R2 + G1 + I1 = 10 − 0 + 10 + 2 = 22 mA
      Açık devre: (V₂ − 10)/1000 + V₂/2000 − 0,001·(10 − V₂) − 0,002 = 0
                  → 2,5·V₂ = 22 → V₂ = 8,8 V → Rth = 8,8 V / 22 mA = 400 Ω
    """
    sec = _step(_sections("V1 1 0 DC 10\nR1 1 2 1000\nR2 2 0 2000\nG1 0 2 V(R1) 0.001\n"
                          "I1 0 2 DC 0.002", ("2", "0")), "2. Adım")
    assert "V₂ = V₀ = 0 V" in sec
    assert "G1 = 0,001·V_R1 = 0,001 · 10 V = 10 mA" in sec
    assert (f"Isc = I_R1 {MINUS} I_R2 + G1 + I1 = 10 mA {MINUS} 0 mA + 10 mA + 2 mA = 22 mA"
            in sec)
    assert "Rth = 400 Ω" in sec


def test_isc_route_with_non_ground_negative_terminal():
    """
    Aynı G1 devresi, port 2 (+) – 3 (−).
      Kısa devre: V₂ = V₃ = V (süperdüğüm {2, 3}, kısıt V₂ − V₃ = 0):
        (V − 10)/1000 + V/2000 + V/4000 − 0,002·V = 0 → −0,25·V = 10 → V = −40 V
      Düğüm 2'de KCL (tel 2 → 3): I_R1 = 50 mA girer, I_R2 = −20 mA (2 → 0 yönünde),
        I_R3 = 0 → Isc = I_R1 − I_R2 − I_R3 = 50 − (−20) − 0 = 70 mA
      Açık devre: V₂ = 100 V, V₃ = 240 V → Vth = −140 V → Rth = −140/0,07 = −2 kΩ
    """
    secs = _sections(G_CIRCUIT, ("2", "3"))
    sec = _step(secs, "2. Adım")
    assert any(t.startswith("Kısa devre teli terminalleri birleştirir. Bu yüzden Düğüm 2 ve 3")
               for t in sec)
    assert "Kısıt (kısa devre teli): V₂ − V₃ = 0" in sec
    assert f"V₃ = 10 / ({MINUS}0,25) = {MINUS}40 V" in sec
    assert (f"Isc = I_R1 {MINUS} I_R2 {MINUS} I_R3 = 50 mA {MINUS} ({MINUS}20 mA) {MINUS} 0 mA "
            "= 70 mA") in sec
    assert "In = Isc = 70 mA" in sec
    assert f"Rth = {MINUS}2 kΩ" in sec
    assert "_port" not in _all_text(secs)


def test_test_source_route_shows_test_circuit_equations():
    """
    R1 = 20 Ω (1–0), G1 0 1 V(R1) −0,03 S, bağımsız kaynak yok, port 1–0.
      1 V test kaynağı: V₁ = 1 V, I_R1 = 1/20 = 50 mA (1 → 0),
      G1 = −0,03·1 = −30 mA (0 → 1 yönünde, yani 30 mA Düğüm 1'den çıkar)
      Düğüm 1'de KCL (kaynağın verdiği akım = çıkan akımlar): I_test = I_R1 − G1 = 50 + 30 = 80 mA
      Rth = 1 V / 80 mA = 12,5 Ω
    """
    secs = _sections("R1 1 0 20\nG1 0 1 V(R1) -0.03", ("1", "0"))
    sec = _step(secs, "2. Adım")
    assert "V_test kaynağı Düğüm 1 ile GND arasına bağlı olduğundan bu düğümün gerilimi doğrudan bilinir:" in sec
    assert "V₁ = 1 V" in sec
    assert f"G1 = {MINUS}0,03·V_R1 = {MINUS}0,03 · 1 V = {MINUS}30 mA" in sec
    assert f"I_test = I_R1 {MINUS} G1 = 50 mA {MINUS} ({MINUS}30 mA) = 80 mA" in sec
    assert "I_test = 80 mA" in sec
    assert "Rth = 12,5 Ω" in sec
    assert "_port" not in _all_text(secs)


def test_test_source_route_with_voltage_controlled_voltage_source():
    """
    R1 = 2 (1–2), R2 = 4 (2–0), E1 1 0 V(R2) 3, port 2–0 (bağımsız kaynak yok).
      1 V test: V₂ = 1, kısıt V₁ = 3·V_R2 = 3·V₂ = 3 V
      I_R2 = 1/4 = 0,25 A (2 → 0), I_R1 = (3 − 1)/2 = 1 A (1 → 2, Düğüm 2'ye girer)
      I_test = I_R1 çıkan değil girer → I_test = −I_R1 + I_R2 = −1 + 0,25 = −0,75 A
      Rth = 1/(−0,75) = −1,333 Ω
    """
    sec = _step(_sections("R1 1 2 2\nR2 2 0 4\nE1 1 0 V(R2) 3", ("2", "0")), "2. Adım")
    assert "Kısıt (E1): V₁ = 3·V_R2" in sec
    assert f"I_test = {MINUS}I_R1 + I_R2 = {MINUS}1 A + 0,25 A = {MINUS}750 mA" in sec
    assert f"Rth = {MINUS}1,333 Ω" in sec


def test_test_source_route_with_non_ground_terminals_and_supernode():
    """
    R1 = 1 k (1–2), R2 = 2 k (2–0), G1 0 2 V(R2) 1 mS, R3 = 500 Ω (2–3), port 3 (+) – 1 (−).
      1 V test: süperdüğüm {1, 3}, kısıt V₃ − V₁ = 1.
        Süperdüğüm: (V₁ − V₂)/1000 + (V₃ − V₂)/500 = 0
        Düğüm 2:    (V₂ − V₁)/1000 + V₂/2000 + (V₂ − V₃)/500 − 0,001·V₂ = 0
        → V₂ = 0, V₁ = −2/3 V, V₃ = 1/3 V
      Düğüm 3'te KCL: I_R3 = (0 − 1/3)/500 = −666,7 µA (2 → 3 yönünde, yani Düğüm 3'e girer
        −666,7 µA) → I_test = −I_R3 = 666,7 µA → Rth = 1/(2/3000) = 1,5 kΩ
    """
    secs = _sections("R1 1 2 1000\nR2 2 0 2000\nG1 0 2 V(R2) 0.001\nR3 2 3 500", ("3", "1"))
    sec = _step(secs, "2. Adım")
    assert "Kısıt (V_test): V₃ − V₁ = 1" in sec
    assert "V₃ = V₁ + 1 = (−0,6667) + 1 = 333,3 mV".replace("−", MINUS) in sec
    assert f"I_test = {MINUS}I_R3 = {MINUS}({MINUS}666,7 µA) = 666,7 µA" in sec
    assert "Rth = 1,5 kΩ" in sec
    assert "_port" not in _all_text(secs)


def test_norton_derives_in_once_in_the_in_step():
    """G1 devresi, Norton: türetme In adımında; Rn adımı tekrar etmez, In adımına gönderir."""
    secs = _sections(G_CIRCUIT, method="NORTON")
    s_in = _step(secs, "1. Adım")
    s_rn = _step(secs, "2. Adım")
    assert f"Isc = G1 + I_R3 {MINUS} I_R4 = 8 mA + 4 mA {MINUS} 0 mA = 12 mA" in s_in
    assert "In = 12 mA" in s_in
    assert "Düğüm Denklemleri (KCL):" not in s_rn
    assert any("In adımında bu devrenin denklemleriyle bulundu" in t for t in s_rn)
    assert "In = Isc = 12 mA" in s_rn and "Rn = 20 kΩ" in s_rn


def test_ac_isc_route_sums_phasors_in_rectangular_form():
    """
    V1 = 10∠0° V, ω = 1000 rad/s, R1 = 1 k (1–2), C1 = 1 µF (2–0, Z = −j1000),
    G1 0 3 V(C1) 2 mS, R3 = 1 k (2–3), R4 = 4 k (3–0), port 3–0.
      Kısa devre (V₃ = 0): (V₂ − 10)/1000 + V₂/(−j1000) + V₂/1000 = 0 → (2 + j1)·V₂ = 10
        → V₂ = 10/(2 + j) = 4 − j2 V
      I_R3 = 4 − j2 mA, G1 = 0,002·(4 − j2) = 8 − j4 mA, I_R4 = 0
      Isc = 12 − j6 mA = 13,42∠−26,57° mA
    """
    sec = _step(_sections(
        "V1 1 0 SINE(0 10 159.15494309189535 0 0 0)\nR1 1 2 1000\nC1 2 0 1u\n"
        "G1 0 3 V(C1) 0.002\nR3 2 3 1000\nR4 3 0 4000",
        mode="AC_PHASOR", frequency=159.15494309189535), "2. Adım")
    assert (f"Isc = G1 + I_R3 {MINUS} I_R4 = (8 {MINUS} j4 mA) + (4 {MINUS} j2 mA) {MINUS} (0 mA) "
            f"= 12 {MINUS} j6 mA = 13,42∠{MINUS}26,57° mA") in sec
    assert f"In = Isc = 13,42∠{MINUS}26,57° mA" in sec


def test_unverified_derivation_falls_back_to_old_text(monkeypatch):
    """Kısa devreli devrenin düğüm gerilimi bozulursa denklemler doğrulanamaz → eski metin."""
    real = cs._solve_port_extras

    def tampered(*args, **kwargs):
        ex = real(*args, **kwargs)
        ex.sc_circuit.node_voltages["2"] *= 1.01
        return ex

    monkeypatch.setattr(cs, "_solve_port_extras", tampered)
    sec = _step(_sections(G_CIRCUIT), "2. Adım")
    assert any("Devre böyle yeniden çözüldüğünde telden Düğüm 3 → Düğüm 0 yönünde geçen akım:"
               in t for t in sec)
    assert not any(t.startswith("Isc = ") for t in sec)
    assert "Düğüm Denklemleri (KCL):" not in sec
    assert "In = Isc = 12 mA" in sec and "Rth = 20 kΩ" in sec


@pytest.mark.parametrize("method", ["THEVENIN", "NORTON", "SOURCE_TRANSFORM"])
@pytest.mark.parametrize("netlist,terminals", [
    (G_CIRCUIT, ("3", "0")),
    (G_CIRCUIT, ("2", "3")),
    ("V1 1 0 DC 10\nR1 1 2 1000\nE1 2 3 V(R2) 3\nR2 3 0 1000", ("3", "0")),
    ("V1 1 0 DC 10\nR1 1 2 1000\nR2 2 0 2000\nF1 0 3 I(R1) 2\nR3 3 0 1000", ("3", "0")),
    ("V1 1 0 DC 10\nR1 1 2 1000\nR2 2 0 2000\nH1 3 0 I(R1) 500\nR3 2 3 1000", ("3", "0")),
    ("R1 1 0 20\nG1 0 1 V(R1) -0.03", ("1", "0")),
])
def test_internal_helper_names_never_shown(method, netlist, terminals):
    text = _all_text(_sections(netlist, terminals, method))
    assert "Vsc_port" not in text and "Vtest_port" not in text
    assert "AC analizde sıfırlanır" not in text
