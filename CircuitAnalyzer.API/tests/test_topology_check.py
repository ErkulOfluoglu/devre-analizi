"""
Çözümden önce yapı denetimi (solver/topology_check.py).

Hatalar (tek çözüm yok), elemanların adıyla:
  a) iki ucu aynı düğümde gerilim kaynağı,  b) yalnızca gerilim kaynaklarından halka
  (DC'de bobin tel sayılır),  c) GND'ye bağlı olmayan bölüm (seri akım kaynakları dahil).
Uyarı: bir ucu hiçbir yere bağlı olmayan eleman ("⚠", durum "warning").

Engelleme yalnızca hata KESİN olduğunda (R, L, C ve bağımsız kaynaklar). Bağımlı kaynaklı,
transformatörlü vb. devreler çözümden önce ENGELLENMEZ.
"""

import pytest

from models.request import AnalysisMode, AnalysisType
from parser.netlist_parser import parse_netlist
from solver.circuit_solver import topology_gate
from solver.error_text import english_leak
from solver.topology_check import (
    blocking_reason, can_block, dangling_warnings, fault_reasons, find_faults,
)

GND = "\n* GND1 — Referans toprak (Node 0)"


def _post(client, netlist, mode="DC", analysis_type="NODAL", **extra):
    body = {"netlist": netlist + GND, "mode": mode, "analysis_type": analysis_type, **extra}
    if mode != "DC" and "frequency" not in body:
        body["frequency"] = 50
    return client.post("/analyze", json=body)


def _p(netlist):
    return parse_netlist(netlist + GND)


# ───────────── a) kısa devre edilmiş gerilim kaynağı ─────────────

def test_shorted_voltage_source_names_the_source(client):
    r = _post(client, "V1 1 1 DC 5\nR1 1 0 100")
    assert r.status_code == 422
    d = r.json()["detail"]
    assert "V1'in iki ucu aynı düğüme (Düğüm 1) bağlı (kısa devre edilmiş)" in d
    assert "Ne yapabilirsiniz:" in d
    assert english_leak(d) is None


def test_shorted_source_on_ground_node_says_gnd(client):
    r = _post(client, "V1 1 0 DC 5\nR1 1 0 100\nV2 0 0 DC 3")
    assert r.status_code == 422
    assert "V2'nin iki ucu aynı düğüme (GND) bağlı" in r.json()["detail"]


# ───────────── b) yalnızca gerilim kaynaklarından halka ─────────────

def test_two_voltage_sources_in_parallel(client):
    r = _post(client, "V1 1 0 DC 5\nV2 1 0 DC 3\nR1 1 0 100")
    assert r.status_code == 422
    d = r.json()["detail"]
    assert "V1 ve V2 gerilim kaynakları doğrudan paralel bağlı" in d
    assert "Ne yapabilirsiniz:" in d


def test_loop_of_three_voltage_sources(client):
    r = _post(client, "V1 1 0 DC 5\nV2 1 2 DC 3\nV3 2 0 DC 2\nR1 1 0 100")
    assert r.status_code == 422
    assert "V1, V2 ve V3 gerilim kaynakları, arada direnç olmadan kapalı bir halka" in r.json()["detail"]


def test_inductor_is_a_wire_in_dc_but_not_in_ac():
    net = "{v1} 1 0 {a}\nL1 1 2 0.01\n{v2} 2 0 {b}\nR1 1 0 100"
    dc = _p(net.format(v1="V1", a="DC 5", v2="V2", b="DC 5"))
    faults = find_faults(dc, True)
    assert len(faults) == 1 and faults[0].kind == "vloop"
    assert set(faults[0].elements) == {"V1", "V2", "L1"}
    assert "DC'de tel sayılan L1 bobini" in faults[0].problem
    assert "Kaynağı AC yapın" in " ".join(faults[0].hints)

    ac = _p(net.format(v1="VAC1", a="AC_PHASOR(5, 0)", v2="VAC2", b="AC_PHASOR(5, 0)"))
    assert find_faults(ac, False) == []


