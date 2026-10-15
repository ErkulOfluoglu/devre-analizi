"""lcapy AC phasor deep debug."""
from lcapy import Circuit
import sympy

cct = Circuit("""
VAC1 1 0 ac {10}
R1 1 2 100
C1 2 0 1e-04
""")

v2 = cct[2].V
print(f"v2 type: {type(v2).__name__}")

# .phasor is a property on SuperpositionVoltage
phasor = v2.phasor
print(f"v2.phasor type: {type(phasor).__name__}")
print(f"v2.phasor value: {phasor}")

# Check if it has free_symbols
if hasattr(phasor, 'free_symbols'):
    print(f"free_symbols: {phasor.free_symbols}")
    
    # Substitute omega_0
    omega_val = 2 * sympy.pi * 50
    for sym in phasor.free_symbols:
        print(f"  sym: {sym} (name={sym.name if hasattr(sym,'name') else '?'})")
        phasor = phasor.subs(sym, omega_val)
    
    print(f"After subs: {phasor}")
    print(f"evalf: {phasor.evalf()}")
    print(f"complex: {complex(phasor.evalf())}")
else:
    print("No free_symbols attr")
    # Maybe it's a dict or ExprDict
    print(f"dir: {[x for x in dir(phasor) if not x.startswith('_')][:20]}")

print()
print("=== Direct .phasor on component ===")
v2_comp = cct['VAC1'].V
print(f"VAC1.V = {v2_comp}")
print(f"VAC1.V.phasor = {v2_comp.phasor}")
print()

# Try .ac on component
print("=== .ac dict approach ===")
v2_ac = v2.ac
print(f"v2.ac type: {type(v2_ac).__name__}")
print(f"v2.ac value: {v2_ac}")

# ExprDict - try to iterate
if hasattr(v2_ac, 'items'):
    for k, v in v2_ac.items():
        print(f"  key={k}, val={v}")
        if hasattr(v, 'free_symbols'):
            print(f"  val.free_symbols: {v.free_symbols}")
            # Substitute
            omega_val = 2 * sympy.pi * 50
            for sym in v.free_symbols:
                v = v.subs(sym, omega_val)
            print(f"  After subs: {v}")
            ev = v.evalf()
            print(f"  evalf: {ev}")
            print(f"  complex: {complex(ev)}")
elif hasattr(v2_ac, 'values'):
    vals = list(v2_ac.values())
    print(f"  values: {vals}")
