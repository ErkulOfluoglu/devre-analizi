"""
Thevenin/Norton eşdeğerleri, bağımlı port ek ölçümleri (kısa devre/test kaynağı) ve karşıtlık teoremi çözücüsü.
"""

import cmath
import copy
from typing import List, Optional, Tuple

from explainer.formatting import node_name, node_pair
from explainer.narrative_core import PortCircuit, PortExtras, port_is_dead
from models.request import AnalysisMode, TheveninTerminals
from models.response import NortonResult, SolutionStep, TheveninResult
from parser.netlist_parser import (
    CURRENT_SOURCES, VOLTAGE_SOURCES, ElementType, ParsedCircuit, ParsedElement,
    element_nodes, lcapy_sense_map, to_lcapy_netlist,
)
from solver.error_text import turkish_error
from solver.numeric import (
    InfiniteImpedanceError, _evaluate_impedance, _extract_numeric,
    lcapy_element_current, make_complex_number,
)
from solver.numeric_ac import make_circuit
from solver.reciprocity import ReciprocityAnalysis, reciprocity_pair, source_phasor


# ═══════════════════════════════════════════════════════
#  THEVENİN EŞDEĞERİ
# ═══════════════════════════════════════════════════════

def _solve_thevenin(
    cct,
    terminals: TheveninTerminals,
    is_dc: bool,
    frequency: float,
    steps: List[SolutionStep],
    errors: List[str]
) -> Optional[TheveninResult]:
    """
    İki terminal (port) arasındaki Thevenin eşdeğerini hesaplar.

    Thevenin Teoremi:
        Vth = Açık devre gerilimi (OCV) — terminaller arasında
              yük yokken ölçülen gerilim.
        Zth = Thevenin empedansı — tüm bağımsız kaynaklar
              sıfırlanıp (V→kısa, I→açık) terminallerden
              bakılan empedans.

    ★ 2-Terminal (Port) Desteği:
        cct.thevenin(node_pos, node_neg)
        Varsayılan: node_neg = "0" (GND)
    """
    node_pos = terminals.node_positive
    node_neg = terminals.node_negative

    steps.append(SolutionStep(
        step_number=len(steps) + 1,
        title=f"Thevenin Eşdeğeri ({node_name(node_pos)} – {node_name(node_neg)})",
        description=(
            f"{node_name(node_pos)} ve {node_name(node_neg)} arasındaki "
            "Thevenin eşdeğer devresi hesaplanıyor.\n\n"
            "Adım A: Açık devre gerilimi (Vth) — terminaller "
            "arasında yük bağlamadan gerilimi ölç.\n"
            "Adım B: Thevenin empedansı (Zth) — tüm bağımsız "
            "kaynakları sıfırla, terminallerden bak."
        )
    ))

    try:
        # lcapy thevenin çağrısı — iki düğüm arası port
        th = cct.thevenin(node_pos, node_neg)

        # Vth — _extract_numeric omega yerine koymasını halleder
        vth_val = _extract_numeric(th.V, is_dc, frequency)

        # Zth — lcapy Laplace alanında verir (s); DC'de s=0, AC'de s=jω
        zth_val = _evaluate_impedance(th.Z, is_dc, frequency)

        vth_complex = make_complex_number(vth_val)
        zth_complex = make_complex_number(zth_val)

        thevenin_result = TheveninResult(
            vth=vth_complex,
            zth=zth_complex,
            node_positive=node_pos,
            node_negative=node_neg
        )

        # Thevenin sonuç LaTeX
        vth_latex = (
            f"V_{{th}} = {vth_complex.rectangular_str} \\text{{ V}}"
        )
        zth_latex = (
            f"Z_{{th}} = {zth_complex.rectangular_str} \\text{{ Ω}}"
        )

        steps.append(SolutionStep(
            step_number=len(steps) + 1,
            title="Thevenin Sonuçları",
            description=(
                f"Vth = {vth_complex.rectangular_str} V\nRth = {zth_complex.rectangular_str} Ω"
                if is_dc else
                f"Vth = {vth_complex.rectangular_str} V "
                f"({vth_complex.polar_str} V)\n"
                f"Zth = {zth_complex.rectangular_str} Ω "
                f"({zth_complex.polar_str} Ω)"
            ),
            equations=[
                f"Vth = {vth_complex.rectangular_str} V",
                f"Zth = {zth_complex.rectangular_str} Ω"
            ],
            latex_formula=f"{vth_latex} \\quad , \\quad {zth_latex}",
            result_snapshot={
                "Vth": vth_complex.rectangular_str,
                "Zth": zth_complex.rectangular_str,
                "Vth_polar": vth_complex.polar_str,
                "Zth_polar": zth_complex.polar_str
            }
        ))

        return thevenin_result

    except InfiniteImpedanceError:
        errors.append(
            f"⚠ Thevenin hesaplanamadı ({node_pair(node_pos, node_neg)}): "
            "Zth sonsuz.\n"
            "Terminallerden bakıldığında devre açık görünüyor — ör: DC "
            "analizde seri bağlı bir kondansatör akımı keser.\n"
            "Bu port için Thevenin eşdeğeri tanımsızdır."
        )
        return None
    except Exception as e:
        err_str = str(e).lower()
        if "singular" in err_str:
            errors.append(
                f"⚠ Thevenin hesaplanamadı ({node_pair(node_pos, node_neg)}):\n"
                "Devre denklemleri tek bir çözüme varmıyor (tekil sistem) — bu genellikle seçilen terminaller "
                "arasında geçerli bir devre yolu olmadığı anlamına gelir.\n"
                "Lütfen terminal düğümlerinin doğru seçildiğinden "
                "emin olun."
            )
        elif "not found" in err_str or "unknown" in err_str:
            errors.append(
                f"⚠ {node_name(node_pos)} veya {node_name(node_neg)} devrede bulunamadı.\n"
                "Lütfen Thevenin terminal düğümlerinin devredeki "
                "geçerli düğüm numaraları olduğunu kontrol edin."
            )
        else:
            errors.append(
                f"⚠ Thevenin hesaplanamadı: {turkish_error(e, 'thevenin')}"
            )
        return None