def test_ac_circuit_with_inductor_between_voltage_sources_still_solves(client):
    r = _post(client, "VAC1 1 0 AC_PHASOR(5, 0)\nL1 1 2 0.01\nVAC2 2 0 AC_PHASOR(3, 0)\nR1 1 0 100",
              mode="AC_PHASOR")
    assert r.status_code == 200


def test_dc_steady_state_message_still_comes_first(client):
    # Bobinle kapanan kaynak halkası: mevcut, daha özel DC mesajı korunur
    r = _post(client, "V1 1 0 DC 5\nL1 1 2 0.01\nV2 2 0 DC 5\nR1 1 0 100")
    assert r.status_code == 422
    assert "DC kararlı hâli yok" in r.json()["detail"]


# ───────────── c) GND'ye bağlı olmayan bölüm ─────────────

def test_series_current_sources_name_both_sources_and_the_middle_node(client):
    r = _post(client, "I1 0 1 DC 0.01\nI2 1 2 DC 0.01\nR1 2 0 100")
    # düğüm 1'i yalnızca iki akım kaynağı tutuyor
    assert r.status_code == 422
    d = r.json()["detail"]
    assert "Düğüm 1, yalnızca I1 ve I2 akım kaynakları arasında kalmış" in d
    assert "seri bağlı" in d and "Ne yapabilirsiniz:" in d


def test_series_current_sources_with_a_resistor_in_the_middle_still_solve(client):
    r = _post(client, "I1 0 1 DC 0.01\nI2 1 2 DC 0.01\nR1 2 0 100\nR3 1 0 50")
    assert r.status_code == 200
    assert r.json()["results"]["node_voltages"]["2"]["value"] == pytest.approx(1.0)


def test_floating_subcircuit_is_named(client):
    r = _post(client, "V1 1 0 DC 5\nR1 1 0 100\nR2 3 4 100\nR3 4 3 50")
    assert r.status_code == 422
    d = r.json()["detail"]
    assert "R2 ve R3 elemanları (Düğüm 3, 4) devrenin geri kalanına hiçbir yoldan bağlı değil" in d


def test_part_attached_only_through_a_current_source(client):
    r = _post(client, "V1 1 0 DC 5\nR1 1 0 100\nI1 0 2 DC 0.01\nR2 2 3 100")
    assert r.status_code == 422
    d = r.json()["detail"]
    assert "R2 elemanı (Düğüm 2, 3) GND'ye yalnızca I1 akım kaynağı üzerinden bağlı" in d
    assert "paralel bir direnç" in d


def test_capacitor_only_connection_is_not_blocked_in_dc_or_ac(client):
    """DC'de kondansatör açıktır ama çözücü bu bölümü 'akım yok' kararlı hâliyle çözer: engellenmez."""
    net = "{v} 1 0 {a}\nR1 1 2 100\nR2 2 0 100\nC1 2 3 0.001\nR3 3 4 100"
    dc = _post(client, net.format(v="V1", a="DC 5"))
    assert dc.status_code == 200
    ac = _post(client, net.format(v="VAC1", a="AC_PHASOR(5, 0)"), mode="AC_PHASOR")
    assert ac.status_code == 200


def test_fault_text_has_no_english_and_no_jargon():
    for net in ("V1 1 1 DC 5\nR1 1 0 100", "V1 1 0 DC 5\nV2 1 0 DC 3\nR1 1 0 100",
                "I1 0 1 DC 0.01\nI2 1 2 DC 0.01\nR1 2 0 100", "V1 1 0 DC 5\nR1 1 0 1\nR2 3 4 100"):
        text = blocking_reason(_p(net), True)
        assert text and english_leak(text) is None


# ───────────── engelleme yalnızca hata kesinken ─────────────

def test_blocked_circuit_never_reaches_the_solver(client, monkeypatch):
    import main

    def boom(*a, **k):
        raise AssertionError("çözücü çağrılmamalıydı")
    monkeypatch.setattr(main, "solve_circuit", boom)
    r = _post(client, "V1 1 0 DC 5\nV2 1 0 DC 3\nR1 1 0 100")
    assert r.status_code == 422


