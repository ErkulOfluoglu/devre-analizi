"""
Faz 4b-1 — Zener diyot (DC, sabit V_Z modeli).

Sözleşmedeki regülatör, doğru polarma, karma (Si + Zener), çevre analizi,
ayrıştırıcı hataları, gizli kimlik sızıntısı ve asistan testleri.
"""

import pytest

from llm.assistant import build_messages, describe_element, known_values
from models.request import AnalysisMode, AnalysisType
from parser.netlist_parser import ElementType, parse_netlist
from solver.circuit_solver import solve_circuit
from solver.diode import with_diode_states

GND = "\n* GND1 - Referans toprak"


def reg_net(ry: str) -> str:
    return f"V1 1 0 DC 100\nRX 1 2 1k\nD1 0 2 ZENER VZ=20 IZM=30m\nRY 2 0 {ry}"


REG2 = "V1 1 0 DC 120\nRX 1 2 2k\nD1 0 2 ZENER VZ=30 IZM=40m\nRY 2 0 1k"
FWD = "V1 1 0 DC 5\nD1 1 2 ZENER VZ=5.1\nR1 2 0 1k"
SERIES_Z = "V1 1 0 DC 12\nR1 1 2 1k\nD1 0 2 ZENER VZ=5.1"
# Karma devre (Si + Zener):
#   V1 = 15 V, R1 = 1 kΩ (1→2), D1 = SI (anot 2, katot 3), D2 = ZENER VZ=5.3 (anot 0, katot 3),
#   R2 = 1 kΩ (3→0).
# El hesabı:
#   D1 ON ve D2 ZENER varsayımı:
#     V(3) = V_Z = 5,3 V, V(2) = V(3) + 0,7 = 6,0 V
#     I(R1) = (15 − 6) / 1k = 9 mA = I(D1) > 0 ✓ (D1 ON tutarlı)
#     I(R2) = 5,3 / 1k = 5,3 mA
#     Düğüm 3 KCL: I_Z(D2) = I(D1) − I(R2) = 9 − 5,3 = 3,7 mA > 0 ✓ (D2 ZENER tutarlı)
#     Güç: V1 verir 15·9m = 135 mW; R1: 81 mW, D1: 6,3 mW, D2: 19,61 mW, R2: 28,09 mW → toplam 135 mW ✓
MIXED = "V1 1 0 DC 15\nR1 1 2 1k\nD1 2 3 SI\nD2 0 3 ZENER VZ=5.3\nR2 3 0 1k"


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

@pytest.mark.parametrize("line,vz,izm", [
    ("D1 0 2 ZENER VZ=20 IZM=30m", 20.0, 0.03),
    ("D1 0 2 zener vz=5.1", 5.1, None),
    ("D1 0 2 Zener Izm=40m Vz=30", 30.0, 0.04),
])
def test_parse_zener_valid(line, vz, izm):
    p = parse_netlist(f"V1 1 0 DC 10\n{line}\nR1 1 2 1k" + GND)
    assert not p.errors
    d = next(e for e in p.elements if e.id == "D1")
    assert d.element_type == ElementType.DIODE
    assert d.params["model"] == "ZENER"
    assert d.params["v_z"] == pytest.approx(vz)
    assert d.params["v_f"] == pytest.approx(0.7)
    assert d.params["v_t"] == pytest.approx(0.7)
    assert d.params["i_zm"] == (None if izm is None else pytest.approx(izm))


@pytest.mark.parametrize("line,needle", [
    ("D1 0 2 ZENER", "VZ"),
    ("D1 0 2 ZENER IZM=30m", "VZ"),
    ("D1 0 2 ZENER VZ=0", "pozitif"),
    ("D1 0 2 ZENER VZ=-5", "pozitif"),
    ("D1 0 2 ZENER VZ=20 IZM=-10m", "pozitif"),
    ("D1 0 2 ZENER VZ=20 IZM=0", "pozitif"),
    ("D1 0 0 ZENER VZ=20", "aynı düğüme"),
    ("D1 0 2 ZENER VZ=20 FOO=1", "tanınmadı"),
])
def test_parse_zener_rejects(client, line, needle):
    r = client.post("/analyze", json={"netlist": f"V1 1 0 DC 10\nR1 1 2 1k\n{line}" + GND,
                                      "mode": "DC", "analysis_type": "NODAL"})
    assert r.status_code == 400
    assert needle in r.json()["detail"]


# ── Regülatör oraklları ──────────────────────────────────

