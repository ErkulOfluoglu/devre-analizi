"""
CircuitAnalyzer.API — Unit Tests for Helpers and Parser Utilities
Covers:
  1. parse_spice_value (SPICE unit suffix parsing, decimal precision, errors)
  2. sympy_to_numeric (SymPy and Python numeric conversions)
  3. make_complex_number (Pydantic ComplexNumber creation, strings, rounding)
  4. _to_sympy (Unwrapping lcapy/SymPy expressions)
  5. _evaluate_impedance & InfiniteImpedanceError (Impedance evaluation in DC/AC)
  6. parse_netlist & element parsers (Passive elements, sources, probes, ground, warnings)
  7. to_lcapy_netlist (Translation to lcapy netlist format)
  8. explainer.step_generator helpers (_format_complex_latex, _format_polar_latex,
     _engineering_notation, _format_complex_text, _paren)
"""

import math
import cmath
import pytest
import sympy
from lcapy import expr as lcapy_expr

from parser.netlist_parser import (
    parse_spice_value,
    parse_netlist,
    to_lcapy_netlist,
    ElementType,
    ParsedCircuit,
    ParsedElement,
    ParsedProbe,
)
from solver.circuit_solver import (
    sympy_to_numeric,
    make_complex_number,
    _to_sympy,
    _evaluate_impedance,
    InfiniteImpedanceError,
)
from explainer.step_generator import (
    _format_complex_latex,
    _format_polar_latex,
    _engineering_notation,
    _format_complex_text,
    _paren,
)


# ═══════════════════════════════════════════════════════
# 1. parse_spice_value
# ═══════════════════════════════════════════════════════

class TestParseSpiceValue:
    """SPICE birim çarpanları ve sayısal ayrıştırma testleri."""

    @pytest.mark.parametrize("inp,expected", [
        ("1000", 1000.0),
        ("2.2e-3", 0.0022),
        ("1E3", 1000.0),
    ])
    def test_plain_and_scientific_numbers(self, inp, expected):
        """Birim eksiz düz ve bilimsel gösterimdeki sayılar."""
        assert parse_spice_value(inp) == pytest.approx(expected)

    @pytest.mark.parametrize("suffix,exp_val", [
        ("T", 1e12), ("t", 1e12),
        ("G", 1e9), ("g", 1e9),
        ("MEG", 1e6), ("meg", 1e6),
        ("K", 1e3), ("k", 1e3),
        ("M", 1e-3), ("m", 1e-3),
        ("U", 1e-6), ("u", 1e-6),
        ("N", 1e-9), ("n", 1e-9),
        ("P", 1e-12), ("p", 1e-12),
        ("F", 1e-15), ("f", 1e-15),
    ])
    def test_all_suffixes_upper_and_lower(self, suffix, exp_val):
        """Her SPICE sonekinin büyük ve küçük harf desteği (M=milli, MEG=mega)."""
        val_str = f"1{suffix}"
        assert parse_spice_value(val_str) == pytest.approx(exp_val)

    def test_mega_and_milli_distinction(self):
        """SPICE standardında M=milli (1e-3), MEG=mega (1e6) ayrımı."""
        assert parse_spice_value("1M") == pytest.approx(1e-3)
        assert parse_spice_value("1MEG") == pytest.approx(1e6)
        assert parse_spice_value("4.7Meg") == pytest.approx(4.7e6)

    def test_kilo_resistor(self):
        """4.7k direnç değeri 4700.0 olmalıdır."""
        assert parse_spice_value("4.7k") == pytest.approx(4700.0)

    def test_exact_decimal_behavior(self):
        """Üs formatı ile tam ondalık doğruluğu (== ile kontrol)."""
        assert parse_spice_value("100u") == 1e-4
        assert parse_spice_value("2.2u") == 2.2e-6

    @pytest.mark.parametrize("invalid_input", ["abc", "", "1x", "k"])
    def test_invalid_inputs_raise_value_error(self, invalid_input):
        """Geçersiz değerler ValueError fırlatmalıdır."""
        with pytest.raises(ValueError):
            parse_spice_value(invalid_input)


# ═══════════════════════════════════════════════════════
# 2. sympy_to_numeric
# ═══════════════════════════════════════════════════════