DEPENDENT_WITH_PARALLEL_SOURCES = (
    "V1 1 0 DC 5\nV2 1 0 DC 3\nR1 1 0 100\nE1 2 0 V(R1) 2\nR2 2 0 100")


def test_circuit_with_dependent_source_is_never_blocked_before_solving():
    parsed = _p(DEPENDENT_WITH_PARALLEL_SOURCES)
    assert not can_block(parsed, True)
    assert blocking_reason(parsed, True) is None
    reason, _ = topology_gate(parsed, AnalysisMode.DC, AnalysisType.NODAL)
    assert reason is None


def test_dependent_circuit_singular_in_solver_gets_the_specific_diagnosis(client):
    r = _post(client, DEPENDENT_WITH_PARALLEL_SOURCES)
    assert r.status_code == 422
    d = r.json()["detail"]
    assert "V1 ve V2 gerilim kaynakları doğrudan paralel bağlı" in d     # tanı, genel listenin yerine
    assert "Olası nedenler" not in d


def test_unexplained_singular_dependent_circuit_keeps_the_generic_list(client):
    # Tek çevrede kazanç dirençleri tam götürüyor: yapı hatası yok, genel liste korunur
    r = _post(client, "V1 1 0 DC 10\nR1 1 2 1000\nE1 2 3 V(R1) 1\nR2 3 0 1000")
    if r.status_code == 422:
        assert "Olası nedenler" in r.json()["detail"] or "kararlı hâli yok" in r.json()["detail"]


@pytest.mark.parametrize("net", [
    "V1 1 0 DC 5\nR1 1 2 100\nT1 2 0 3 4 IDEAL 2\nR2 3 4 100\nV2 5 5 DC 1",   # transformatör
])
def test_transformer_circuit_is_not_blocked(net):
    assert blocking_reason(_p(net), True) is None


def test_circuit_without_a_nonzero_source_is_left_alone():
    # Kaynaksız devreyi çözücü 0 bulur; bunu reddetmeyiz
    assert blocking_reason(_p("R1 1 2 100\nR2 3 0 100"), True) is None


def test_self_looped_passive_element_makes_the_verdict_uncertain():
    assert blocking_reason(_p("V1 1 0 DC 5\nR1 1 0 100\nL2 3 3 0.01\nR3 4 5 1"), True) is None


def test_switches_use_the_position_after_t0():
    net = "V1 1 0 DC 5\nS1 1 2 NO\nV2 2 0 DC 3\nR1 1 0 100"
    parsed = _p(net)
    # t > 0'da S1 kapalı: V1 ve V2 paralel
    reason, _ = topology_gate(parsed, AnalysisMode.DC, AnalysisType.NODAL)
    assert reason and "V1 ve V2 gerilim kaynakları doğrudan paralel" in reason
    # Geçici durumda t < 0 ve t > 0 ayrı çözülür: önceden engellenmez
    reason, _ = topology_gate(parsed, AnalysisMode.DC, AnalysisType.TRANSIENT)
    assert reason is None


def test_mixed_dc_and_ac_sources_are_not_blocked():
    parsed = _p("V1 1 0 DC 5\nVAC1 2 3 AC_PHASOR(5, 0)\nR1 1 0 100\nR2 2 0 100")
    assert not can_block(parsed, False)
    assert not can_block(parsed, True)


# ───────────── uyarı: bir ucu boşta kalan eleman ─────────────

def test_dangling_end_gives_a_warning_and_still_solves(client):
    r = _post(client, "V1 1 0 DC 5\nR1 1 2 100\nR2 2 0 100\nR3 2 3 100")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "warning"
    assert ("⚠ R3'ün bir ucu hiçbir yere bağlı değil (Düğüm 3); bu eleman akım taşımaz. "
            "Bir tel eksik olabilir.") in body["warnings"]
    assert body["results"]["node_voltages"]["2"]["value"] == pytest.approx(2.5)   # sonuç değişmedi


