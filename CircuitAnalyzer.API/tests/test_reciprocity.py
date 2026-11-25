"""
Karşıtlık teoremi (analysis_type = "RECIPROCITY") testleri.

Beklenen değerler testte elle (devre formülleriyle) hesaplanır; çözücü çıktısı kopyalanmaz.

Ana örnek (DC): V1 1 0 DC 10, R1 1 2 2, R2 2 0 3, R3 2 3 4, R4 3 0 6, hedef R4
    R3 + R4 = 10;  R2 ∥ 10 = 30/13;  I_V1 = 10 / (2 + 30/13) = 65/28
    V₂ = 10 − 2·65/28 = 75/14;  I₁ = I_R4 = V₂ / 10 = 15/28 = 0,5357 A
    karşıt durum: kaynak R4 ile seri → I₂ = 15/28 (aynı);  aktarım direnci = 10 / (15/28) = 18,67 Ω
"""

import cmath
import math
import re

import pytest
from fastapi.testclient import TestClient

from explainer.formatting import polar
from main import app

client = TestClient(app)
GND = "\n* GND1 - Referans toprak"

MAIN = "V1 1 0 DC 10\nR1 1 2 2\nR2 2 0 3\nR3 2 3 4\nR4 3 0 6" + GND
I_EXACT = 15 / 28