# ═══════════════════════════════════════════════════════
#  NORTON EŞDEĞERİ
# ═══════════════════════════════════════════════════════

def _solve_norton(
    cct,
    terminals: TheveninTerminals,
    is_dc: bool,
    frequency: float,
    steps: List[SolutionStep],
    errors: List[str]
) -> Optional[NortonResult]:
    """
    İki terminal (port) arasındaki Norton eşdeğerini hesaplar.

    Norton Teoremi (Thevenin'in dual'i):
        In = Kısa devre akımı (Isc) — terminaller kısa devre
             edildiğinde (+)'dan (−)'ye akan akım.
        Zn = Zth — tüm bağımsız kaynaklar sıfırlanıp
             terminallerden bakılan empedans (Yn = 1/Zn).

    ★ lcapy notu: cct.norton(n1, n2).I bu sürümde boş
      SuperpositionCurrent({}) döndürüyor. Bu yüzden In, aynı
      Norton nesnesinin .Isc alanından alınır ve In = Vth·Yn
      (= Vth/Zth) ile çapraz doğrulanır.
    """
    node_pos = terminals.node_positive
    node_neg = terminals.node_negative

    steps.append(SolutionStep(
        step_number=len(steps) + 1,
        title=f"Norton Eşdeğeri ({node_name(node_pos)} – {node_name(node_neg)})",
        description=(
            f"{node_name(node_pos)} ve {node_name(node_neg)} arasındaki "
            "Norton eşdeğer devresi hesaplanıyor.\n\n"
            "Adım A: Kısa devre akımı (In) — terminalleri bir tel ile "
            "kısa devre et, telden geçen akımı bul.\n"
            "Adım B: Norton empedansı (Zn) — tüm bağımsız kaynakları "
            "sıfırla (V→kısa devre), terminallerden bak. Zn = Zth.\n"
            "Kontrol: In = Vth / Zth (Thevenin ↔ Norton dönüşümü)."
        )
    ))

    try:
        no = cct.norton(node_pos, node_neg)

        in_val = _extract_numeric(no.Isc, is_dc, frequency)
        vth_val = _extract_numeric(no.Voc, is_dc, frequency)
        yn_val = _evaluate_impedance(no.Y, is_dc, frequency)

        zn_finite = abs(yn_val) > 1e-15
        zn_val = (1 / yn_val) if zn_finite else None

        # Çapraz doğrulama: In = Vth · Yn
        expected_in = vth_val * yn_val
        if abs(in_val - expected_in) > 1e-6 * max(abs(expected_in), 1e-9):
            errors.append(
                f"ℹ Norton tutarlılık uyarısı: Isc={in_val} ancak "
                f"Vth·Yn={expected_in}."
            )

        in_c = make_complex_number(in_val)
        yn_c = make_complex_number(yn_val)
        zn_c = make_complex_number(zn_val) if zn_finite else None
        vth_c = make_complex_number(vth_val)

        result = NortonResult(
            i_n=in_c,
            z_n=zn_c,
            y_n=yn_c,
            node_positive=node_pos,
            node_negative=node_neg
        )

        zn_str = f"{zn_c.rectangular_str} Ω" if zn_c else "∞ Ω"
        zn_polar = f"{zn_c.polar_str} Ω" if zn_c else "∞"
        equations = [
            f"In = Isc = {in_c.rectangular_str} A",
            f"Yn = {yn_c.rectangular_str} S",
            f"Zn = Zth = 1/Yn = {zn_str}",
        ]
        zn_latex = zn_c.rectangular_str if zn_c else "\\infty"
        latex = [
            f"I_{{N}} = {in_c.rectangular_str} \\text{{ A}}",
            f"Z_{{N}} = {zn_latex} \\text{{ Ω}}",
        ]
        if zn_c:
            equations.append(
                f"Kontrol: In = Vth / Zth = ({vth_c.rectangular_str}) / "
                f"({zn_c.rectangular_str}) = {in_c.rectangular_str} A"
            )
            latex.append(
                f"I_{{N}} = \\frac{{V_{{th}}}}{{Z_{{th}}}} = "
                f"\\frac{{{vth_c.rectangular_str}}}{{{zn_c.rectangular_str}}}"
            )
        else:
            equations.append(
                "Zn sonsuz → Norton eşdeğeri ideal bir akım kaynağıdır "
                "(Thevenin eşdeğeri tanımsız)."
            )

        steps.append(SolutionStep(
            step_number=len(steps) + 1,
            title="Norton Sonuçları",
            description=(
                f"In = {in_c.rectangular_str} A\nRn = {zn_str}"
                if is_dc else
                f"In = {in_c.rectangular_str} A ({in_c.polar_str} A)\n"
                f"Zn = {zn_str} ({zn_polar})"
            ),
            equations=equations,
            latex_formula=" \\quad , \\quad ".join(latex),
            result_snapshot={
                "In": in_c.rectangular_str,
                "In_polar": in_c.polar_str,
                "Zn": zn_c.rectangular_str if zn_c else "∞",
                "Zn_polar": zn_polar,
                "Yn": yn_c.rectangular_str,
                "Vth": vth_c.rectangular_str,
            }
        ))

        return result

    except Exception as e:
        err_str = str(e).lower()
        if "not invertible" in err_str or "singular" in err_str:
            errors.append(
                f"⚠ Norton hesaplanamadı ({node_pair(node_pos, node_neg)}): "
                "terminaller kısa devre edildiğinde bir gerilim kaynağı "
                "da kısa devre oluyor.\n"
                "Port doğrudan ideal bir gerilim kaynağına paralel → "
                "Zth = 0 ve In = Vth/0 sonsuz.\n"
                "Bu port için Norton eşdeğeri tanımsızdır "
                "(Thevenin eşdeğeri: yalnızca Vth)."
            )
        elif "not found" in err_str or "unknown" in err_str:
            errors.append(
                f"⚠ {node_name(node_pos)} veya {node_name(node_neg)} devrede bulunamadı.\n"
                "Lütfen Norton terminal düğümlerinin devredeki "
                "geçerli düğüm numaraları olduğunu kontrol edin."
            )
        else:
            errors.append(
                f"⚠ Norton hesaplanamadı: {turkish_error(e, 'norton')}"
            )
        return None