def test_dangling_warning_uses_the_right_turkish_suffix():
    texts = dangling_warnings(_p("V1 1 0 DC 5\nR1 1 2 100\nR2 2 0 100\nC1 2 3 0.001\n"
                                 "L1 2 4 0.01\nI1 0 5 DC 0.001\nR5 5 0 10"))
    joined = "\n".join(texts)
    assert "C1'in bir ucu" in joined and "L1'in bir ucu" in joined


def test_no_dangling_warning_for_a_healthy_circuit(client):
    r = _post(client, "V1 1 0 DC 5\nR1 1 2 100\nR2 2 0 100")
    assert r.status_code == 200
    assert r.json()["status"] == "success" and r.json()["warnings"] == []


def test_selected_thevenin_terminals_are_not_warned_about(client):
    net = "V1 1 0 DC 10\nR1 1 2 1000\nR2 2 3 1000"
    r = _post(client, net, analysis_type="THEVENIN", thevenin_terminals={"node_positive": "3", "node_negative": "0"})
    assert r.status_code == 200
    assert not any("hiçbir yere bağlı değil" in w for w in r.json()["warnings"])
    # terminal seçilmezse aynı devrede uyarı çıkar
    r2 = _post(client, net)
    assert any("R2'nin bir ucu hiçbir yere bağlı değil" in w for w in r2.json()["warnings"])


def test_probe_node_is_not_warned_about(client):
    r = _post(client, "V1 1 0 DC 10\nR1 1 2 1000\nR2 2 3 1000\n* PROBE VP1 V(3)")
    assert r.status_code == 200
    assert not any("hiçbir yere bağlı değil" in w for w in r.json()["warnings"])


def test_open_transformer_secondary_is_not_warned_about(client):
    r = _post(client, "VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nT1 2 0 3 4 IDEAL 2", mode="AC_PHASOR")
    assert r.status_code == 200
    assert not any("hiçbir yere bağlı değil" in w for w in r.json()["warnings"])


def test_switch_terminals_do_not_count_as_dangling():
    assert dangling_warnings(_p("V1 1 0 DC 5\nR1 1 2 100\nS1 2 3 NO\nR2 3 0 100")) == []
    assert dangling_warnings(_p("V1 1 0 DC 5\nS1 1 2 3 SPDT\nR1 2 0 100")) == []


def test_fully_isolated_element_gets_its_own_wording():
    texts = dangling_warnings(_p("V1 1 0 DC 5\nR1 1 0 100\nR9 7 8 100"))
    assert any("R9 hiçbir yere bağlı değil (iki ucu da boşta)" in t for t in texts)


# ───────────── çalışan devreler bozulmasın ─────────────

@pytest.mark.parametrize("net", [
    "V1 1 0 DC 12\nR1 1 2 1000\nR2 2 0 2000",
    "V1 1 0 DC 10\nR1 1 2 1000\nR2 2 0 2000\nI1 0 3 DC 0.002\nR3 2 3 1000",
    "V1 1 0 DC 12\nR1 1 2 1000\nR2 2 0 2000\nR3 2 3 1000\nV2 3 0 DC 6",
    "V1 1 0 DC 10\nR1 1 2 1000\nL1 2 3 0.01\nR2 2 0 2000\nR3 3 0 2000",
    "V1 1 0 DC 12\nR1 1 2 1000\nR2 2 0 4000\nC1 2 0 0.0001",
])
def test_working_circuits_are_not_blocked(client, net):
    assert blocking_reason(_p(net), True) is None
    assert find_faults(_p(net), True) == []
    r = _post(client, net)
    assert r.status_code == 200 and r.json()["status"] == "success"


def test_fault_reasons_skip_unwrapped_three_phase_expansion():
    p = _p("V1 1 0 DC 5\nV2 1 0 DC 3\nR1 1 0 100")
    assert fault_reasons(p, True)
    p.internal_names = True
    assert fault_reasons(p, True) is None
    assert dangling_warnings(p) == []