class TestSympyToNumeric:
    """SymPy ve Python sayısal türlerini float/complex'e dönüştürme testleri."""

    def test_none_returns_zero(self):
        """None girişi 0.0 (float) döndürmelidir."""
        res = sympy_to_numeric(None)
        assert res == 0.0
        assert isinstance(res, float)

    def test_python_int_and_float(self):
        """Python int float'a çevrilmeli, float aynen geçmelidir."""
        res_int = sympy_to_numeric(5)
        assert res_int == 5.0
        assert isinstance(res_int, float)

        res_float = sympy_to_numeric(3.14)
        assert res_float == pytest.approx(3.14)
        assert isinstance(res_float, float)

    def test_python_complex_negligible_imaginary(self):
        """İhmal edilebilir sanal kısım (|imag| < 1e-12) gerçel float döndürmelidir."""
        val = complex(7.5, 1e-13)
        res = sympy_to_numeric(val)
        assert res == pytest.approx(7.5)
        assert isinstance(res, float)

    def test_python_complex_retained(self):
        """Belirgin sanal kısmı olan karmaşık sayı complex kalmalıdır."""
        val = complex(3, 4)
        res = sympy_to_numeric(val)
        assert res == (3 + 4j)
        assert isinstance(res, complex)

    def test_sympy_numbers(self):
        """SymPy Integer, Rational ve Float dönüşümleri."""
        assert sympy_to_numeric(sympy.Integer(8)) == 8.0
        assert sympy_to_numeric(sympy.Rational(1, 250)) == pytest.approx(0.004)
        assert sympy_to_numeric(sympy.Float(2.5)) == pytest.approx(2.5)
        assert sympy_to_numeric(sympy.sqrt(2)) == pytest.approx(math.sqrt(2))

    def test_sympy_complex_expressions(self):
        """SymPy sembolik karmaşık ifadeler Python complex'e dönüşmelidir."""
        res1 = sympy_to_numeric(3 + 4 * sympy.I)
        assert res1 == (3 + 4j)
        assert isinstance(res1, complex)

        res2 = sympy_to_numeric(sympy.I * 2)
        assert res2 == 2j
        assert isinstance(res2, complex)

    def test_sympy_real_valued_expression(self):
        """Gerçel değerli sembolik ifade (sympy.pi / 2) gerçel sayı dönmelidir."""
        res = sympy_to_numeric(sympy.pi / 2)
        assert res == pytest.approx(math.pi / 2)
        assert isinstance(res, float)


# ═══════════════════════════════════════════════════════
# 3. make_complex_number
# ═══════════════════════════════════════════════════════

class TestMakeComplexNumber:
    """ComplexNumber Pydantic modeli üretim testleri."""

    def test_pure_real_positive(self):
        """6.0 gerçel sayısı için model doğrulaması."""
        c = make_complex_number(6.0)
        assert c.real == 6.0
        assert c.imaginary == 0.0
        assert c.magnitude == 6.0
        assert c.phase_degrees == 0.0
        assert c.rectangular_str == "6"
        assert c.polar_str == "6∠0°"

    def test_complex_first_quadrant(self):
        """3+4j karmaşık sayısı için büyüklük, açı ve dizgiler."""
        c = make_complex_number(3 + 4j)
        assert c.real == 3.0
        assert c.imaginary == 4.0
        assert c.magnitude == pytest.approx(5.0)
        assert c.phase_degrees == pytest.approx(53.1301, abs=1e-3)
        assert c.rectangular_str == "3+j4"
        assert c.polar_str == "5∠53,13°"

    def test_complex_fourth_quadrant_unicode_minus(self):
        """3-4j için dikdörtgensel gösterimde U+2212 eksi işareti bulunmalıdır."""
        c = make_complex_number(3 - 4j)
        assert c.rectangular_str == "3\u2212j4"

    def test_pure_negative_imaginary(self):
        """-31.83j için gerçel kısmı olmayan negatif sanal gösterim."""
        c = make_complex_number(-31.83j)
        assert c.rectangular_str == "\u2212j31,83"

    def test_pure_positive_imaginary(self):
        """2j için 'j2' dikdörtgensel gösterim."""
        c = make_complex_number(2j)
        assert c.rectangular_str == "j2"

    def test_zero_value(self):
        """0 değeri için polar '0∠0°' ve faz 0 olmalıdır."""
        c = make_complex_number(0)
        assert c.magnitude == 0.0
        assert c.phase_degrees == 0.0
        assert c.polar_str == "0∠0°"

    def test_negative_real_value(self):
        """-1 gerçel sayısı için faz 180 derece olmalıdır."""
        c = make_complex_number(-1)
        assert c.phase_degrees == pytest.approx(180.0)

    def test_rounding_significant_digits(self):
        """1/3 gibi sayılar 10 anlamlı basamağa yuvarlanır."""
        c = make_complex_number(1 / 3)
        assert c.real == 0.3333333333
        assert c.magnitude == 0.3333333333

    def test_micro_values_keep_precision(self):
        """Mikro düzeyindeki değerler bozulmamalı (eski round(x, 6) 5e-6 verirdi)."""
        c = make_complex_number(4.7e-6)
        assert c.real == pytest.approx(4.7e-6, rel=1e-9)


