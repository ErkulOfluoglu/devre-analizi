"""
Faz 4a — DC diyot desteği.

Kitap örnekleri (Selek, Elektronik-1): s.54, 73, 82, 83, 87 ve ek durumlar
(Ge‖Si, özdeş paralel, seri iki yalıtım, eşik altı kaynak). Hem sayısal sonuçlar
hem anlatım metni kontrol edilir.
"""

import pytest

from llm.assistant import build_messages, describe_element, known_values
from models.request import AnalysisMode, AnalysisType
from parser.netlist_parser import ElementType, parse_netlist
from solver.circuit_solver import solve_circuit
from solver.diode import with_diode_states

GND = "\n* GND1 - Referans toprak"

P54 = "V1 1 0 DC 5\nD1 1 2 SI\nR1 2 0 1k"
P73 = "V1 1 0 DC 9\nD1 1 2 SI\nV2 2 3 DC 3\nR1 3 0 1k"
P82 = "V1 1 0 DC 9\nD1 1 2 SI\nD2 3 2 SI\nD3 3 4 GE\nR1 4 0 2k"
P83 = "V1 1 0 DC 12\nD3 1 2 SI\nD2 2 3 GE\nD1 3 2 SI\nR1 3 0 3k"
P87 = "V1 1 0 DC 4\nD1 2 1 GE\nR1 2 3 1k\nD2 3 4 GE\nR2 4 0 1k"
GESI = "V1 1 0 DC 5\nR1 1 2 1k\nD1 2 0 GE\nD2 2 0 SI"
PAR = "V1 1 0 DC 5\nR1 1 2 1k\nD1 2 0 SI\nD2 2 0 SI"
TWOOFF = "V1 1 0 DC 5\nD1 2 1 SI\nD2 3 2 SI\nR1 3 0 1k"
LOW = "V1 1 0 DC 0.5\nD1 1 2 SI\nR1 2 0 1k"


def analyze(client, netlist, analysis_type="NODAL", status=200, **extra):
    body = {"netlist": netlist + GND, "mode": "DC", "analysis_type": analysis_type}
    body.update(extra)
    r = client.post("/analyze", json=body)
    assert r.status_code == status, r.text
    return r.json()


def nv(d, node):
    return d["results"]["node_voltages"][node]["value"]


def cur(d, eid):
    return d["results"]["element_currents"][eid]["value"]


def diode(d, did):
    return next(x for x in d["diodes"] if x["id"] == did)


def text(d):
    parts = []
    for s in d["results"]["explanation"]:
        parts.append(s["title"])
        parts += [b["text"] for b in s["blocks"]]
    return "\n".join(parts)


def titles(d):
    return [s["title"] for s in d["results"]["explanation"]]


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


# ── Ayrıştırıcı ──────────────────────────────────────────

@pytest.mark.parametrize("model,vt", [("IDEAL", 0.0), ("si", 0.7), ("Ge", 0.3)])
def test_parse_models(model, vt):
    p = parse_netlist(f"V1 1 0 DC 5\nD1 1 2 {model}\nR1 2 0 1k" + GND)
    d = next(e for e in p.elements if e.id == "D1")
    assert d.element_type == ElementType.DIODE
    assert d.node_positive == "1" and d.node_negative == "2"
    assert d.params["model"] == model.upper()
    assert d.params["v_t"] == pytest.approx(vt)


@pytest.mark.parametrize("line,needle", [
    ("D1 1 2 XX", "tanınmadı"),
    ("D1 1 1 SI", "aynı düğüme"),
    ("D1 1 2", "Diyot satırı anlaşılamadı"),
])
def test_parse_rejects(client, line, needle):
    r = client.post("/analyze", json={"netlist": "V1 1 0 DC 5\nR1 2 0 1k\n" + line + GND,
                                      "mode": "DC", "analysis_type": "NODAL"})
    assert r.status_code == 400
    assert needle in r.json()["detail"]


