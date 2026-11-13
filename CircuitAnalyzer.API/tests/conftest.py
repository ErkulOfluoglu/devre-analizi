"""
Ortak pytest fixture'ları.

client  → FastAPI TestClient (sunucu başlatmadan uçtan uca test)
solve   → solve_circuit() için kısa yol: netlist metninden doğrudan çözüm
"""

import pytest
from fastapi.testclient import TestClient

from main import app
from models.request import AnalysisMode, AnalysisType, TheveninTerminals
from parser.netlist_parser import parse_netlist
from solver.circuit_solver import solve_circuit


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def no_real_ai_hardware(monkeypatch):
    """
    Testler bilgisayardaki gerçek NPU'ya, ekran kartına ya da çalışan Ollama'ya
    dokunmasın: varsayılan olarak NPU yok, ekran kartı yok, bellekte model yok.
    Bunları deneyen testler kendi değerlerini monkeypatch ile verir.
    """
    from llm import devices, ollama
    monkeypatch.setattr(devices, "_probe_npu",
                        lambda: devices.NpuInfo(False, None, "Bu bilgisayarda FastFlowLM kurulu değil."))
    monkeypatch.setattr(devices, "_npu_cached", None)
    monkeypatch.setattr(devices, "_display_adapters", lambda: [])
    monkeypatch.setattr(devices, "flm_running", lambda: False)
    monkeypatch.setattr(devices, "_igpu_started", False)
    monkeypatch.setattr(devices, "_last_where", None)
    monkeypatch.setattr(ollama, "running_models", lambda: None)


@pytest.fixture
def solve():
    def _solve(netlist, mode="DC", frequency=None, analysis_type="NODAL",
               terminals=None):
        parsed = parse_netlist(netlist)
        term = None
        if terminals is not None:
            pos, neg = terminals
            term = TheveninTerminals(node_positive=pos, node_negative=neg)
        return solve_circuit(
            parsed=parsed,
            mode=AnalysisMode(mode),
            frequency=frequency,
            analysis_type=AnalysisType(analysis_type),
            thevenin_terminals=term,
        )
    return _solve


def as_complex(value):
    """ComplexNumber modeli veya float → Python complex."""
    if isinstance(value, (int, float)):
        return complex(value, 0)
    return complex(value.real, value.imaginary)
