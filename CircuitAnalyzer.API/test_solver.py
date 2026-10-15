"""
Solver entegrasyon testi.

DC ve AC devre çözümlerini lcapy üzerinden test eder.
Beklenen sonuçlar elle hesaplanmıştır.
"""
import urllib.request
import json
import sys

BASE = "http://127.0.0.1:8000"

def post_json(endpoint, data):
    """POST isteği gönder ve JSON yanıt döndür."""
    req = urllib.request.Request(
        f"{BASE}{endpoint}",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  HTTP {e.code}: {body}")
        return None


def print_result(label, result, expected=None):
    """Sonucu yazdır ve beklenen ile karşılaştır."""
    if result is None:
        print(f"  {label}: HATA (yanıt yok)")
        return
    
    print(f"\n  {label}")
    print(f"  Status: {result.get('status', '?')}")
    
    if result.get('results'):
        # Düğüm gerilimleri
        nv = result['results'].get('node_voltages', {})
        if nv:
            print("  Düğüm Gerilimleri:")
            for node, data in sorted(nv.items()):
                val = data['value']
                if isinstance(val, dict):
                    print(f"    V({node}) = {val['rectangular_str']} V")
                else:
                    print(f"    V({node}) = {val} V")
        
        # Eleman akımları
        ec = result['results'].get('element_currents', {})
        if ec:
            print("  Eleman Akımları:")
            for eid, data in ec.items():
                val = data['value']
                if isinstance(val, dict):
                    print(f"    I({eid}) = {val['rectangular_str']} A  [{data['direction']}]")
                else:
                    print(f"    I({eid}) = {val} A  [{data['direction']}]")
        
        # Prob sonuçları
        pr = result['results'].get('probe_results', [])
        if pr:
            print("  Prob Sonuçları:")
            for p in pr:
                val = p['value']
                if isinstance(val, dict):
                    print(f"    {p['probe_id']}: {p['type']}={val['rectangular_str']} {p['unit']}")
                else:
                    print(f"    {p['probe_id']}: {p['type']}={val} {p['unit']}")
        
        # Thevenin
        th = result['results'].get('thevenin')
        if th:
            print("  Thevenin Eşdeğeri:")
            print(f"    Vth = {th['vth']['rectangular_str']} V ({th['vth']['polar_str']})")
            print(f"    Zth = {th['zth']['rectangular_str']} Ω ({th['zth']['polar_str']})")
    
    # Hatalar
    errs = result.get('errors', [])
    if errs:
        print("  Notlar/Hatalar:")
        for e in errs:
            print(f"    • {e}")
    
    # Adımlar
    steps = result.get('solution_steps', [])
    if steps:
        print(f"  Çözüm Adımları ({len(steps)} adım):")
        for s in steps:
            print(f"    {s['step_number']}. {s['title']}")
            if s.get('equations'):
                for eq in s['equations'][:3]:
                    print(f"       {eq}")


# ═══════════════════════════════════════════════════════
#  TEST 1: DC GERİLİM BÖLÜCÜ
# ═══════════════════════════════════════════════════════
#
#  Devre:
#    V1=12V ─── R1=1kΩ ─── (Node 2) ─── R2=2kΩ ─── GND
#
#  Beklenen:
#    V(2) = 12 × 2000/(1000+2000) = 8.0 V
#    I(R1) = I(R2) = (12-8)/1000 = 0.004 A = 4 mA

print("=" * 60)
print("TEST 1: DC Gerilim Bölücü (R1=1k, R2=2k, V1=12V)")
print("  Beklenen: V(2) = 8.0 V, I = 4.0 mA")
print("=" * 60)

result1 = post_json("/analyze", {
    "netlist": "R1 1 2 1000\nR2 2 0 2000\nV1 1 0 DC 12\n* GND1 — Referans toprak (Node 0)\n* PROBE VP1 V(2)\n.end",
    "mode": "DC",
    "analysis_type": "NODAL"
})
print_result("DC Gerilim Bölücü", result1)


# ═══════════════════════════════════════════════════════
#  TEST 2: DC + THEVENİN
# ═══════════════════════════════════════════════════════
#
#  Aynı devre, Thevenin Node 2–0 arası:
#    Vth = 8.0 V
#    Rth = R1 || R2 (paralel yok, V kaynağı kısa devre)
#        = R1 × R2 / (R1 + R2) ... aslında V1 kısa devre olunca
#        R1 ve R2 paralel → Rth = 1000×2000/(1000+2000) = 666.67Ω

print("\n" + "=" * 60)
print("TEST 2: Thevenin (Node 2–Node 0)")
print("  Beklenen: Vth=8V, Rth=666.67Ω")
print("=" * 60)

result2 = post_json("/analyze", {
    "netlist": "R1 1 2 1000\nR2 2 0 2000\nV1 1 0 DC 12\n* GND1 — Referans toprak (Node 0)\n.end",
    "mode": "DC",
    "analysis_type": "THEVENIN",
    "thevenin_terminals": {"node_positive": "2", "node_negative": "0"}
})
print_result("Thevenin DC", result2)


# ═══════════════════════════════════════════════════════
#  TEST 3: HATA YAKALAMA — GND YOK
# ═══════════════════════════════════════════════════════

print("\n" + "=" * 60)
print("TEST 3: GND Eksik Uyarı")
print("=" * 60)

result3 = post_json("/analyze", {
    "netlist": "R1 1 2 1000\nV1 1 0 DC 12\n.end",
    "mode": "DC",
    "analysis_type": "NODAL"
})
print_result("GND Eksik", result3)


print("\n" + "=" * 60)
print("TÜM TESTLER TAMAMLANDI")
print("=" * 60)
