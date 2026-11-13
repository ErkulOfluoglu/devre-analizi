"""
CircuitAnalyzer API — Yapay zekânın çalıştığı yer (ekran kartı, işlemci, NPU)

Test edilen modül:
- llm/devices.py (classify_gpu, npu_info, auto_choice, route, placement_text)
- main.py (GET /llm/status cihaz seçenekleri, POST /llm/ask device, POST /llm/gpu/enable)
"""

import pytest

from llm import devices, ollama

GND = "* GND1 — Referans toprak (Node 0)"
DIVIDER = f"V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n{GND}"
ASK = {"netlist": DIVIDER, "mode": "DC", "analysis_type": "NODAL", "question": "V2 nedir?"}


def npu_ready(monkeypatch, models=("gemma4-it:e4b",)):
    monkeypatch.setattr(devices, "_probe_npu", lambda: devices.NpuInfo(True, None, "", list(models)))
    monkeypatch.setattr(devices, "_npu_cached", None)


def ollama_with(monkeypatch, models=("gemma4:e4b",)):
    monkeypatch.setattr("llm.ollama.get_status",
                        lambda: ollama.OllamaStatus(available=True, version="0.40", models=list(models)))


@pytest.mark.parametrize("names, kind", [
    (["NVIDIA GeForce RTX 2060"], "dedicated"),
    (["AMD Radeon RX 7600"], "dedicated"),
    (["Intel(R) Arc(TM) A770 Graphics"], "dedicated"),
    (["AMD Radeon(TM) 860M Graphics"], "integrated"),
    (["Intel(R) UHD Graphics 620"], "integrated"),
    (["Intel(R) UHD Graphics 620", "NVIDIA GeForce RTX 2060"], "dedicated"),  # hibrit laptop
    (["Microsoft Basic Display Adapter"], "none"),
    ([], "none"),
])
def test_classify_gpu(names, kind):
    assert devices.classify_gpu(names).kind == kind


def test_npu_model_matches_the_ollama_model(monkeypatch):
    npu_ready(monkeypatch, ["gemma4-it:e2b", "gemma4-it:e4b"])
    assert devices.npu_info("gemma4:e2b").model == "gemma4-it:e2b"
    assert devices.npu_info("gemma4:e4b").model == "gemma4-it:e4b"
    assert devices.npu_info("baska:model").model == "gemma4-it:e4b"   # tercih sırası


def test_npu_without_a_suitable_model_is_unavailable(monkeypatch):
    npu_ready(monkeypatch, ["llama3.2:1b"])
    info = devices.npu_info("gemma4:e4b")
    assert not info.available and "gemma4-it:e4b" in info.reason


def test_auto_choice_order(monkeypatch):
    ready = devices.NpuInfo(True, "gemma4-it:e4b")
    none = devices.NpuInfo(False, None, "yok")
    assert devices.auto_choice(ready, devices.GpuInfo("dedicated", "RTX")) == "npu"
    assert devices.auto_choice(none, devices.GpuInfo("dedicated", "RTX")) == "gpu"
    assert devices.auto_choice(none, devices.GpuInfo("integrated", "860M")) == "cpu"
    monkeypatch.setattr(devices, "_igpu_started", True)
    assert devices.auto_choice(none, devices.GpuInfo("integrated", "860M")) == "gpu"
    assert devices.auto_choice(none, devices.GpuInfo("none")) == "cpu"


def test_route(monkeypatch):
    r = devices.route("cpu", "gemma4:e4b")
    assert (r.where, r.base_url, r.options) == ("cpu", None, {"num_gpu": 0})
    assert devices.route("gpu", "gemma4:e4b").options == {}
    assert devices.route("auto", "gemma4:e4b").where == "ollama"      # NPU yok → Ollama karar verir
    assert devices.route("bilinmeyen", "gemma4:e4b").where == "ollama"
    with pytest.raises(devices.DeviceUnavailable, match="FastFlowLM"):
        devices.route("npu", "gemma4:e4b")
    npu_ready(monkeypatch)
    r = devices.route("auto", "gemma4:e4b")
    assert (r.where, r.base_url, r.model) == ("npu", devices.FLM_HOST, "gemma4-it:e4b")


def test_placement_text(monkeypatch):
    assert devices.placement_text(None) is None
    assert devices.placement_text([{"size": 100, "size_vram": 100}]) == "ekran kartında"
    assert devices.placement_text([{"size": 100, "size_vram": 0}]) == "işlemcide"
    assert devices.placement_text([{"size": 100, "size_vram": 63}]) == "%63 ekran kartında, kalanı işlemcide"
    monkeypatch.setattr(devices, "_last_where", "npu")
    monkeypatch.setattr(devices, "flm_running", lambda: True)
    assert devices.placement_text(None) == "NPU'da"