# ═══════════════════════════════════════════════════════
# 4. _to_sympy
# ═══════════════════════════════════════════════════════

class TestToSympy:
    """_to_sympy ile lcapy ve SymPy ifadelerini açma testleri."""

    def test_sympy_object_identity(self):
        """SymPy nesnesi değiştirilmeden aynı şekilde dönmelidir."""
        sym = sympy.Symbol("x")
        assert _to_sympy(sym) is sym

    def test_plain_python_numbers(self):
        """Düz Python sayıları aynen dönmelidir."""
        assert _to_sympy(5) == 5
        assert _to_sympy(3.14) == pytest.approx(3.14)

    def test_lcapy_expression_unwraps_to_sympy(self):
        """lcapy ifadesi altındaki sympy.Basic nesnesine açılmalıdır."""
        e = lcapy_expr("3*s+2")
        unwrapped = _to_sympy(e)
        assert isinstance(unwrapped, sympy.Basic)


# ═══════════════════════════════════════════════════════
# 5. _evaluate_impedance & InfiniteImpedanceError
# ═══════════════════════════════════════════════════════

class TestEvaluateImpedance:
    """Laplace alanı empedans ifadelerinin DC ve AC'de değerlendirilmesi."""

    def test_parallel_rc_impedance(self):
        """R / (R*C*s + 1) paralel RC devresi empedansı."""
        s = sympy.Symbol("s")
        r_val = 100
        c_val = 1e-4
        expr_rc = r_val / (r_val * c_val * s + 1)

        # DC değerlendirme (s = 0 -> R = 100)
        z_dc = _evaluate_impedance(expr_rc, is_dc=True)
        assert z_dc == pytest.approx(100.0)

        # AC değerlendirme f = 50 Hz
        z_ac = _evaluate_impedance(expr_rc, is_dc=False, frequency=50)
        expected_ac = 100.0 / (1 + 1j * 2 * math.pi * 50 * 100 * 1e-4)
        assert z_ac == pytest.approx(expected_ac)

    def test_series_rl_impedance(self):
        """R + L*s seri RL devresi AC empedansı f = 60 Hz."""
        s = sympy.Symbol("s")
        expr_rl = 50 + 0.1 * s
        z_ac = _evaluate_impedance(expr_rl, is_dc=False, frequency=60)
        expected_ac = 50 + 1j * 2 * math.pi * 60 * 0.1
        assert z_ac == pytest.approx(expected_ac)

    def test_series_capacitor_dc_raises_infinite_impedance(self):
        """1 / (C*s) kapasitör empedansı DC'de açık devredir (InfiniteImpedanceError)."""
        s = sympy.Symbol("s")
        expr_c = 1 / (1e-4 * s)
        with pytest.raises(InfiniteImpedanceError):
            _evaluate_impedance(expr_c, is_dc=True)

    def test_ac_without_frequency_raises_value_error(self):
        """AC modda frekans verilmezse ve ifade s içeriyorsa ValueError fırlatılmalıdır."""
        s = sympy.Symbol("s")
        with pytest.raises(ValueError):
            _evaluate_impedance(s, is_dc=False, frequency=None)

    def test_constant_impedance_both_modes(self):
        """s içermeyen sabit bir empedans hem DC hem AC'de sabit kalmalıdır."""
        const = sympy.Integer(5)
        assert _evaluate_impedance(const, is_dc=True) == 5.0
        assert _evaluate_impedance(const, is_dc=False, frequency=50) == 5.0


# ═══════════════════════════════════════════════════════
# 6. parse_netlist & element parsers
# ═══════════════════════════════════════════════════════