def test_regulator_ry300_zener_active(client):
    d = analyze(client, reg_net("300"))
    assert d["status"] == "success"
    assert not any("⚠" in m for m in d["errors"] + d["warnings"])
    assert nv(d, "2") == pytest.approx(20.0)
    assert cur(d, "RX") == pytest.approx(0.08)
    assert cur(d, "RY") == pytest.approx(20.0 / 300.0)
    # element_currents anot → katot (0→2) yönünü korur; zener akımı katottan anoda olduğu için eksi
    assert d["results"]["element_currents"]["D1"]["direction"] == "0→2"
    assert cur(d, "D1") == pytest.approx(-40.0 / 3000.0)
    dd = diode(d, "D1")
    assert dd["model"] == "ZENER"
    assert dd["state"] == "ZENER"
    assert dd["vz"] == pytest.approx(20.0)
    assert dd["izm"] == pytest.approx(0.03)
    assert dd["v_ak"] == pytest.approx(-20.0)
    assert dd["i"] == pytest.approx(40.0 / 3000.0)
    # Güç dengesi ve zenerin çektiği güç P = V_Z · I_Z
    pw = d["results"]["power"]["elements"]
    assert sum(p["active_power"] for p in pw.values()) == pytest.approx(0, abs=1e-9)
    assert pw["D1"]["active_power"] == pytest.approx(20.0 * (40.0 / 3000.0))
    # Anlatım kontrolü
    t = text(d)
    assert "Zener diyotlar: D1 (V_Z = 20 V, I_ZM = 30 mA)." in t
    assert "D1 ters iletimde (zener bölgesi): yerine 20 V'luk kaynak konur (+ ucu katoda)" in t
    assert "I_Z ≤ I_ZM (30 mA) ✓" in t


def test_regulator_ry200_zener_off(client):
    d = analyze(client, reg_net("200"))
    assert d["status"] == "success"
    assert not any("⚠" in m for m in d["errors"] + d["warnings"])
    v2 = 100.0 * 200.0 / 1200.0
    assert nv(d, "2") == pytest.approx(v2)
    dd = diode(d, "D1")
    assert dd["state"] == "OFF"
    assert dd["i"] == 0.0
    assert dd["v_ak"] == pytest.approx(-v2)
    assert cur(d, "D1") == 0.0
    t = text(d)
    assert "ters polarmada ama V_Z'ye ulaşmıyor, yalıtımda" in t


def test_regulator_ry500_over_izm_warning(client):
    d = analyze(client, reg_net("500"))
    assert d["status"] == "warning"
    assert nv(d, "2") == pytest.approx(20.0)
    dd = diode(d, "D1")
    assert dd["state"] == "ZENER"
    assert dd["i"] == pytest.approx(0.04)
    expected_warn = (
        "⚠ D1: I_Z = 40 mA, I_ZM = 30 mA sınırını aşıyor; gerçekte zener aşırı akımdan zarar görür. "
        "Not: bazı ders kitapları bu durumu “zener yalıtımdadır” diye yorumlar."
    )
    assert expected_warn in d["errors"]
    t = text(d)
    assert "I_Z > I_ZM (30 mA) ✗" in t
    assert expected_warn in t


def test_regulator_second_oracle(client):
    d = analyze(client, REG2)
    assert d["status"] == "success"
    assert not any("⚠" in m for m in d["errors"] + d["warnings"])
    assert nv(d, "2") == pytest.approx(30.0)
    assert cur(d, "RX") == pytest.approx(0.045)
    assert cur(d, "RY") == pytest.approx(0.03)
    dd = diode(d, "D1")
    assert dd["state"] == "ZENER"
    assert dd["i"] == pytest.approx(0.015)


# ── Doğru polarma, tek çevre KVL, sınır durumu ve karma devre ──

def test_zener_forward_on(client):
    d = analyze(client, FWD)
    assert nv(d, "2") == pytest.approx(4.3)
    dd = diode(d, "D1")
    assert dd["model"] == "ZENER"
    assert dd["state"] == "ON"
    assert dd["vz"] == pytest.approx(5.1)
    assert dd["izm"] is None
    assert dd["v_ak"] == pytest.approx(0.7)
    assert dd["i"] == pytest.approx(4.3e-3)
    t = text(d)
    assert "Zener diyotlar: D1 (V_Z = 5,1 V)." in t
    assert "I_ZM" not in t


def test_zener_single_loop_kvl_breakdown(client):
    d = analyze(client, SERIES_Z)
    assert nv(d, "2") == pytest.approx(5.1)
    assert diode(d, "D1")["state"] == "ZENER"
    assert diode(d, "D1")["i"] == pytest.approx(6.9e-3)
    t = text(d)
    assert "Çevre Denklemi (KVL)" in t
    assert "6,9 mA" in t