# ═══════════════════════════════════════════════════════
#  BAĞIMLI KAYNAKLI DEVREDE PORT: KISA DEVRE VE TEST KAYNAĞI
# ═══════════════════════════════════════════════════════

def _fresh_id(parsed: ParsedCircuit, base: str) -> str:
    used = {e.id.upper() for e in parsed.elements}
    name = base
    while name.upper() in used:
        name += "_"
    return name


def _solve_port_extras(
    parsed: ParsedCircuit, terminals: TheveninTerminals, is_dc: bool,
    frequency: Optional[float], raw_nodes: dict, raw_currents: dict,
) -> PortExtras:
    """
    Anlatımın ders kitabı yöntemi için gerçek sayılar (bağımlı kaynaklar SIFIRLANMAZ):

      • isc: terminaller 0 V'luk bir kaynakla (tel) kısa devre edilip devre yeniden
        çözülür; telden + → − akan akım (n+ → n− eleman akımı kuralı).
      • i_test: açık devre gerilimi ve kısa devre akımı 0 ise (bağımsız kaynak yok ya da
        terminallere hiçbir şey vermiyor) bağımsız kaynaklar sıfırlanır, terminallere
        1 V'luk test kaynağı (+ ucu node_positive) bağlanır; kaynağın devreye + ucundan
        verdiği akım (= −eleman akımı) bulunur. Rth = 1 V / I_test.

    Her ikisi de lcapy ile gerçekten çözülür; Rth'den türetilmez.
    """
    a, b = terminals.node_positive, terminals.node_negative
    extras = PortExtras()

    def solve_with(base: ParsedCircuit, src: ParsedElement, keep):
        sub = copy.deepcopy(base)
        sub.probes = []
        sub.elements.append(src)
        cct = make_circuit(sub, is_dc, frequency, to_lcapy_netlist(sub, frequency))
        sense = lcapy_sense_map(sub)
        current = complex(lcapy_element_current(cct, src, sense, is_dc, frequency))
        # Anlatım için değiştirilmiş devrenin düğüm gerilimleri ve eleman akımları
        # (süperpozisyon alt devreleriyle aynı yol); alınamazsa anlatım eski metne döner
        try:
            nodes = {n for e in sub.elements for n in (e.node_positive, e.node_negative)}
            v = {"0": 0j}
            for n in nodes - {"0"}:
                v[n] = complex(_extract_numeric(cct[n].V, is_dc, frequency))
            i = {e.id: complex(lcapy_element_current(cct, e, sense, is_dc, frequency))
                 for e in sub.elements}
            keep(PortCircuit(parsed=sub, source_id=src.id, node_voltages=v, element_currents=i))
        except Exception:
            pass
        return current

    def keep_sc(pc):
        extras.sc_circuit = pc

    def keep_test(pc):
        extras.test_circuit = pc

    short = ParsedElement(id=_fresh_id(parsed, "Vsc_port"), element_type=ElementType.DC_SOURCE,
                          node_positive=a, node_negative=b, value=0.0)
    try:
        extras.isc = solve_with(parsed, short, keep_sc)
    except Exception:
        extras.isc = None

    vth = complex(raw_nodes.get(a, 0)) - complex(raw_nodes.get(b, 0))
    if not port_is_dead(vth, extras.isc, raw_nodes, raw_currents):
        return extras

    zeroed = copy.deepcopy(parsed)
    for e in zeroed.elements:
        if e.element_type in VOLTAGE_SOURCES:
            e.element_type, e.value, e.params = ElementType.DC_SOURCE, 0.0, {}
        elif e.element_type in CURRENT_SOURCES:
            e.element_type, e.value, e.params = ElementType.CURRENT_DC, 0.0, {}
    if is_dc:
        test = ParsedElement(id=_fresh_id(parsed, "Vtest_port"),
                             element_type=ElementType.DC_SOURCE,
                             node_positive=a, node_negative=b, value=1.0)
    else:
        test = ParsedElement(id=_fresh_id(parsed, "Vtest_port"),
                             element_type=ElementType.AC_SOURCE_PHASOR,
                             node_positive=a, node_negative=b, value=1.0,
                             params={"amplitude": 1.0, "phase": 0.0})
    try:
        extras.i_test = -solve_with(zeroed, test, keep_test)
    except Exception:
        extras.i_test = None
    return extras