class TestNetlistParser:
    """Netlist ayrıştırıcısı ve eleman kalıpları testleri."""

    def test_passive_elements_with_suffixes(self):
        """Direnç, kapasitör ve bobin birim ekleriyle doğru ayrıştırılmalıdır."""
        netlist = "R1 1 2 4.7k\nC1 2 0 100u\nL1 1 2 10m\n.end"
        circuit = parse_netlist(netlist)
        assert len(circuit.elements) == 3

        r = circuit.elements[0]
        assert r.id == "R1"
        assert r.element_type == ElementType.RESISTOR
        assert r.value == pytest.approx(4700.0)

        c = circuit.elements[1]
        assert c.id == "C1"
        assert c.element_type == ElementType.CAPACITOR
        assert c.value == pytest.approx(1e-4)

        l = circuit.elements[2]
        assert l.id == "L1"
        assert l.element_type == ElementType.INDUCTOR
        assert l.value == pytest.approx(0.01)

    def test_dc_source(self):
        """DC gerilim kaynağı ayrıştırması."""
        circuit = parse_netlist("V1 1 0 DC 12\n.end")
        assert len(circuit.elements) == 1
        v = circuit.elements[0]
        assert v.id == "V1"
        assert v.element_type == ElementType.DC_SOURCE
        assert v.value == pytest.approx(12.0)

    def test_ac_sine_source(self):
        """SINE biçimindeki AC kaynak parametreleri."""
        netlist = "VAC1 1 0 SINE(0 10 50 0 0 30)\n.end"
        circuit = parse_netlist(netlist)
        v = circuit.elements[0]
        assert v.element_type == ElementType.AC_SOURCE_SINE
        assert v.value == pytest.approx(10.0)
        assert v.params["offset"] == pytest.approx(0.0)
        assert v.params["amplitude"] == pytest.approx(10.0)
        assert v.params["frequency"] == pytest.approx(50.0)
        assert v.params["phase"] == pytest.approx(30.0)

    def test_ac_phasor_source(self):
        """AC_PHASOR kaynak parametreleri ve kartezyen fazör değeri."""
        netlist = "VAC1 1 0 AC_PHASOR(10, 30)\n.end"
        circuit = parse_netlist(netlist)
        v = circuit.elements[0]
        assert v.element_type == ElementType.AC_SOURCE_PHASOR
        assert v.params["amplitude"] == pytest.approx(10.0)
        assert v.params["phase"] == pytest.approx(30.0)

        expected_complex = cmath.rect(10.0, math.radians(30))
        assert v.params["phasor_complex"].real == pytest.approx(expected_complex.real)
        assert v.params["phasor_complex"].imag == pytest.approx(expected_complex.imag)

    def test_impedance_complex(self):
        """COMPLEX(50, 30) empedans elemanı ayrıştırması."""
        netlist = "Z1 2 3 COMPLEX(50, 30)\n.end"
        circuit = parse_netlist(netlist)
        z = circuit.elements[0]
        assert z.element_type == ElementType.IMPEDANCE
        assert z.params["impedance"] == (50 + 30j)
        assert z.value == pytest.approx(abs(50 + 30j))
        assert z.params["phase_degrees"] == pytest.approx(30.9637, abs=0.01)

    def test_impedance_polar(self):
        """POLAR(58.31, 30.96) empedans elemanı 50+30j değerine dönüştürülmelidir."""
        netlist = "Z1 2 3 POLAR(58.31, 30.96)\n.end"
        circuit = parse_netlist(netlist)
        z = circuit.elements[0]
        assert z.element_type == ElementType.IMPEDANCE
        assert z.params["impedance"].real == pytest.approx(50.0, abs=0.01)
        assert z.params["impedance"].imag == pytest.approx(30.0, abs=0.01)

    def test_probes(self):
        """* PROBE direktifleri devre problarına kaydedilmelidir."""
        netlist = "* PROBE VP1 V(2)\n* PROBE IP1 I(R1)\n.end"
        circuit = parse_netlist(netlist)
        assert len(circuit.probes) == 2
        assert circuit.probes[0] == ParsedProbe(id="VP1", probe_type="V", target="2")
        assert circuit.probes[1] == ParsedProbe(id="IP1", probe_type="I", target="R1")

    def test_ground_comment_directive(self):
        """GND yorumu has_ground bayrağını True yapar; yoksa False kalır."""
        netlist_with_gnd = "* GND1 — Referans toprak (Node 0)\nR1 1 0 1000\n.end"
        circuit1 = parse_netlist(netlist_with_gnd)
        assert circuit1.has_ground is True

        netlist_without_gnd = "R1 1 0 1000\n.end"
        circuit2 = parse_netlist(netlist_without_gnd)
        assert circuit2.has_ground is False

    def test_unknown_line_warning(self):
        """Tanınmayan eleman formatı circuit.warnings listesine uyarı ekler."""
        netlist = "X1 1 2 foo\n.end"
        circuit = parse_netlist(netlist)
        assert len(circuit.warnings) == 1
        assert "Tanınmayan" in circuit.warnings[0]

    def test_end_ignored_and_node_count(self):
        """.end satırı eleman sayılmamalı ve 0 dahil benzersiz düğüm sayısı hesaplanmalıdır."""
        netlist = "R1 1 2 1000\nV1 1 0 DC 12\n.end"
        circuit = parse_netlist(netlist)
        assert len(circuit.elements) == 2
        # Düğümler: "1", "2", "0" -> 3 adet
        assert circuit.node_count == 3


