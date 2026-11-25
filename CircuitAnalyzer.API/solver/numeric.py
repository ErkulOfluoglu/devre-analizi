"""
SymPy ↔ Python sayısal/karmaşık dönüşüm araçları ve lcapy ifade/empedans okuyucuları.
"""

import cmath
import math
from typing import Optional, Union

import sympy
from explainer.formatting import num
from models.response import ComplexNumber
from parser.netlist_parser import (
    CURRENT_SOURCES, DEPENDENT_CURRENT_OUTPUT, ParsedElement, lcapy_name,
)


# ═══════════════════════════════════════════════════════
#  SYMPY ↔ PYTHON DÖNÜŞÜM ARAÇLARI
# ═══════════════════════════════════════════════════════

def sympy_to_numeric(expr) -> Union[float, complex]:
    """
    SymPy ifadesini Python float veya complex'e dönüştürür.

    Dönüşüm öncelik sırası:
        1. None / 0 → 0.0
        2. Zaten float/int/complex ise → doğrudan döndür
        3. SymPy sayısal (Integer, Float, Rational) → float()
        4. SymPy karmaşık (a + b*I) → complex()
        5. Sembolik (hâlâ değişken içeriyor) → evalf() → complex()

    Args:
        expr: SymPy ifadesi veya Python sayı

    Returns:
        float veya complex
    """
    if expr is None:
        return 0.0

    # Zaten Python sayısıysa doğrudan döndür
    if isinstance(expr, (int, float)):
        return float(expr)
    if isinstance(expr, complex):
        return expr if abs(expr.imag) > 1e-12 else expr.real

    # lcapy Expr sarmalayıcısını aç — SymPy fonksiyonlarına lcapy nesnesi
    # vermek deprecation uyarısı üretir
    expr = _to_sympy(expr)

    try:
        # SymPy → float dene
        val = float(expr)
        return val
    except (TypeError, ValueError):
        pass

    try:
        # SymPy → complex (önce evalf ile sayısala çevir)
        evaluated = expr.evalf()
        val = complex(evaluated)
        if abs(val.imag) < 1e-12:
            return val.real
        return val
    except (TypeError, ValueError, AttributeError):
        pass

    try:
        # lcapy PhasorDomainVoltage/Current — complex() doğrudan çalışmaz
        # ama .real ve .imag SymPy ifadeleri döndürür
        re_part = float(sympy.re(expr).evalf())
        im_part = float(sympy.im(expr).evalf())
        if abs(im_part) < 1e-12:
            return re_part
        return complex(re_part, im_part)
    except (TypeError, ValueError, AttributeError):
        pass

    try:
        # lcapy Expr: .expr ile alttaki SymPy ifadesine eriş
        underlying = getattr(expr, 'expr', None)
        if underlying is not None and underlying is not expr:
            return sympy_to_numeric(underlying)
    except:
        pass

    try:
        # Son çare: string'e çevirip complex() dene
        s = str(expr.evalf())
        s = s.replace("*I", "j").replace("I", "j")
        val = complex(s)
        if abs(val.imag) < 1e-12:
            return val.real
        return val
    except:
        return 0.0


def _to_sympy(expr):
    """
    lcapy Expr nesnesini alttaki SymPy ifadesine açar.

    lcapy sonuçları (ConstantDomainExpression, PhasorDomainVoltage,
    LaplaceDomainImpedance...) SymPy ifadesini '.expr' içinde taşır.
    Zaten SymPy olan veya '.expr' taşımayan nesneler aynen döner.
    """
    if isinstance(expr, sympy.Basic):
        return expr
    try:
        underlying = getattr(expr, 'expr', None)
    except Exception:
        return expr
    return underlying if isinstance(underlying, sympy.Basic) else expr


def sympy_to_latex(expr) -> Optional[str]:
    """
    SymPy ifadesini LaTeX string'e dönüştürür.

    Örnekler:
        sympy.Rational(8, 1) → "8"
        V2 / 1000 + V2 / 2000 → "\\frac{V_{2}}{1000} + \\frac{V_{2}}{2000}"

    Returns:
        LaTeX string veya None (dönüşüm başarısızsa)
    """
    if expr is None:
        return None
    try:
        return sympy.latex(expr)
    except:
        return str(expr)


def sig_round(x: float, digits: int = 10) -> float:
    """
    Anlamlı basamağa yuvarlar: 4.7e-6 → 4.7e-6.

    Eskiden round(x, 6) kullanılıyordu; mikro düzeyindeki değerleri
    bozuyordu (4.7 µA → 5 µA, 0.4 µA → 0). Femto altı gürültü 0 olur.
    """
    if not math.isfinite(x):
        return x
    if abs(x) < 1e-15:
        return 0.0
    return float(f"{x:.{digits}g}")


