"""
Süperpozisyon anlatımı: her adımın eleman akımları ve bağımlı kaynaklı alt devre denklemleri.

Fable denetimi (7. tur): toplam bölümü I_R1′ gibi hiç hesaplanmamış katkıları
topluyordu; bağımlı kaynaklı devrede adımlar "alt devre çözücüyle çözüldü" deyip
denklem göstermiyordu.
"""

from fastapi.testclient import TestClient

from main import app

GND = "* GND1 — Referans toprak (Node 0)"
client = TestClient(app)


def _sections(netlist, mode="DC", freq=None):
    r = client.post("/analyze", json={"netlist": f"{netlist}\n{GND}", "mode": mode,
                                      "analysis_type": "SUPERPOSITION", "frequency": freq})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "success", d["errors"]
    return {s["title"]: [b["text"] for b in s["blocks"]] for s in d["results"]["explanation"]}


def test_each_step_computes_the_currents_that_are_added_up():
    # Örnek 6: V1 = 12 V, V2 = 6 V; R1 = 1k, R2 = 2k, R3 = 1k
    # 2. adım (yalnız V2): V₂″ = 2,4 V → I_R1″ = (0 − 2,4)/1k = −2,4 mA, I_R3″ = (2,4 − 6)/1k = −3,6 mA
    secs = _sections("V1 1 0 DC 12\nR1 1 2 1000\nR2 2 0 2000\nR3 2 3 1000\nV2 3 0 DC 6")
    step2 = next(v for k, v in secs.items() if k.startswith("2. Adım"))
    assert "I_R1″ = (V₁″ − V₂″)/R1 = (0 V − 2,4 V) / 1 kΩ = −2,4 mA" in step2
    assert "I_R3″ = (V₂″ − V₃″)/R3 = (2,4 V − 6 V) / 1 kΩ = −3,6 mA" in step2
    total = secs["Toplam: Katkıların Toplanması"]
    assert any(t.startswith("I_R1 = I_R1′ + I_R1″") for t in total)
    assert any(t.startswith("Güç katkılar gibi toplanamaz") for t in total)


def test_dependent_source_steps_show_their_equations():
    # G1 = 1 mS · V_R1 (bağımlı, sıfırlanmaz); V1 = 10 V, I1 = 2 mA
    # 1. adım: (V₂ − 10)/1 + V₂/2 − (10 − V₂)·1 = 0 (kΩ, mA) → 2,5·V₂ = 20 → 8 V
    # 2. adım: V₂/1 + V₂/2 − 2 + V₂ = 0 → 2,5·V₂ = 2 → 0,8 V
    secs = _sections("V1 1 0 DC 10\nR1 1 2 1000\nR2 2 0 2000\nG1 0 2 V(R1) 0.001\n"
                     "I1 0 2 DC 0.002")
    step1 = next(v for k, v in secs.items() if k.startswith("1. Adım"))
    step2 = next(v for k, v in secs.items() if k.startswith("2. Adım"))
    for step in (step1, step2):
        assert not any("alt devre çözücüyle çözüldü" in t for t in step)
    assert "V_R1 = V₁ − V₂ = −V₂ + 10" in step1
    assert "2,5·V₂ = 20" in step1 and "V₂ = 20 / 2,5 = 8 V" in step1
    assert "2,5·V₂ = 2" in step2 and "V₂ = 2 / 2,5 = 800 mV" in step2
    assert "I_G1″ = −800 µA  (G1 bağımlı kaynağının bu adımdaki akımı)" in step2
    # Genel açıklama paragrafı yalnız ilk adımda
    intro = next(t for t in step1 if t.startswith("Bağımlı kaynağın çıkışı bir kontrol"))
    assert intro not in step2