# ═══════════════════════════════════════════════════════
# 7. to_lcapy_netlist
# ═══════════════════════════════════════════════════════

class TestToLcapyNetlist:
    """lcapy netlist metni üretim testleri."""

    def test_dc_source_format(self):
        """DC kaynak süslü parantez içinde sayısal değer olarak yazılmalıdır."""
        circuit = parse_netlist("V1 1 0 DC 12\n.end")
        lcapy_str = to_lcapy_netlist(circuit)
        assert lcapy_str == "V1 1 0 {12.0}"

    def test_ac_phasor_zero_phase(self):
        """Fazı 0 olan fazör kaynak 'ac {10.0}' formatında olmalıdır."""
        circuit = parse_netlist("VAC1 1 0 AC_PHASOR(10, 0)\n.end")
        lcapy_str = to_lcapy_netlist(circuit)
        assert lcapy_str == "VAC1 1 0 ac {10.0}"

    def test_ac_phasor_with_phase(self):
        """Fazı 30 derece olan fazör 'exp(j*0.523599)' içermelidir."""
        circuit = parse_netlist("VAC1 1 0 AC_PHASOR(10, 30)\n.end")
        lcapy_str = to_lcapy_netlist(circuit)
        assert "exp(j*0.523599)" in lcapy_str

    def test_complex_impedance_positive_imag(self):
        """COMPLEX(50, 30) empedansı Z1 2 3 {50.0+30.0j} olarak çevrilmelidir."""
        circuit = parse_netlist("Z1 2 3 COMPLEX(50, 30)\n.end")
        lcapy_str = to_lcapy_netlist(circuit)
        assert lcapy_str == "Z1 2 3 {50.0+30.0j}"

    def test_complex_impedance_negative_imag(self):
        """COMPLEX(50, -30) empedansı {50.0-30.0j} içermelidir."""
        circuit = parse_netlist("Z1 2 3 COMPLEX(50, -30)\n.end")
        lcapy_str = to_lcapy_netlist(circuit)
        assert "{50.0-30.0j}" in lcapy_str


# ═══════════════════════════════════════════════════════
# 8. explainer.step_generator helpers
# ═══════════════════════════════════════════════════════

class TestStepGeneratorHelpers:
    """Çözüm adımı açıklayıcı yardımcı fonksiyon testleri."""

    def test_format_complex_latex(self):
        """_format_complex_latex ile karmaşık sayıların LaTeX biçimlendirmesi."""
        assert _format_complex_latex(8.0, "V") == "8 \\; \\text{V}"
        assert _format_complex_latex(50 + 30j, "Ω").startswith("50 + j30")
        assert _format_complex_latex(-2.5j) == "-j2,5"
        assert _format_complex_latex(-31.83j) == "-j31,83"

    def test_format_polar_latex(self):
        """_format_polar_latex ile kutupsal LaTeX formatı."""
        assert _format_polar_latex(3 + 4j) == "5 \\angle 53,13^\\circ"

    @pytest.mark.parametrize("val,unit,expected", [
        (0.004, "A", "4 mA"),
        (1000, "Ω", "1 kΩ"),
        (1e-6, "F", "1 µF"),
        (0, "V", "0 V"),
        (4700, "Ω", "4,7 kΩ"),
    ])
    def test_engineering_notation(self, val, unit, expected):
        """_engineering_notation ile mühendislik birim önekleri."""
        assert _engineering_notation(val, unit) == expected

    @pytest.mark.parametrize("val,expected", [
        (12, "12"),
        (-31.83j, "-j31,83"),
        (14.14 + 14.14j, "14,14+j14,14"),
        (3 - 4j, "3-j4"),
    ])
    def test_format_complex_text(self, val, expected):
        """_format_complex_text ile düz metin biçimlendirmesi."""
        assert _format_complex_text(val) == expected

    @pytest.mark.parametrize("val,expected", [
        (1000, "1000"),
        (-31.83j, "(-j31,83)"),
        (3 + 4j, "(3+j4)"),
        (-5, "(−5)"),
    ])
    def test_paren(self, val, expected):
        """_paren ile negatif ve toplam ifadeleri paranteze alma."""
        assert _paren(val) == expected