def make_complex_number(value: Union[float, complex]) -> ComplexNumber:
    """
    Python float/complex → Pydantic ComplexNumber modeli.

    Her iki gösterim formunu (dikdörtgensel + kutupsal) üretir:
        float(6.0)          → real=6, imag=0, mag=6, phase=0°
        complex(3+4j)       → real=3, imag=4, mag=5, phase=53.13°

    Args:
        value: Python float veya complex

    Returns:
        ComplexNumber Pydantic modeli
    """
    if isinstance(value, (int, float)):
        value = complex(value, 0)

    real = value.real
    imag = value.imag
    magnitude = abs(value)
    # Sayısal gürültüyü temizle (ör. 8+1e-17j → 8): büyüklüğe göre
    # ihmal edilebilir kısımlar ve femto altı değerler 0 sayılır
    if magnitude < 1e-15:
        real = imag = magnitude = 0.0
    else:
        if abs(imag) <= 1e-12 * magnitude:
            imag = 0.0
        if abs(real) <= 1e-12 * magnitude:
            real = 0.0
    phase_deg = math.degrees(cmath.phase(complex(real, imag))) if magnitude > 1e-15 else 0.0

    # Dikdörtgensel gösterim: "50+j30" veya "6"
    if abs(imag) < 1e-10:
        rect_str = num(real)
    elif abs(real) < 1e-10:
        rect_str = f"{'−' if imag < 0 else ''}j{num(abs(imag))}"
    else:
        sign = "+" if imag >= 0 else "−"
        rect_str = f"{num(real)}{sign}j{num(abs(imag))}"

    # Kutupsal gösterim: "58.31∠30.96°"
    if magnitude < 1e-15:
        polar_str = "0∠0°"
    else:
        polar_str = f"{num(magnitude)}∠{num(phase_deg)}°"

    return ComplexNumber(
        real=sig_round(real),
        imaginary=sig_round(imag),
        magnitude=sig_round(magnitude),
        phase_degrees=round(phase_deg, 4),
        rectangular_str=rect_str,
        polar_str=polar_str
    )


def _substitute_frequency(expr, frequency: float):
    """
    SymPy ifadesindeki omega sembollerini sayısal değerle değiştirir.

    lcapy AC sonuçları 'omega_0' sembolü içerir:
        V2 = -1000*j/(omega_0 - 100*j)

    Bu fonksiyon omega_0 = 2πf yerine koyar.

    ★ NOT: lcapy v1.26 'omega_0' kullanır, 'omega' değil!
    """
    if expr is None or frequency is None:
        return expr

    try:
        omega_val = 2 * sympy.pi * frequency

        # lcapy'nin kullandığı tüm olası sembol adları
        for sym in list(expr.free_symbols):
            name = str(sym)
            if name in ('omega_0', 'omega', 'Omega', 'w'):
                expr = expr.subs(sym, omega_val)
            elif name == 'f':
                expr = expr.subs(sym, frequency)
    except (AttributeError, TypeError):
        pass

    return expr


def _extract_numeric(
    expr, is_dc: bool, frequency: float = None
) -> Union[float, complex]:
    """
    lcapy ifadesinden sayısal değer çıkarır.

    İş akışı:
        1. DC ise .dc bileşenini al, AC ise .phasor (property!) al
        2. ExprDict ise ilk değeri çıkar
        3. Frekans varsa omega_0 = 2πf yerine koy
        4. sympy_to_numeric ile Python float/complex'e çevir

    ★ NOT: lcapy .phasor property'dır (parantessiz), method değil!
    ★ NOT: lcapy .ac ExprDict döndürür {omega_0: expr} formatında
    """
    raw = None

    if is_dc:
        for getter in [lambda e: e.dc, lambda e: e]:
            try:
                raw = getter(expr)
                break
            except:
                continue
    else:
        time_phasor = _phasor_from_time_part(expr)
        if time_phasor is not None:
            return time_phasor
        # lcapy AC stratejisi:
        # 1. .ac: ExprDict döndürür {omega_0: expr} — ilk değeri al
        #    Debug'da doğrulandı: expr.ac → ExprDict({omega_0: -1000j/(omega_0-100j)})
        # 2. .phasor(): Method — parametresiz çağrılırsa expression dönebilir
        # 3. Doğrudan ifade
        for getter in [
            lambda e: _exprdict_first(e.ac),  # ExprDict'ten ilk değer (birincil)
            lambda e: e.phasor(),              # method call (yedek)
            lambda e: e
        ]:
            try:
                raw = getter(expr)
                if raw is not None:
                    break
            except:
                continue

    if raw is None:
        raw = expr

    # Frekans yerine koyma (AC modda omega_0 sembolünü çözer)
    if frequency is not None:
        raw = _substitute_frequency(raw, frequency)

    return sympy_to_numeric(raw)