def test_diode_cannot_be_control(client):
    r = client.post("/analyze", json={
        "netlist": "V1 1 0 DC 5\nD1 1 2 SI\nR1 2 0 1k\nE1 3 0 V(D1) 2\nR2 3 0 1k" + GND,
        "mode": "DC", "analysis_type": "NODAL"})
    assert r.status_code == 400
    assert "diyot (D1) olamaz" in r.json()["detail"]


def test_parse_only(client):
    r = client.post("/parse-only", json={"netlist": P54 + GND, "mode": "DC", "analysis_type": "NODAL"})
    assert r.status_code == 200
    els = {e["id"]: e for e in r.json()["elements"]}
    assert els["D1"]["type"] == "D"
    assert els["D1"]["params"]["v_t"] == pytest.approx(0.7)


# ── Kitap örnekleri ──────────────────────────────────────

def test_p54_single_si(client):
    d = analyze(client, P54)
    assert nv(d, "2") == pytest.approx(4.3)
    assert cur(d, "D1") == pytest.approx(4.3e-3)
    assert cur(d, "R1") == pytest.approx(4.3e-3)
    dd = diode(d, "D1")
    assert dd["state"] == "ON" and dd["model"] == "SI"
    assert dd["v_ak"] == pytest.approx(0.7) and dd["i"] == pytest.approx(4.3e-3)
    t = text(d)
    assert titles(d)[:4] == [
        "Devreyi Tanıyalım", "Diyotların Durumu", "Elektriksel Eşdeğer Devre", "Çevre Denklemi (KVL)"
    ]
    assert "Diyotlar: D1 (Si, V_T = 0,7 V)" in t
    assert "−5 + 0,7 + V_O = 0 ⇒ V_O = 4,3 V" in t
    assert "I = V_O / R1 = 4,3 V / 1 kΩ = 4,3 mA" in t
    assert "D1 (0,7 V)" in t
    assert "700 mV" not in t


def test_p73_diode_with_second_source(client):
    d = analyze(client, P73)
    assert nv(d, "3") == pytest.approx(5.3)
    assert cur(d, "R1") == pytest.approx(5.3e-3)
    assert diode(d, "D1")["state"] == "ON"
    assert "5,3" in text(d)


def test_p82_reverse_diode_blocks_loop(client):
    d = analyze(client, P82)
    for eid in ("D1", "D2", "D3", "R1"):
        assert cur(d, eid) == pytest.approx(0, abs=1e-12)
    assert diode(d, "D2")["state"] == "OFF"
    assert diode(d, "D2")["v_ak"] == pytest.approx(-8)
    t = text(d)
    assert "yalıtımda" in t
    assert "I = 0" in t


def test_p83_series_si_ge_with_off_diode(client):
    d = analyze(client, P83)
    assert nv(d, "3") == pytest.approx(11)
    assert cur(d, "R1") == pytest.approx(11 / 3000)
    assert diode(d, "D3")["state"] == "ON"
    assert diode(d, "D2")["state"] == "ON"
    d1 = diode(d, "D1")
    assert d1["state"] == "OFF" and d1["i"] == 0
    assert d1["v_ak"] == pytest.approx(-0.3)
    t = text(d)
    assert "−12 + 0,7 + 0,3 + V_O = 0 ⇒ V_O = 11 V" in t
    assert "3,667 mA" in t


def test_p87_reversed_ge_gives_zero(client):
    d = analyze(client, P87)
    assert diode(d, "D1")["state"] == "OFF"
    for eid in ("R1", "R2", "D1", "D2"):
        assert cur(d, eid) == pytest.approx(0, abs=1e-12)


# ── Ek durumlar ──────────────────────────────────────────

def test_ge_parallel_si_only_ge_conducts(client):
    d = analyze(client, GESI)
    assert diode(d, "D1")["state"] == "ON"
    assert diode(d, "D2")["state"] == "OFF"
    assert nv(d, "2") == pytest.approx(0.3)
    assert cur(d, "D1") == pytest.approx(4.7e-3)