# ═══════════════════════════════════════════════════════
#  KARŞITLIK TEOREMİ (RECIPROCITY yöntemi): ikinci çözüm
# ═══════════════════════════════════════════════════════

def _fresh_node(parsed: ParsedCircuit, base: str) -> str:
    used = {n for e in parsed.elements for n in element_nodes(e)}
    name = base
    while name in used:
        name += "_"
    return name


def _solve_reciprocity(
    parsed: ParsedCircuit, mode: AnalysisMode, is_dc: bool, frequency: Optional[float],
    target_id: Optional[str], raw_nodes: dict, raw_currents: dict,
) -> Tuple[Optional[ReciprocityAnalysis], str]:
    """
    Kaynak ile hedef elemanı yer değiştirip devreyi ikinci kez çözer; (analiz, '') ya da
    (None, Türkçe sebep) döndürür. Birinci durum özgün devrenin zaten çözülmüş sonuçlarıdır.

    Gerilim kaynağı E (a+, b−), hedef Y (c, d):
      1. durum: I₁ = Y'nin c → d eleman akımı.
      2. durum: E yerine 0 V'luk bir kaynak (ampermetre) konur, Y (x, d)'ye taşınır, x gizli
         düğümdür; E'nin bir kopyası (+ ucu x, − ucu c) Y ile seri girer. I₂ = devreye a ucundan
         giren akım = −(ampermetrenin eleman akımı).
    Akım kaynağı I (a, b), hedef Y (c, d):
      1. durum: V₁ = V_c − V_d.  2. durum: I silinir (açık devre), kopyası (c, d) arasına
      konur; V₂ = V_a − V_b.
    Sayılar uyuşmazsa ya da ikinci devre çözülemezse (ör. yalnızca bobinlerden oluşan çevrede
    DC gerilim kaynağı) (None, sebep) döner. Gizli düğüm ve yardımcı kaynak adları
    hiçbir sonuca ya da metne girmez.
    """
    pair, why = reciprocity_pair(parsed, mode, target_id)
    if pair is None:
        return None, why
    src, tgt = pair
    voltage_form = src.element_type in VOLTAGE_SOURCES
    a, b = src.node_positive, src.node_negative
    c, d = tgt.node_positive, tgt.node_negative

    if voltage_form:
        if tgt.id not in raw_currents:
            return None, f"{tgt.id} elemanının akımı bulunamadı."
        case1 = complex(raw_currents[tgt.id])
    else:
        case1 = complex(raw_nodes.get(c, 0)) - complex(raw_nodes.get(d, 0))

    sub = copy.deepcopy(parsed)
    sub.probes = []
    ammeter = None
    if voltage_form:
        x = _fresh_node(parsed, "_rcp_x")
        ammeter = ParsedElement(id=_fresh_id(parsed, "Vrcp_amp"), element_type=ElementType.DC_SOURCE,
                                node_positive=a, node_negative=b, value=0.0)
        moved = copy.deepcopy(src)
        moved.id = _fresh_id(parsed, "Vrcp_src")
        moved.node_positive, moved.node_negative = x, c
        new_elements = []
        for e in sub.elements:
            if e.id == src.id:
                new_elements.append(ammeter)
            elif e.id == tgt.id:
                e.node_positive = x
                new_elements.append(e)
            else:
                new_elements.append(e)
        new_elements.append(moved)
        sub.elements = new_elements
    else:
        moved = copy.deepcopy(src)
        moved.id = _fresh_id(parsed, "Irp_src")
        moved.node_positive, moved.node_negative = c, d
        sub.elements = [e for e in sub.elements if e.id != src.id] + [moved]

    cct = make_circuit(sub, is_dc, frequency, to_lcapy_netlist(sub, frequency))
    sense = lcapy_sense_map(sub)
    if voltage_form:
        case2 = -complex(lcapy_element_current(cct, ammeter, sense, is_dc, frequency))
    else:
        def volt(n: str) -> complex:
            return 0j if n == "0" else complex(_extract_numeric(cct[n].V, is_dc, frequency))
        case2 = volt(a) - volt(b)

    if not (cmath.isfinite(case1) and cmath.isfinite(case2)):
        return None, "ikinci durumun çözümünde sonsuz ya da tanımsız bir değer çıktı."
    if abs(case1 - case2) > 1e-6 * max(abs(case1), abs(case2)) + 1e-12:
        return None, "kaynak taşınınca bulunan değer ilk durumla uyuşmadı (devre karşıtlık koşullarını sağlamıyor)."
    return ReciprocityAnalysis(
        form="current" if voltage_form else "voltage", source=src, target=tgt,
        source_value=source_phasor(src), case1=case1, case2=case2), ""
