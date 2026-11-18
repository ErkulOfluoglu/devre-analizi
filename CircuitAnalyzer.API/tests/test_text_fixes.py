"""
Anlatım metni düzeltmeleri (Fable denetimi, 1., 6. ve 7. tur).
"""

import pytest

GND = "\n* GND1 — Referans toprak (Node 0)"


def _texts(client, body):
    r = client.post("/analyze", json=body)
    assert r.status_code == 200, r.text
    out = []
    for sec in r.json()["results"]["explanation"]:
        out.append(sec["title"])
        out += [b.get("text", "") for b in sec["blocks"]]
    return out


def _delta(seq):
    return {"netlist": f"U1 1 2 3 0 3PH_SOURCE Y LINE 380 50 0 {seq} RMS\n"
                       "Y1 1 2 3 0 3PH_LOAD D Z(30,40) Z(30,40) Z(30,40)" + GND,
            "mode": "AC_PHASOR", "analysis_type": "THREE_PHASE", "value_display": "RMS"}


@pytest.mark.parametrize("seq, v_dir, i_dir", [("RST", "öndedir", "geridedir"),
                                               ("RTS", "geridedir", "öndedir")])
def test_thirty_degrees_has_a_direction(client, seq, v_dir, i_dir):
    t = " ".join(_texts(client, _delta(seq)))
    assert f"V_RN'den 30° {v_dir}" in t
    assert f"kol akımından 30° {i_dir}" in t
    assert "fazı 30° kayar" not in t


def test_delta_load_uses_its_own_symbol(client):
    t = " ".join(_texts(client, _delta("RST")))
    assert "U_kol = U_h" in t and "3 · U_kol · I_kol" in t
    assert "U_f = U_h." not in t        # U_f kaynağın faz gerilimi (U_h/√3) olarak kalır


def test_complex_power_sign_is_written_once():
    from explainer.narrative import _pq
    assert _pq(33.17, -57.46) == "33,17 W − j57,46 VAR"
    assert _pq(5.1, 3.846) == "5,1 W + j3,846 VAR"


def test_norton_finds_rn_before_using_it(client):
    t = _texts(client, {"netlist": "V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\nR3 2 3 1k\nR4 3 0 1k" + GND,
                        "mode": "DC", "analysis_type": "NORTON",
                        "thevenin_terminals": {"node_positive": "3", "node_negative": "0"}})
    rn = next(i for i, x in enumerate(t) if x.startswith("1. Adım — Rn"))
    i_n = next(i for i, x in enumerate(t) if x.startswith("2. Adım — In"))
    assert rn < i_n


def test_half_power_frequencies_are_marked_approximate(client):
    t = " ".join(_texts(client, {"netlist": "V1 1 0 AC_PHASOR(10, 0)\nR1 1 2 10\nL1 2 3 10m\nC1 3 0 1u" + GND,
                                 "mode": "AC_PHASOR", "analysis_type": "RESONANCE"}))
    assert "f₁ ≈ f₀ − BW/2" in t
    assert "bunların yaklaşığıdır" in t


def test_no_lcapy_name_in_student_text(client):
    for body in (_delta("RST"),
                 {"netlist": "V1 1 0 DC 12\nS1 1 2 NO\nR1 2 3 2k\nC1 3 0 1u" + GND,
                  "mode": "DC", "analysis_type": "TRANSIENT"}):
        r = client.post("/analyze", json=body)
        expl = " ".join(b.get("text", "") for s in r.json()["results"]["explanation"] for b in s["blocks"])
        steps = " ".join(s["description"] for s in r.json()["solution_steps"])
        assert "lcapy" not in expl and "lcapy" not in steps