def test_identical_parallel_split(client):
    d = analyze(client, PAR)
    assert cur(d, "D1") == pytest.approx(2.15e-3)
    assert cur(d, "D2") == pytest.approx(2.15e-3)
    assert any("özdeş" in m for m in d["errors"])


def test_two_off_in_series_floating_node(client):
    d = analyze(client, TWOOFF)
    assert "2" not in d["results"]["node_voltages"]
    assert all(x["state"] == "OFF" for x in d["diodes"])
    assert all(x["v_ak"] is None for x in d["diodes"])
    assert "Düğüm 2 boşta kalır" in text(d)


def test_below_threshold_is_off(client):
    d = analyze(client, LOW)
    assert diode(d, "D1")["state"] == "OFF"
    assert cur(d, "R1") == pytest.approx(0, abs=1e-12)


def test_mesh_on_equivalent(client):
    d = analyze(client, P83, "MESH")
    assert cur(d, "R1") == pytest.approx(11 / 3000)
    t = text(d)
    assert "I_D3 = −I₁ = 3,667 mA" in t
    assert "D3 kaynağının" not in t


def test_mesh_diode_voltage_symbol(client):
    import re
    # Tek çevreli devre: KVL ve çözüm satırlarında çıplak D1 yerine V_D1 yazılmalı
    d = analyze(client, P54, "MESH")
    mesh_secs = [s for s in d["results"]["explanation"]
                 if s["title"] in ("Çevre Denklemleri (KVL)", "Denklemlerin Çözümü")]
    assert len(mesh_secs) == 2
    mesh_text = "\n".join(b["text"] for s in mesh_secs for b in s["blocks"])
    assert "R1·I₁ = V_D1 − V1" in mesh_text
    assert "I₁ · (R1) = V_D1 − V1" in mesh_text
    assert not re.search(r"(?<!V_)D1\s*−", mesh_text)
    assert not re.search(r"−\s*D1\b", mesh_text)

    # Bağımlı kaynaklı çevre anlatımı (_kvl_terms yolu) da V_D1 kullanmalı
    dep_net = "V1 1 0 DC 5\nD1 1 2 SI\nR1 2 0 1k\nE1 3 0 V(R1) 2\nR2 3 0 1k"
    d_dep = analyze(client, dep_net, "MESH")
    kvl_sec = next(s for s in d_dep["results"]["explanation"] if s["title"] == "Çevre Denklemleri (KVL)")
    kvl_text = "\n".join(b["text"] for b in kvl_sec["blocks"])
    assert "V_D1" in kvl_text
    assert not re.search(r"(?<!V_)D1\s*−", kvl_text)
    assert not re.search(r"−\s*D1\b", kvl_text)


# ── Denge kontrolleri ve gizli isimler ───────────────────

@pytest.mark.parametrize("net", [P54, P73, P83, GESI, PAR])
def test_power_and_kcl_balance(client, net):
    d = analyze(client, net)
    pw = d["results"]["power"]["elements"]
    assert sum(p["active_power"] for p in pw.values()) == pytest.approx(0, abs=1e-9)
    for x in d["diodes"]:
        if x["state"] == "ON":
            assert pw[x["id"]]["active_power"] == pytest.approx(x["v_t"] * x["i"])
    sec = next(s for s in d["results"]["explanation"] if s["title"].startswith("Kontrol"))
    checks = [b["text"] for b in sec["blocks"] if b["kind"] == "check"]
    assert checks and all("✓" in c for c in checks)


@pytest.mark.parametrize("net", [P54, P82, P83, P87, GESI, PAR, TWOOFF])
@pytest.mark.parametrize("method", ["NODAL", "MESH"])
def test_no_hidden_names(client, net, method):
    d = analyze(client, net, method)
    assert not [s for s in strings(d) if "Vdiode" in s]


# ── Doğrusal yöntemler reddedilir ────────────────────────