def _phasor_from_time_part(expr) -> Optional[complex]:
    """
    Yalnız dirençli devrede lcapy AC çözümünü zaman bölgesinde verir:
        x(t) = A·cos(ω₀t) − B·sin(ω₀t)  →  fazör = A + jB

    Bu biçimde .ac sanal kısmı kaybeder (farklı fazlı kaynaklarda yanlış sonuç), bu yüzden fazör
    x(t)'nin çeyrek periyot aralıklı dört değerinden okunur. Biçim bu değilse None döner.
    """
    try:
        parts = {str(key): value for key, value in expr.items()}
    except (AttributeError, TypeError):
        return None
    if "t" not in parts or any(name.startswith("omega") for name in parts):
        return None

    x_t = _to_sympy(parts["t"])
    symbols = {str(sym): sym for sym in x_t.free_symbols}
    if not set(symbols) <= {"t", "omega_0"}:
        return None

    def sample(theta):
        subs = {symbols["t"]: theta} if "t" in symbols else {}
        if "omega_0" in symbols:
            subs[symbols["omega_0"]] = 1
        return float(x_t.subs(subs).evalf())

    a = (sample(0) - sample(sympy.pi)) / 2
    b = (sample(3 * sympy.pi / 2) - sample(sympy.pi / 2)) / 2
    return a if abs(b) < 1e-12 else complex(a, b)


def _exprdict_first(expr_dict):
    """
    lcapy ExprDict'ten ilk değeri çıkarır.

    lcapy .ac özelliği ExprDict({omega_0: expr}) formatında döndürür.
    Bu fonksiyon ilk (ve genellikle tek) ifadeyi çıkarır.
    """
    try:
        # ExprDict bir dict-like objedir
        values = list(expr_dict.values())
        if values:
            return values[0]
    except:
        pass
    return expr_dict


def lcapy_element_current(
    cct, elem: ParsedElement, sense: dict, is_dc: bool, frequency: float = None
) -> Union[float, complex]:
    """
    Elemanın içinden n+ → n− akan akım (uygulamanın raporladığı işaret).

    • Bağımsız akım kaynağı: lcapy'ye uçlar ters yazıldığı için (bkz.
      to_lcapy_netlist) lcapy akımı kendi ilk→ikinci ucuna göre verir →
      işaret çevrilir. Sonuç: kaynak içinden n+ → n− (= kaynak değeri).
    • Akım çıkışlı bağımlı kaynak (G, F): lcapy bunun akımını vermez; elemanla
      seri konan 0 V'luk gizli ölçüm kaynağının akımı alınır (zaten n+ → n−).
    • Diğerleri: lcapy'nin eleman akımı.
    """
    if elem.element_type in DEPENDENT_CURRENT_OUTPUT:
        return _extract_numeric(cct[sense[elem.id][0]].I, is_dc, frequency)
    # Diyot eşdeğer kaynağı lcapy'de gizli V… adıyla durur (bkz. netlist_parser.lcapy_name)
    i_val = _extract_numeric(cct[lcapy_name(elem)].I, is_dc, frequency)
    if elem.element_type in CURRENT_SOURCES:
        i_val = -i_val
    return i_val


class InfiniteImpedanceError(ValueError):
    """Empedans sonsuz (açık devre) — ör: DC'de seri kapasitör."""


def _evaluate_impedance(
    expr, is_dc: bool, frequency: float = None
) -> Union[float, complex]:
    """
    lcapy Laplace alanı empedansını/admitansını sayısala çevirir.

    lcapy thevenin().Z ve norton().Y ifadelerini 's' cinsinden verir:
        Z(s) = R / (R·C·s + 1)

    Değerlendirme noktası:
        DC  →  s = 0           (C açık devre, L kısa devre)
        AC  →  s = jω = j2πf

    ★ NOT: Eski kod sadece omega_0 yerine koyuyordu; 's' sembolü
      kaldığı için dönüşüm başarısız olup sessizce 0 dönüyordu.

    Raises:
        InfiniteImpedanceError: Sonuç sonsuzsa (ör: DC'de seri kapasitör)
        ValueError: AC modda frekans bilinmiyorsa
    """
    if isinstance(expr, (int, float, complex)):
        # Sayısal AC çözücüden gelen değer (sembolik değil)
        if not cmath.isfinite(expr):
            raise InfiniteImpedanceError("Empedans sonsuz (açık devre).")
        return sympy_to_numeric(expr)

    e = _to_sympy(expr)

    s_syms = [sym for sym in getattr(e, 'free_symbols', ()) if str(sym) == 's']
    if s_syms:
        s = s_syms[0]
        if is_dc:
            s_val = sympy.Integer(0)
        elif frequency is not None:
            s_val = sympy.I * 2 * sympy.pi * sympy.nsimplify(frequency)
        else:
            raise ValueError("AC empedans için frekans gerekli.")

        evaluated = e.subs(s, s_val)
        if evaluated.has(sympy.nan):
            # 0/0 belirsizliği → limit ile çöz
            evaluated = sympy.limit(e, s, s_val)
        e = evaluated

    if frequency is not None:
        e = _substitute_frequency(e, frequency)

    if isinstance(e, sympy.Basic) and e.has(sympy.zoo, sympy.oo, -sympy.oo):
        raise InfiniteImpedanceError("Empedans sonsuz (açık devre).")

    return sympy_to_numeric(e)