def _post(net, mode="DC", target=None, freq=None, analysis="RECIPROCITY"):
    body = {"netlist": net, "mode": mode, "analysis_type": analysis}
    if target is not None:
        body["reciprocity_target"] = target
    if freq is not None:
        body["frequency"] = freq
    res = client.post("/analyze", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _blocks(d):
    return [(s["title"], b["kind"], b["text"]) for s in d["results"]["explanation"] for b in s["blocks"]]


def _text(d):
    return "\n".join(t for _, _, t in _blocks(d))


def _titles(d):
    return [s["title"] for s in d["results"]["explanation"]]


def _applicable(d):
    return "Karşıtlık Teoremi" in _titles(d) and "uygulanamadı" not in _text(d)


def _val(d, group, key):
    return d["results"][group][key]["value"]


# ── Elle doğrulanmış asimetrik DC devre ──

def test_hand_checked_dc():
    d = _post(MAIN, target="R4")
    assert _val(d, "element_currents", "R4") == pytest.approx(I_EXACT, rel=1e-6)
    assert _applicable(d)
    text = _text(d)
    assert "I₁ = 535,7 mA" in text
    assert "I₂ = 535,7 mA" in text
    assert "I₁ = I₂ ✓" in text
    assert "18,67 Ω" in text
    assert "aktarım direnci" in text.lower()
    titles = _titles(d)
    for t in ("Karşıtlık Teoremi", "1. Durum: Kaynak Kendi Yerinde",
              "2. Durum: Kaynak R4 Koluna Taşındı", "Sonuç: Karşıtlık Kontrolü"):
        assert t in titles
    assert not any("uygulanamadı" in m for m in d["errors"])


@pytest.mark.parametrize("src_line", ["V1 1 0 DC 10", "V1 0 1 DC 10"])
@pytest.mark.parametrize("r4_line", ["R4 3 0 6", "R4 0 3 6"])
def test_polarity_and_node_order_combinations(src_line, r4_line):
    net = f"{src_line}\nR1 1 2 2\nR2 2 0 3\nR3 2 3 4\n{r4_line}" + GND
    d = _post(net, target="R4")
    assert _applicable(d)
    text = _text(d)
    assert "I₁ = I₂ ✓" in text
    assert "535,7 mA" in text
    # İşaretler değişebilir ama iki durum aynı işareti taşır
    m1 = re.search(r"I₁ = (−?)535,7 mA", text)
    m2 = re.search(r"I₂ = (−?)535,7 mA", text)
    assert m1 and m2 and m1.group(1) == m2.group(1)
    # Ters kaynak + ters sıralı hedef: iki ters çevirme birbirini götürür
    flipped = (src_line.startswith("V1 0 1")) != (r4_line == "R4 0 3 6")
    assert (m1.group(1) == "−") == flipped


def test_independent_cross_check_voltage_form():
    # 2. durumu elle kur: V1 eski yerinde 0 V'luk kaynak, R4 ile seri (− ucu düğüm 3, + ucu yeni düğüm 4)
    case2 = ("V0 1 0 DC 0\nR1 1 2 2\nR2 2 0 3\nR3 2 3 4\nV1 4 3 DC 10\nR4 4 0 6" + GND)
    n = _post(case2, analysis="NODAL")
    i_v0 = _val(n, "element_currents", "V0")           # n+ → n−: 1 → 0, devreye giren akımın tersi
    i2_hand = -i_v0
    assert i2_hand == pytest.approx(I_EXACT, rel=1e-6)
    d = _post(MAIN, target="R4")
    assert f"I₂ = {_fmt_ma(i2_hand)}" in _text(d)


def _fmt_ma(a):
    return f"{abs(a) * 1000:.4g}".replace(".", ",") + " mA"


def test_independent_cross_check_current_form():
    net = "I1 0 1 DC 2m\nR1 1 0 1k\nR2 1 2 2k\nR3 2 0 3k\nR4 2 3 1k\nR5 3 0 4k" + GND
    # Elle: R4 + R5 = 5k; R3 ∥ 5k = 15/8 k; R2 + 15/8 = 31/8 k; R1 ∥ 31/8 = 31/39 k
    v1 = 2e-3 * (31 / 39) * 1e3
    v2 = v1 * (15 / 8) / (31 / 8)
    v3 = v2 * 4 / 5
    # 2. durum elle: kaynak R5'in uçlarına (3 → 0 yönünde), eski uçlar açık; V(0) − V(1)
    case2 = "R1 1 0 1k\nR2 1 2 2k\nR3 2 0 3k\nR4 2 3 1k\nR5 3 0 4k\nI2 3 0 DC 2m" + GND
    n = _post(case2, analysis="NODAL")
    u2_hand = 0 - _val(n, "node_voltages", "1")
    assert u2_hand == pytest.approx(v3, rel=1e-6)
    d = _post(net, target="R5")
    assert _val(d, "node_voltages", "3") == pytest.approx(v3, rel=1e-6)
    text = _text(d)
    assert "U₁ = U₂ ✓" in text
    assert f"U₂ = {_fmt_mv(u2_hand)}" in text


def _fmt_mv(v):
    return f"{abs(v) * 1000:.4g}".replace(".", ",") + " mV"


# ── Akım kaynağı (eş biçim) ──

CURR = "I1 0 1 DC 2m\nR1 1 0 1k\nR2 1 2 2k\nR3 2 0 3k\nR4 2 3 1k\nR5 3 0 4k" + GND


@pytest.mark.parametrize("src_line", ["I1 0 1 DC 2m", "I1 1 0 DC 2m"])
@pytest.mark.parametrize("r5_line", ["R5 3 0 4k", "R5 0 3 4k"])
def test_current_source_dual(src_line, r5_line):
    net = f"{src_line}\nR1 1 0 1k\nR2 1 2 2k\nR3 2 0 3k\nR4 2 3 1k\n{r5_line}" + GND
    d = _post(net)                       # varsayılan hedef: son R/L/C = R5
    assert _applicable(d)
    text = _text(d)
    assert "U₁ = U₂ ✓" in text
    assert "2. Durum: Kaynak R5 Koluna Taşındı" in _titles(d)
    assert "aktarım direnci" in text.lower()
    # |V3| = 2 mA · Z31 ; Z31 = (31/39 k)·(15/31)·(4/5) = 0,30769 kΩ  →  615,4 mV
    assert "615,4 mV" in text


# ── AC fazör ──

def test_ac_phasor_rlc():
    net = "VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nL1 2 3 50m\nC1 2 0 10u\nR2 3 0 50" + GND
    f = 100.0
    w = 2 * math.pi * f
    zl, zc = 1j * w * 0.05, 1 / (1j * w * 10e-6)
    zbranch = zl + 50
    zp = zbranch * zc / (zbranch + zc)
    v2 = 10 * zp / (100 + zp)
    i_hand = v2 / zbranch
    d = _post(net, mode="AC_PHASOR", target="R2", freq=f)
    assert _applicable(d)
    text = _text(d)
    assert f"I₁ = {polar(i_hand, 'A')}" in text
    assert f"I₂ = {polar(i_hand, 'A')}" in text
    assert "aktarım empedansı" in text.lower()
    zt = 10 / i_hand
    assert f"Z_t = {polar(zt, 'Ω')}" in text or polar(zt, "Ω") in text


def test_ac_phasor_current_source():
    net = "I1 0 1 AC_PHASOR(0.01, 0)\nR1 1 0 1k\nL1 1 2 100m\nC1 2 0 1u\nR2 2 3 500\nR3 3 0 2k" + GND
    d = _post(net, mode="AC_PHASOR", freq=200.0)
    assert _applicable(d)
    assert "U₁ = U₂ ✓" in _text(d)


# ── Varsayılan hedef ──

def test_default_target_is_last_passive_in_netlist_order():
    # Son satır kaynak: son R/L/C = R2 (kaynak değil)
    net = "R1 1 2 2\nR2 2 0 3\nR3 2 3 4\nR4 3 0 6\nV1 1 0 DC 10" + GND
    d = _post(net)
    assert "2. Durum: Kaynak R4 Koluna Taşındı" in _titles(d)
    d2 = _post(MAIN)
    assert "2. Durum: Kaynak R4 Koluna Taşındı" in _titles(d2)
    d3 = _post(MAIN, target="R3")
    assert "2. Durum: Kaynak R3 Koluna Taşındı" in _titles(d3)
    assert "I₁ = I₂ ✓" in _text(d3)


def test_empty_target_string_means_default():
    d = _post(MAIN, target="")
    assert "2. Durum: Kaynak R4 Koluna Taşındı" in _titles(d)


# ── Uygulanamayan durumlar: dürüst yedek + düğüm gerilimi anlatımı ──

def _assert_fallback(d, reason_part):
    text = _text(d)
    assert "Bu devrede karşıtlık teoremi uygulanamadı:" in text
    assert reason_part in text
    assert "“Düğüm Gerilimleri” yöntemini seçebilirsiniz" in text
    assert "Karşıtlık Teoremi" in _titles(d)
    assert "Düğüm Denklemleri (KCL)" in _titles(d)       # NODAL anlatımına döndü
    assert "I₁ = I₂" not in text
    assert any("Karşıtlık teoremi uygulanamadı" in m for m in d["errors"])


def test_two_independent_sources_inapplicable():
    net = "V1 1 0 DC 10\nR1 1 2 2\nR2 2 0 3\nV2 2 3 DC 5\nR3 3 0 4" + GND
    d = _post(net)
    _assert_fallback(d, "devrede iki bağımsız kaynak var (V1, V2); karşıtlık teoremi "
                        "tek kaynaklı devrelerde uygulanır.")


def test_dependent_source_inapplicable():
    net = "V1 1 0 DC 10\nR1 1 2 100\nR2 2 0 200\nE1 3 0 V(R2) 2\nR3 3 0 50" + GND
    d = _post(net)
    _assert_fallback(d, "devrede bağımlı (kontrollü) kaynak var (E1)")


def test_target_not_found_inapplicable():
    d = _post(MAIN, target="R9")
    _assert_fallback(d, "“R9” adlı bir eleman devrede yok")


def test_target_is_the_source_inapplicable():
    d = _post(MAIN, target="V1")
    _assert_fallback(d, "kaynağın kendisi (V1)")


def test_no_source_inapplicable():
    d = _post("R1 1 2 2\nR2 2 0 3" + GND)
    _assert_fallback(d, "devrede bağımsız kaynak yok")


def test_switch_inapplicable():
    net = "V1 1 0 DC 10\nR1 1 2 2\nS1 2 3 NO\nR2 3 0 3" + GND
    d = _post(net)
    _assert_fallback(d, "devrede anahtar var")


# ── Sonuçlar özgün devrenin sıradan çözümüdür ──

@pytest.mark.parametrize("net,mode,freq", [
    (MAIN, "DC", None),
    (CURR, "DC", None),
    ("VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nL1 2 3 50m\nC1 2 0 10u\nR2 3 0 50" + GND, "AC_PHASOR", 100.0),
])
def test_results_equal_nodal(net, mode, freq):
    rec = _post(net, mode=mode, freq=freq)
    nod = _post(net, mode=mode, freq=freq, analysis="NODAL")
    assert rec["results"]["node_voltages"] == nod["results"]["node_voltages"]
    assert rec["results"]["element_currents"] == nod["results"]["element_currents"]


def test_results_equal_nodal_when_inapplicable():
    net = "V1 1 0 DC 10\nR1 1 2 2\nR2 2 0 3\nV2 2 3 DC 5\nR3 3 0 4" + GND
    rec = _post(net)
    nod = _post(net, analysis="NODAL")
    assert rec["results"]["node_voltages"] == nod["results"]["node_voltages"]
    assert rec["results"]["element_currents"] == nod["results"]["element_currents"]


# ── Gizli düğüm ve yardımcı kaynak adları hiçbir yerde görünmez ──

HIDDEN = re.compile(r"rcp|Vrcp|Irp_", re.IGNORECASE)


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _strings(v)


@pytest.mark.parametrize("net,mode,freq,target", [
    (MAIN, "DC", None, "R4"),
    (CURR, "DC", None, None),
    ("VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nL1 2 3 50m\nC1 2 0 10u\nR2 3 0 50" + GND, "AC_PHASOR", 100.0, None),
])
def test_internal_names_stay_hidden(net, mode, freq, target):
    d = _post(net, mode=mode, freq=freq, target=target)
    assert _applicable(d)
    bad = [s for s in _strings(d) if HIDDEN.search(s)]
    assert not bad, bad
    assert set(d["results"]["node_voltages"]) <= {"0", "1", "2", "3"}
    assert not any(k.startswith(("V0", "Vrcp", "Irp")) for k in d["results"]["element_currents"])


# ── Enum / şema ──

def test_enum_value_accepted_but_hidden_from_schema():
    res = client.get("/openapi.json").json()
    assert "RECIPROCITY" not in res["components"]["schemas"]["AnalysisType"]["enum"]
    d = _post(MAIN)
    assert d["analysis_type"] == "RECIPROCITY"
