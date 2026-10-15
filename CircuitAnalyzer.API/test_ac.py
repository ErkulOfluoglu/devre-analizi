"""
AC Fazör Devre Testleri.

Elle hesaplanmış beklenen değerlerle lcapy çözücüyü doğrular.

TEST 4: RC Alçak Geçiren Filtre (AC)
  Devre: VAC(10∠0°, 50Hz) → R(100Ω) → C(100µF) → GND
  
  Zc = 1/(jωC) = 1/(j·2π·50·100e-6) = -j31.831Ω
  V(2) = 10 × Zc/(R+Zc) = 10 × (-j31.831)/(100-j31.831)
  |V(2)| = 10 × 31.831 / √(100²+31.831²) = 10 × 31.831/104.94 ≈ 3.033 V

TEST 5: RL Seri Devre (AC)  
  Devre: VAC(20∠45°, 60Hz) → R(50Ω) → L(100mH) → GND
  
  ZL = jωL = j·2π·60·0.1 = j37.699Ω
  I = V/(R+ZL) = 20∠45° / (50+j37.699)
  |Z| = √(50²+37.699²) = 62.62Ω
  |I| = 20/62.62 = 0.3194A
"""
import urllib.request
import json
import math
import cmath
import math

BASE = "http://127.0.0.1:8000"

def post_json(endpoint, data):
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


def check_close(label, actual, expected, tolerance=0.05):
    """Değerin beklenen aralıkta olduğunu kontrol et."""
    if actual is None:
        print(f"  ✕ {label}: değer yok!")
        return False
    
    diff = abs(actual - expected)
    rel = diff / max(abs(expected), 1e-10) if expected != 0 else diff
    ok = rel < tolerance
    symbol = "✓" if ok else "✕"
    print(f"  {symbol} {label}: {actual:.4f} (beklenen: {expected:.4f}, fark: {rel*100:.1f}%)")
    return ok


def get_node_voltage(result, node):
    """Düğüm gerilimini float veya complex olarak çıkar."""
    nv = result.get('results', {}).get('node_voltages', {}).get(node)
    if nv is None:
        return None
    val = nv.get('value')
    if isinstance(val, dict):
        return complex(val['real'], val['imaginary'])
    return float(val)


def get_element_current(result, elem_id):
    """Eleman akımını float veya complex olarak çıkar."""
    ec = result.get('results', {}).get('element_currents', {}).get(elem_id)
    if ec is None:
        return None
    val = ec.get('value')
    if isinstance(val, dict):
        return complex(val['real'], val['imaginary'])
    return float(val)


# ═══════════════════════════════════════════════════════
#  TEST 4: RC ALÇAK GEÇİREN FİLTRE (AC, 50Hz)
# ═══════════════════════════════════════════════════════
print("=" * 60)
print("TEST 4: RC Alçak Geçiren Filtre (AC)")
print("  VAC=10∠0° V, f=50Hz, R=100Ω, C=100µF")
print("=" * 60)

# Elle hesap:
f = 50.0
omega = 2 * math.pi * f
Zc = 1 / (1j * omega * 100e-6)  # = -j31.831Ω
V2_expected = 10 * Zc / (100 + Zc)
print(f"  Elle hesap: Zc = {Zc:.4f}")
print(f"  Elle hesap: V(2) = {V2_expected:.4f}")
print(f"  Elle hesap: |V(2)| = {abs(V2_expected):.4f} V")
print(f"  Elle hesap: ∠V(2) = {math.degrees(cmath.phase(V2_expected)):.4f}°")
import cmath

result4 = post_json("/analyze", {
    "netlist": "VAC1 1 0 AC_PHASOR(10, 0)\nR1 1 2 100\nC1 2 0 1e-04\n* GND1 — Referans toprak (Node 0)\n* PROBE VP1 V(2)\n.end",
    "mode": "AC_PHASOR",
    "frequency": 50.0,
    "analysis_type": "NODAL"
})

