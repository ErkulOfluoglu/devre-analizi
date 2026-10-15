"""
Netlist Parser + API test betiği.

C# uygulamasının üreteceği gerçek bir Netlist ile
tüm parser formatlarını ve API endpoint'lerini test eder.
"""
import urllib.request
import json

BASE = "http://127.0.0.1:8000"

# ═══════════════════════════════════════════════════════
#  TEST 1: DC Devre (R1-R2 gerilim bölücü + GND + Probe)
# ═══════════════════════════════════════════════════════
print("=" * 60)
print("TEST 1: DC Gerilim Bölücü")
print("=" * 60)

dc_netlist = """* Circuit Analyzer — Otomatik Netlist
* Eleman sayısı: 3
* Düğüm sayısı: 3
* Referans: Node 0 (GND)
*
R1 1 2 1000
R2 2 0 2000
V1 1 0 DC 12
* GND1 — Referans toprak (Node 0)
*
* ═══ Ölçüm Hedefleri ═══
* PROBE VP1 V(2)
.end"""

payload = {
    "netlist": dc_netlist,
    "mode": "DC",
    "analysis_type": "NODAL"
}

req = urllib.request.Request(
    f"{BASE}/parse-only",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"}
)
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())
print(json.dumps(result, indent=2, ensure_ascii=False))

# ═══════════════════════════════════════════════════════
#  TEST 2: AC Fazör Devre (Empedans + AC_PHASOR + Probe)
# ═══════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("TEST 2: AC Fazör Devre")
print("=" * 60)

ac_netlist = """* Circuit Analyzer — Otomatik Netlist
*
R1 1 2 100
Z1 2 0 COMPLEX(50, 30)
VAC1 1 0 AC_PHASOR(10, 30)
* GND1 — Referans toprak (Node 0)
*
* ═══ Ölçüm Hedefleri ═══
* PROBE VP1 V(2)
* PROBE IP1 I(R1)
.end"""

payload2 = {
    "netlist": ac_netlist,
    "mode": "AC_PHASOR",
    "frequency": 50.0,
    "analysis_type": "NODAL"
}

req2 = urllib.request.Request(
    f"{BASE}/analyze",
    data=json.dumps(payload2).encode(),
    headers={"Content-Type": "application/json"}
)
resp2 = urllib.request.urlopen(req2)
result2 = json.loads(resp2.read())
print(json.dumps(result2, indent=2, ensure_ascii=False))

# ═══════════════════════════════════════════════════════
#  TEST 3: Karışık devre (tüm format türleri)
# ═══════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("TEST 3: Tüm Format Türleri")
print("=" * 60)

mixed_netlist = """R1 1 2 1000
C1 2 0 1e-05
L1 1 3 0.1
V1 1 0 DC 12
VAC1 3 0 SINE(0 10 50 0 0 30)
Z1 2 3 POLAR(58.31, 30.96)
* PROBE VP1 V(2)
.end"""

payload3 = {
    "netlist": mixed_netlist,
    "mode": "AC_TIME",
    "frequency": 50.0,
    "analysis_type": "NODAL"
}

req3 = urllib.request.Request(
    f"{BASE}/parse-only",
    data=json.dumps(payload3).encode(),
    headers={"Content-Type": "application/json"}
)
resp3 = urllib.request.urlopen(req3)
result3 = json.loads(resp3.read())
print(f"Eleman sayısı: {result3['element_count']}")
print(f"Düğüm sayısı: {result3['node_count']}")
print(f"GND var mı: {result3['has_ground']}")
print(f"Uyarılar: {result3['warnings']}")
print(f"\nlcapy Netlist:\n{result3['lcapy_netlist']}")
print(f"\nElemanlar:")
for e in result3['elements']:
    print(f"  {e['id']}: tip={e['type']}, düğümler=({e['node_positive']},{e['node_negative']}), değer={e['value']}")

print("\n✅ Tüm testler başarılı!")