REFUSED = [
    ("SUPERPOSITION", {}),
    ("THEVENIN", {"thevenin_terminals": {"node_positive": "2", "node_negative": "0"}}),
    ("NORTON", {"thevenin_terminals": {"node_positive": "2", "node_negative": "0"}}),
    ("MILLMAN", {}),
    ("SOURCE_TRANSFORM", {"thevenin_terminals": {"node_positive": "2", "node_negative": "0"}}),
    ("RECIPROCITY", {}),
    ("POWER", {}),
    ("TRANSIENT", {}),
    ("RESONANCE", {}),
]


@pytest.mark.parametrize("method,extra", REFUSED)
def test_linear_methods_fall_back_to_nodal(client, method, extra):
    d = analyze(client, P54, method, **extra)
    notes = [m for m in d["errors"] if "uygulanamadı" in m]
    assert notes and "diyot doğrusal olmayan bir elemandır" in notes[0]
    assert "Düğüm Gerilimleri yöntemiyle" in notes[0]
    assert nv(d, "2") == pytest.approx(4.3)
    assert "Bilinen Düğüm Gerilimleri" in titles(d)


# ── Kapsam dışı ──────────────────────────────────────────

def test_ac_mode_refused(client):
    r = client.post("/analyze", json={"netlist": P54 + GND, "mode": "AC_PHASOR",
                                      "frequency": 50, "analysis_type": "NODAL"})
    assert r.status_code == 422
    assert "yalnızca DC kaynaklarla" in r.json()["detail"]


@pytest.mark.parametrize("net,mode", [
    ("V1 1 0 AC_PHASOR(10, 0)\nD1 1 2 SI\nR1 2 0 1k", "DC"),
    ("V1 1 0 AC_PHASOR(10, 0)\nD1 1 2 SI\nR1 2 0 1k", "AC_PHASOR"),
    ("V1 1 0 SINE(0 10 50 0 0 0)\nD1 1 2 SI\nR1 2 0 1k", "AC_TIME"),
    ("V1 1 0 DC 5\nI1 0 2 AC_PHASOR(1m, 0)\nD1 1 2 SI\nR1 2 0 1k", "DC"),
])
def test_ac_source_refused(client, net, mode):
    body = {"netlist": net + GND, "mode": mode, "analysis_type": "NODAL"}
    if mode != "DC":
        body["frequency"] = 50
    r = client.post("/analyze", json=body)
    assert r.status_code == 422
    assert "doğrultucu ve kırpıcılar" in r.json()["detail"]


def test_no_consistent_state_refused(client):
    r = client.post("/analyze", json={"netlist": "V1 1 0 DC 5\nD1 1 0 SI" + GND, "mode": "DC",
                                      "analysis_type": "NODAL"})
    assert r.status_code == 422
    assert "durumu belirlenemedi" in r.json()["detail"]


def test_current_source_into_blocked_diode(client):
    r = client.post("/analyze", json={"netlist": "I1 0 1 DC 1m\nD1 2 1 SI\nR1 2 0 1k" + GND,
                                      "mode": "DC", "analysis_type": "NODAL"})
    assert r.status_code == 422
    assert "D1 yalıtımda kaldı ve açık devre sayıldı" in r.json()["detail"]


def test_switch_and_dependent_source_with_diode(client):
    d = analyze(client, "V1 1 0 DC 5\nS1 1 2 NO\nD1 2 3 SI\nR1 3 0 1k")
    assert nv(d, "3") == pytest.approx(4.3)
    assert titles(d)[0] == "Anahtar Konumu"
    d = analyze(client, "V1 1 0 DC 5\nD1 1 2 SI\nR1 2 0 1k\nE1 3 0 V(R1) 2\nR2 3 0 1k")
    assert nv(d, "3") == pytest.approx(8.6)