if result4:
    print(f"  Status: {result4['status']}")
    
    v2 = get_node_voltage(result4, "2")
    if v2 is not None:
        print(f"  lcapy V(2) = {v2}")
        check_close("|V(2)|", abs(v2), abs(V2_expected))
        check_close("∠V(2)", math.degrees(cmath.phase(v2)),
                     math.degrees(cmath.phase(V2_expected)), tolerance=0.1)
    
    i_r1 = get_element_current(result4, "R1")
    if i_r1 is not None:
        I_expected = 10 / (100 + Zc)
        check_close("|I(R1)|", abs(i_r1), abs(I_expected))
    
    # Hatalar
    for e in result4.get('errors', []):
        print(f"  Not: {e}")
    
    # Adım sayısı
    steps = result4.get('solution_steps', [])
    print(f"  Çözüm adımları: {len(steps)}")
    for s in steps:
        print(f"    {s['step_number']}. {s['title']}")
else:
    print("  ✕ Yanıt alınamadı!")


# ═══════════════════════════════════════════════════════
#  TEST 5: RL SERİ DEVRE (AC, 60Hz)
# ═══════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("TEST 5: RL Seri Devre (AC)")
print("  VAC=20∠45° V, f=60Hz, R=50Ω, L=100mH")
print("=" * 60)

f5 = 60.0
omega5 = 2 * math.pi * f5
ZL = 1j * omega5 * 0.1  # = j37.699Ω
V_src = 20 * cmath.exp(1j * math.radians(45))  # 20∠45°
I_expected5 = V_src / (50 + ZL)
V2_expected5 = I_expected5 * ZL  # Bobin üzerindeki gerilim (Node 2)

# Ama devremizde V(2) = VAC - I*R = Node 2 gerilimi
# Devre: VAC(1→0), R(1→2), L(2→0) → V(2) = I × ZL
print(f"  Elle hesap: ZL = {ZL:.4f}")
print(f"  Elle hesap: V_kaynak = {V_src:.4f}")
print(f"  Elle hesap: I = {I_expected5:.4f}")
print(f"  Elle hesap: |I| = {abs(I_expected5):.4f} A")
print(f"  Elle hesap: V(2) = I×ZL = {V2_expected5:.4f}")
print(f"  Elle hesap: |V(2)| = {abs(V2_expected5):.4f} V")

result5 = post_json("/analyze", {
    "netlist": "VAC1 1 0 AC_PHASOR(20, 45)\nR1 1 2 50\nL1 2 0 0.1\n* GND1 — Referans toprak (Node 0)\n* PROBE VP1 V(2)\n* PROBE IP1 I(R1)\n.end",
    "mode": "AC_PHASOR",
    "frequency": 60.0,
    "analysis_type": "NODAL"
})

if result5:
    print(f"  Status: {result5['status']}")
    
    v2 = get_node_voltage(result5, "2")
    if v2 is not None:
        print(f"  lcapy V(2) = {v2}")
        check_close("|V(2)|", abs(v2), abs(V2_expected5))
    
    i_r1 = get_element_current(result5, "R1")
    if i_r1 is not None:
        print(f"  lcapy I(R1) = {i_r1}")
        check_close("|I(R1)|", abs(i_r1), abs(I_expected5))
    
    # Prob sonuçları
    probes = result5.get('results', {}).get('probe_results', [])
    if probes:
        print(f"  Prob sonuçları:")
        for p in probes:
            val = p['value']
            if isinstance(val, dict):
                print(f"    {p['probe_id']}: {p['type']}={val['rectangular_str']} ({val['polar_str']})")
            else:
                print(f"    {p['probe_id']}: {p['type']}={val}")
    
    for e in result5.get('errors', []):
        print(f"  Not: {e}")
else:
    print("  ✕ Yanıt alınamadı!")


# ═══════════════════════════════════════════════════════
#  TEST 6: DC TEST (regresyon)
# ═══════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("TEST 6: DC Regresyon (V(2)=8V bekleniyor)")
print("=" * 60)

result6 = post_json("/analyze", {
    "netlist": "R1 1 2 1000\nR2 2 0 2000\nV1 1 0 DC 12\n* GND1 — Referans toprak (Node 0)\n* PROBE VP1 V(2)\n.end",
    "mode": "DC",
    "analysis_type": "NODAL"
})

if result6:
    v2 = get_node_voltage(result6, "2")
    check_close("V(2)", v2 if v2 else 0, 8.0, tolerance=0.001)
else:
    print("  ✕ DC regresyon başarısız!")


print("\n" + "=" * 60)
print("TÜM AC TESTLERİ TAMAMLANDI")
print("=" * 60)