def test_status_lists_device_options(client, monkeypatch):
    ollama_with(monkeypatch)
    monkeypatch.setattr(devices, "_display_adapters", lambda: ["AMD Radeon(TM) 860M Graphics"])
    data = client.get("/llm/status").json()
    opts = {o["id"]: o for o in data["device_options"]}
    assert list(opts) == ["auto", "gpu", "cpu", "npu"]
    assert opts["gpu"]["available"] and "860M" in opts["gpu"]["note"]
    assert not opts["npu"]["available"] and "FastFlowLM" in opts["npu"]["note"]
    assert data["auto_device"] == "cpu"
    assert data["gpu_needs_restart"] is True


def test_status_auto_prefers_npu(client, monkeypatch):
    ollama_with(monkeypatch)
    npu_ready(monkeypatch)
    data = client.get("/llm/status").json()
    assert data["auto_device"] == "npu"
    assert "NPU" in data["device_options"][0]["note"]
    assert data["gpu_needs_restart"] is False


def test_ask_on_cpu_sends_num_gpu_zero(client, monkeypatch):
    ollama_with(monkeypatch)
    seen = {}

    def fake_chat(model, msgs, **kw):
        seen.update(model=model, **kw)
        return "V2 = 8 V."
    monkeypatch.setattr("llm.ollama.chat", fake_chat)
    data = client.post("/llm/ask", json=dict(ASK, device="cpu")).json()
    assert seen["options"] == {"num_gpu": 0} and "base" not in seen
    assert data["device"] == "cpu"


def test_ask_on_npu_uses_fastflowlm(client, monkeypatch):
    ollama_with(monkeypatch)
    npu_ready(monkeypatch)
    monkeypatch.setattr(devices, "ensure_flm", lambda model: True)
    seen = {}

    def fake_chat(model, msgs, **kw):
        seen.update(model=model, **kw)
        return "V2 = 8 V."
    monkeypatch.setattr("llm.ollama.chat", fake_chat)
    data = client.post("/llm/ask", json=dict(ASK, device="npu")).json()
    assert seen["model"] == "gemma4-it:e4b" and seen["base"] == devices.FLM_HOST
    assert data["device"] == "npu" and data["model"] == "gemma4-it:e4b"


def test_ask_npu_unavailable_is_a_clear_error(client, monkeypatch):
    ollama_with(monkeypatch)
    resp = client.post("/llm/ask", json=dict(ASK, device="npu"))
    assert resp.status_code == 400 and "FastFlowLM" in resp.json()["detail"]


def test_auto_falls_back_to_ollama_when_npu_does_not_start(client, monkeypatch):
    ollama_with(monkeypatch)
    npu_ready(monkeypatch)
    monkeypatch.setattr(devices, "ensure_flm", lambda model: False)
    monkeypatch.setattr("llm.ollama.chat", lambda model, msgs, **kw: "V2 = 8 V.")
    data = client.post("/llm/ask", json=ASK).json()
    assert data["device"] == "ollama" and data["model"] == "gemma4:e4b"


def test_gpu_enable_endpoint(client, monkeypatch):
    monkeypatch.setattr(devices, "restart_ollama_with_igpu", lambda: True)
    assert client.post("/llm/gpu/enable").json()["ok"] is True
    monkeypatch.setattr(devices, "restart_ollama_with_igpu", lambda: False)
    assert client.post("/llm/gpu/enable").json()["ok"] is False


def test_npu_works_while_ollama_is_closed(client, monkeypatch):
    """NPU seçiliyken Ollama kapalı olabilir; soru yine NPU'ya gider."""
    monkeypatch.setattr("llm.ollama.get_status", lambda: ollama.OllamaStatus(available=False))
    npu_ready(monkeypatch)
    monkeypatch.setattr(devices, "ensure_flm", lambda model: True)
    monkeypatch.setattr("llm.ollama.chat", lambda model, msgs, **kw: "V2 = 8 V.")
    data = client.post("/llm/ask", json=ASK).json()
    assert data["device"] == "npu"


def test_only_one_model_stays_in_memory(client, monkeypatch):
    """NPU'ya geçince Ollama'nın modeli boşaltılır; Ollama'ya geçince NPU sunucusu kapanır."""
    ollama_with(monkeypatch)
    npu_ready(monkeypatch)
    calls = []
    monkeypatch.setattr(devices, "ensure_flm", lambda model: True)
    monkeypatch.setattr("llm.ollama.unload_all", lambda: calls.append("ollama boşaltıldı"))
    monkeypatch.setattr(devices, "stop_flm", lambda: calls.append("NPU kapandı"))
    monkeypatch.setattr("llm.ollama.chat", lambda model, msgs, **kw: "V2 = 8 V.")
    client.post("/llm/ask", json=dict(ASK, device="npu"))
    client.post("/llm/ask", json=dict(ASK, device="cpu"))
    assert calls == ["ollama boşaltıldı", "NPU kapandı"]