def test_probes_with_refused_method(client):
    d = analyze(client, P54, "THEVENIN",
                thevenin_terminals={"node_positive": "2", "node_negative": "0"},
                target_probes=[{"id": "IP1", "type": "I", "target": "D1"},
                               {"id": "VP1", "type": "V", "target": "2"}])
    probes = {p["probe_id"]: p["value"] for p in d["results"]["probe_results"]}
    assert probes == {"IP1": pytest.approx(4.3e-3), "VP1": pytest.approx(4.3)}
    assert not [s for s in strings(d) if "Vdiode" in s]
    d = analyze(client, TWOOFF, target_probes=[{"id": "VP1", "type": "V", "target": "2"}])
    assert any("VP1" in m and "boşta" in m for m in d["errors"])


def test_more_than_six_diodes_refused(client):
    lines = ["V1 1 0 DC 9"] + [f"D{i} {i} {i + 1} SI" for i in range(1, 8)] + ["R1 8 0 1k"]
    r = client.post("/analyze", json={"netlist": "\n".join(lines) + GND, "mode": "DC",
                                      "analysis_type": "NODAL"})
    assert r.status_code == 422
    assert "en fazla 6 diyot" in r.json()["detail"]


def test_six_diodes_solved(client):
    lines = ["V1 1 0 DC 9"] + [f"D{i} {i} {i + 1} SI" for i in range(1, 7)] + ["R1 7 0 1k"]
    d = analyze(client, "\n".join(lines))
    assert nv(d, "7") == pytest.approx(9 - 6 * 0.7)


# ── Alıştırma ve asistan ─────────────────────────────────

def test_practice_has_no_diode_or_total_power_question(client):
    d = analyze(client, P54)
    ids = [q["id"] for q in d["results"]["practice"]]
    assert "P_TOTAL" not in ids
    assert not any("D1" in q["label"] or "D1" in q["description"] for q in d["results"]["practice"])


def test_assistant_sees_diode_states():
    parsed = parse_netlist(P83 + GND)
    results, _, _ = solve_circuit(parsed=parsed, mode=AnalysisMode.DC, frequency=None,
                                  analysis_type=AnalysisType.NODAL, thevenin_terminals=None)
    assert results.diodes
    shown = with_diode_states(parse_netlist(P83 + GND), results.diodes)
    d3 = next(e for e in shown.elements if e.id == "D3")
    d1 = next(e for e in shown.elements if e.id == "D1")
    assert "İLETİMDE" in describe_element(d3) and "silisyum" in describe_element(d3)
    assert "YALITIMDA" in describe_element(d1)
    msgs = build_messages(shown, results, AnalysisType.NODAL, True, None, None,
                          "D1 neden yalıtımda?", [], False, [])
    system = msgs[0]["content"]
    assert "eşik gerilimi V_T = 0,7 V" in system
    assert "Diyot doğrusal olmayan bir elemandır" in system
    kv = known_values(shown, results, None, [])
    assert any(abs(v - 0.7) < 1e-12 for v in kv._typed.get("V", ()))


def test_practice_ask_does_not_leak_diode_state(client, monkeypatch):
    from llm import ollama
    seen = {}
    monkeypatch.setattr("llm.ollama.get_status",
                        lambda: ollama.OllamaStatus(available=True, version="0.9.0", models=["gemma3:4b"]))

    def fake_chat(model, msgs):
        seen["system"] = msgs[0]["content"]
        return "Önce diyotun durumunu belirleyin."
    monkeypatch.setattr("llm.ollama.chat", fake_chat)
    for net in (P54, P83):
        r = client.post("/llm/ask", json={"netlist": net + GND, "mode": "DC", "analysis_type": "NODAL",
                                          "question": "Nasıl başlarım?", "practice": True})
        assert r.status_code == 200, r.text
        assert "program çözdü" not in seen["system"]
        assert "4,3 mA" not in seen["system"]
    r = client.post("/llm/ask", json={"netlist": P54 + GND, "mode": "DC", "analysis_type": "NODAL",
                                      "question": "D1 iletimde mi?"})
    assert r.status_code == 200, r.text
    assert "program çözdü: İLETİMDE" in seen["system"]