def test_zener_exact_vz_tie_is_off(client):
    # Sınırda V_AK = −V_Z (−20 V): eşitlikte OFF seçilir
    d = analyze(client, "V1 1 0 DC 20\nR1 1 2 1k\nD1 0 2 ZENER VZ=20")
    assert diode(d, "D1")["state"] == "OFF"
    assert diode(d, "D1")["i"] == 0.0
    assert nv(d, "2") == pytest.approx(20.0)


def test_mixed_si_and_zener(client):
    d = analyze(client, MIXED)
    assert d["status"] == "success"
    assert nv(d, "3") == pytest.approx(5.3)
    assert nv(d, "2") == pytest.approx(6.0)
    assert cur(d, "R1") == pytest.approx(9e-3)
    assert cur(d, "R2") == pytest.approx(5.3e-3)
    d1 = diode(d, "D1")
    d2 = diode(d, "D2")
    assert d1["model"] == "SI" and d1["state"] == "ON"
    assert d1["vz"] is None and d1["izm"] is None
    assert d1["i"] == pytest.approx(9e-3)
    assert d2["model"] == "ZENER" and d2["state"] == "ZENER"
    assert d2["vz"] == pytest.approx(5.3) and d2["izm"] is None
    assert d2["i"] == pytest.approx(3.7e-3)
    assert d2["v_ak"] == pytest.approx(-5.3)
    pw = d["results"]["power"]["elements"]
    assert sum(p["active_power"] for p in pw.values()) == pytest.approx(0, abs=1e-9)
    assert pw["D1"]["active_power"] == pytest.approx(0.7 * 9e-3)
    assert pw["D2"]["active_power"] == pytest.approx(5.3 * 3.7e-3)
    t = text(d)
    assert "Diyotlar: D1 (Si, V_T = 0,7 V)." in t
    assert "Zener diyotlar: D2 (V_Z = 5,3 V)." in t


# ── Çevre analizi, gizli ad sızıntısı, yöntem kapıları, asistan ──

def test_zener_mesh_and_symbol(client):
    d = analyze(client, reg_net("300"), "MESH")
    assert nv(d, "2") == pytest.approx(20.0)
    assert diode(d, "D1")["i"] == pytest.approx(40.0 / 3000.0)
    mesh_secs = [s for s in d["results"]["explanation"]
                 if s["title"] in ("Çevre Denklemleri (KVL)", "Denklemlerin Çözümü")]
    assert mesh_secs
    mesh_text = "\n".join(b["text"] for s in mesh_secs for b in s["blocks"])
    assert "V_D1" in mesh_text
    assert "I_D1 (I_Z)" in text(d)


@pytest.mark.parametrize("net", [reg_net("300"), reg_net("200"), reg_net("500"), FWD, MIXED])
@pytest.mark.parametrize("method", ["NODAL", "MESH"])
def test_no_hidden_names_zener(client, net, method):
    d = analyze(client, net, method)
    assert not [s for s in strings(d) if "Vdiode" in s]


def test_zener_method_gate_and_ac_refused(client):
    d = analyze(client, reg_net("300"), "THEVENIN",
                thevenin_terminals={"node_positive": "2", "node_negative": "0"})
    assert any("uygulanamadı" in m for m in d["errors"])
    assert nv(d, "2") == pytest.approx(20.0)
    r = client.post("/analyze", json={"netlist": reg_net("300") + GND, "mode": "AC_PHASOR",
                                      "frequency": 50, "analysis_type": "NODAL"})
    assert r.status_code == 422
    assert "Dalga Şekli" in r.json()["detail"]


def test_assistant_describes_zener():
    parsed = parse_netlist(reg_net("300") + GND)
    results, _, _ = solve_circuit(parsed=parsed, mode=AnalysisMode.DC, frequency=None,
                                  analysis_type=AnalysisType.NODAL, thevenin_terminals=None)
    shown = with_diode_states(parse_netlist(reg_net("300") + GND), results.diodes)
    d1 = next(e for e in shown.elements if e.id == "D1")
    desc = describe_element(d1)
    assert "zener diyot" in desc and "V_Z = 20 V" in desc and "I_ZM = 30 mA" in desc
    assert "ZENER BÖLGESİ" in desc
    msgs = build_messages(shown, results, AnalysisType.NODAL, True, None, None,
                          "D1 neden zener bölgesinde?", [], False, [])
    assert "Zener diyot ters polarmada" in msgs[0]["content"]
    kv = known_values(shown, results, None, [])
    assert any(abs(v - 20.0) < 1e-12 for v in kv._typed.get("V", ()))
    assert any(abs(v - 0.03) < 1e-12 for v in kv._typed.get("A", ()))
