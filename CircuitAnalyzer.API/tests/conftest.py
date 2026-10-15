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
