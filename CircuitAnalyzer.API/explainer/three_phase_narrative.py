"""
CircuitAnalyzer API — Üç faz anlatımı (Faz 3 / v1.6)

Ders kitabı sırası:
    Devreyi Tanıyalım → Faz ve Hat Büyüklükleri → (Dengeli) Tek Faz Eşdeğeri
    ya da (Dengesiz) Kol Kol Çözüm → Güç → Aron (3 iletkenli) → Kompanzasyon (hedef verildiyse)
    → Wattmetre okumaları → Kontrol → Sonuç

Tüm sayılar çözücüden (lcapy) gelir; elle türetme solver.three_phase'de çözücüyle karşılaştırılır.
Uyuşmazsa ya da devre kalıba girmiyorsa (hat empedansı, birden çok kaynak/yük, transformatör …)
kısa anlatım verilir: tanıtım + çözücü sonuçları + sebep. Gerilim sembolü V'dir; kitaplardaki
U gösterimi bir notla belirtilir.
"""

import math
from typing import List

from explainer.formatting import MINUS, eng, num, polar, rect
from explainer.narrative import _Section
from explainer.transformer_narrative import _c, _cn, _zeq
from models.request import AnalysisType
from solver.three_phase import DELTA_ARMS, PHASES, SQRT3, ThreePhaseAnalysis, line_voltages

U_NOTE = "Kitaplarda gerilim U ile de gösterilir (U = V); U_h hat, U_f faz gerilimidir."
OTHER_METHOD_NOTE = "Bu devrede üç fazlı eleman var; çözüm Üç Faz yöntemiyle anlatılıyor."
_PHASE_NAME = {"R": "R", "S": "S", "T": "T"}


def _z(z: complex) -> str:
    return _zeq(z)


def _basis(an) -> str:
    return "etkin" if an.is_rms else "tepe"


def _pf_text(an) -> str:
    return {"lagging": "geri (endüktif)", "leading": "ileri (kapasitif)",
            "unity": "birim"}[an.pf_type]


def _arm_keys(an):
    return PHASES if an.conn_l == "Y" else tuple(k for k, _, _ in DELTA_ARMS)


def _arm_name(an, k: str) -> str:
    return f"Z_{k}"


def build_three_phase_sections(an: ThreePhaseAnalysis, requested_type=None,
                               transformer: bool = False) -> List[_Section]:
    """Üç faz anlatımı. Kalıba girmeyen devrede (an.guided False) kısa anlatım."""
    sections = [_intro(an, requested_type)]
    if an.guided:
        sections += _voltage_section(an)
        sections += _balanced_sections(an) if an.balanced else _unbalanced_sections(an)
        sections += _power_section(an)
    else:
        sections += _short_sections(an, transformer)
    sections += _aron_section(an)
    sections += _compensation_section(an)
    if an.meters:
        sections.append(_meter_section(an.meters, an.is_rms, False))
    if an.guided:
        sections.append(_check_section(an))
    sections.append(_result_section(an))
    return sections


# ═══════════════════════════════════════════════════════
#  DEVREYİ TANIYALIM
# ═══════════════════════════════════════════════════════

def _intro(an: ThreePhaseAnalysis, requested_type) -> _Section:
    s = _Section("Devreyi Tanıyalım")
    if requested_type not in (None, AnalysisType.THREE_PHASE):
        s.note(OTHER_METHOD_NOTE)
    p = an.src.params
    conn = "yıldız (Y)" if an.conn_s == "Y" else "üçgen (Δ)"
    kind = "hat" if (an.conn_s == "D" or p["value_kind"] == "LINE") else "faz"
    given = an.uh if kind == "hat" else an.uf
    s.text(f"Kaynak: {an.src.id}, {conn} bağlı üç fazlı kaynak; girilen {kind} gerilimi "
           f"{eng(given, 'V')} ({_basis(an)} değer), f = {num(an.frequency)} Hz, "
           f"R fazının açısı {num(p['phase'])}°, faz sırası {an.sequence}.")
    if an.load is not None:
        lconn = "yıldız (Y)" if an.conn_l == "Y" else "üçgen (Δ)"
        zs = ", ".join(f"{_arm_name(an, k)} = {rect(an.z[k], 'Ω')}" for k in _arm_keys(an))
        s.text(f"Yük: {an.load.id}, {lconn} bağlı üç fazlı yük; {zs}.")
    if an.wires == 4:
        s.text("İletken sayısı: 4 (R, S, T hatları ve nötr iletkeni).")
    else:
        s.text("İletken sayısı: 3 (R, S, T hatları); nötr iletkeni yok.")
    s.text("Bu çözümde AC değerler etkin (RMS) olarak gösterilir." if an.is_rms
           else "Bu çözümde AC değerler tepe değer olarak gösterilir.")
    s.math(f"U_h = √3 · U_f  →  U_h = {eng(an.uh, 'V')},  U_f = U_h / √3 = {eng(an.uf, 'V')}")
    if an.conn_s == "D":
        s.note("Üçgen kaynakta sargı gerilimi hat gerilimine eşittir ve ideal üçgen gerilim çevrimi "
               "çözücü için tekildir; bu yüzden kaynak içeride eşdeğer yıldıza çevrilir "
               "(yüzer sanal nötr, her fazda U_f = U_h/√3). Hat gerilimleri ve hat akımları değişmez.")
    s.text("Amaç: faz ve hat akımlarını, nötr akımını ve gücü (P, Q, S, cos φ) bulmak.")
    for n in an.notes:
        s.note(n)
    s.note(U_NOTE)
    return s


# ═══════════════════════════════════════════════════════
#  FAZ VE HAT BÜYÜKLÜKLERİ
# ═══════════════════════════════════════════════════════

def _voltage_section(an: ThreePhaseAnalysis) -> List[_Section]:
    s = _Section("Faz ve Hat Büyüklükleri")
    th = float(an.src.params["phase"])
    s.text("Faz gerilimleri fazörlerdir ve birbirinden 120° farklıdır "
           f"(faz sırası {an.sequence}):")
    for ph in PHASES:
        s.math(f"V_{ph}N = {_c(an.v_ph[ph], 'V')}")
    s.text("Hat gerilimi iki faz geriliminin farkıdır; büyüklüğü faz geriliminin √3 katıdır "
           "ve fazı 30° kayar:")
    vl = line_voltages(an.v_ph)
    s.math(f"V_RS = V_RN {MINUS} V_SN = {_c(vl['RS'], 'V')}")
    s.math(f"V_ST = V_SN {MINUS} V_TN = {_c(vl['ST'], 'V')}")
    s.math(f"V_TR = V_TN {MINUS} V_RN = {_c(vl['TR'], 'V')}")
    s.math(f"|V_RS| = √3 · U_f = √3 · {eng(an.uf, 'V')} = {eng(abs(vl['RS']), 'V')}")
    if abs(th) > 1e-9:
        s.note(f"R fazının başlangıç açısı {num(th)}° olduğundan tüm açılar {num(th)}° kaymıştır.")
    return [s]


# ═══════════════════════════════════════════════════════
#  DENGELİ
# ═══════════════════════════════════════════════════════

def _balanced_sections(an: ThreePhaseAnalysis) -> List[_Section]:
    h = an.hand
    s = _Section("Tek Faz Eşdeğeri (Dengeli Yük)")
    z0 = an.z[_arm_keys(an)[0]]
    s.text("Üç empedans eşit ve kaynak simetrik olduğundan devre dengelidir. Bir fazı çözmek yeter; "
           "diğer fazlar aynı büyüklükte, ∓120° kaymış olarak yazılır.")
    if an.conn_l == "Y":
        if an.wires == 4:
            s.text("Dengeli yıldız yükte yük nötrü ile kaynak nötrü aynı potansiyeldedir; nötr "
                   "iletkeninden akım geçmez.")
        else:
            s.text("Dengeli yıldız yükte yük nötr noktası kaynak nötrüyle aynı potansiyeldedir "
                   "(V_N'N = 0); nötr iletkeni olmasa da kol gerilimi faz gerilimine eşittir.")
        s.text("Yıldız bağlantıda hat akımı faz akımına eşittir: I_h = I_f.")
        s.math(f"I_f = V_RN / Z = {_c(an.v_ph['R'], 'V')} / {_z(z0)} = {_c(h['i_line']['R'], 'A')}")
    else:
        s.text("Üçgen yükte her kol hat gerilimini görür: U_f = U_h. Hat akımı faz akımının "
               "√3 katıdır ve 30° geridedir.")
        vl = line_voltages(an.v_ph)
        s.math(f"I_RS = V_RS / Z = {_c(vl['RS'], 'V')} / {_z(z0)} = {_c(h['i_phase']['RS'], 'A')}")
        s.math(f"I_ST = {_c(h['i_phase']['ST'], 'A')},  I_TR = {_c(h['i_phase']['TR'], 'A')}")
        s.math(f"I_h = √3 · I_f = √3 · {eng(abs(h['i_phase']['RS']), 'A')} = "
               f"{eng(abs(h['i_line']['R']), 'A')}")
        s.math(f"I_R = I_RS {MINUS} I_TR = {_c(h['i_line']['R'], 'A')}")
    s.text("Hat akımları 120° aralıklıdır:" if an.conn_l == "D" else "Diğer hat akımları ∓120° kayar:")
    for ph in (PHASES if an.conn_l == "Y" else ("S", "T")):
        s.math(f"I_{ph} = {_c(h['i_line'][ph], 'A')}")
    if an.wires == 4:
        s.math(f"I_N = I_R + I_S + I_T = {eng(0.0, 'A')}")
    return [s]


# ═══════════════════════════════════════════════════════
#  DENGESİZ
# ═══════════════════════════════════════════════════════

def _unbalanced_sections(an: ThreePhaseAnalysis) -> List[_Section]:
    h = an.hand
    s = _Section("Kol Kol Çözüm (Dengesiz Yük)")
    s.text("Empedanslar eşit olmadığından devre dengesizdir: tek faz eşdeğeri kullanılamaz, her kol "
           "ayrı çözülür.")
    if an.conn_l == "Y" and an.wires == 4:
        s.text("Nötr iletkeni yük nötrünü kaynak nötrüne bağlar; her kol kendi faz gerilimini görür:")
        for ph in PHASES:
            s.math(f"I_{ph} = V_{ph}N / Z_{ph} = {_c(an.v_ph[ph], 'V')} / {_z(an.z[ph])} = "
                   f"{_c(h['i_line'][ph], 'A')}")
        s.text("Nötr iletkeninden dönen akım hat akımlarının fazör toplamıdır:")
        tot_n = sum(h['i_line'].values())
        if abs(tot_n) <= 1e-6 * max(abs(v) for v in h['i_line'].values()):
            tot_n = 0j
        s.math(f"I_N = I_R + I_S + I_T = {_c(tot_n, 'A')}")
    elif an.conn_l == "Y":
        s.text("Nötr iletkeni yok (3 iletkenli yüzer yıldız): yük nötr noktası kaynak nötrüne göre "
               "kayar. Kayma gerilimi Millman teoremiyle bulunur:")
        s.math("V_N'N = (V_RN/Z_R + V_SN/Z_S + V_TN/Z_T) / (1/Z_R + 1/Z_S + 1/Z_T)")
        num_t = sum(an.v_ph[k] / an.z[k] for k in PHASES)
        den_t = sum(1 / an.z[k] for k in PHASES)
        s.math(f"Pay = {rect(num_t, 'A')},  Payda = {rect(den_t, 'S')}")
        s.math(f"V_N'N = {_c(h['vnn'], 'V')}")
        s.text("Her kolun gerilimi faz geriliminden kayma gerilimi çıkarılarak, akımı da kol "
               "empedansına bölünerek bulunur:")
        for ph in PHASES:
            s.math(f"V_{ph}' = V_{ph}N {MINUS} V_N'N = {_c(h['arm_v'][ph], 'V')};  "
                   f"I_{ph} = V_{ph}' / Z_{ph} = {_c(h['i_line'][ph], 'A')}")
        tot_i = sum(h['i_line'].values())
        if abs(tot_i) <= 1e-6 * max(abs(v) for v in h['i_line'].values()):
            tot_i = 0j
        s.math(f"I_R + I_S + I_T = {_c(tot_i, 'A')}  (nötr iletkeni olmadığından toplam sıfırdır)")
    else:
        s.text("Üçgen yükte her kol bir hat gerilimini görür; önce kol (faz) akımları, sonra KCL ile "
               "hat akımları bulunur:")
        vl = line_voltages(an.v_ph)
        for k in ("RS", "ST", "TR"):
            s.math(f"I_{k} = V_{k} / Z_{k} = {_c(vl[k], 'V')} / {_z(an.z[k])} = "
                   f"{_c(h['i_phase'][k], 'A')}")
        s.math(f"I_R = I_RS {MINUS} I_TR = {_c(h['i_line']['R'], 'A')}")
        s.math(f"I_S = I_ST {MINUS} I_RS = {_c(h['i_line']['S'], 'A')}")
        s.math(f"I_T = I_TR {MINUS} I_ST = {_c(h['i_line']['T'], 'A')}")
    return [s]


# ═══════════════════════════════════════════════════════
#  GÜÇ
# ═══════════════════════════════════════════════════════

def _power_section(an: ThreePhaseAnalysis) -> List[_Section]:
    s = _Section("Güç")
    h = an.hand
    f_txt = "V·I*" if an.is_rms else "½·V·I*"
    if an.balanced:
        ih = abs(h["i_line"]["R"])
        if not an.is_rms:
            s.text("Fazörler tepe değer olduğundan güç formülleri için önce etkin değerlere çeviririz "
                   "(etkin = tepe / √2):")
            s.math(f"U_h = {eng(an.uh, 'V')} / √2 = {eng(an.uh_rms, 'V')},  "
                   f"I_h = {eng(ih, 'A')} / √2 = {eng(an.to_rms(ih), 'A')}")
        uh_r, ih_r = an.uh_rms, an.to_rms(ih)
        z0 = an.z[_arm_keys(an)[0]]
        cosphi = z0.real / abs(z0)
        sinphi = abs(z0.imag) / abs(z0)
        s.math(f"cos φ = Re(Z) / |Z| = {num(z0.real)} / {num(abs(z0))} = {num(cosphi)}  "
               f"(φ = {num(math.degrees(math.atan2(z0.imag, z0.real)))}°)")
        s.math(f"P = √3 · U_h · I_h · cos φ = √3 · {num(uh_r)} · {num(ih_r)} · {num(cosphi)} = "
               f"{eng(an.p, 'W')}")
        if an.conn_l == "Y":
            uf_r, if_r = an.to_rms(an.uf), ih_r
        else:
            uf_r, if_r = uh_r, an.to_rms(abs(h["i_phase"]["RS"]))
        s.math(f"P = 3 · U_f · I_f · cos φ = 3 · {num(uf_r)} · {num(if_r)} · {num(cosphi)} = "
               f"{eng(3 * uf_r * if_r * cosphi, 'W')}")
        sgn = "" if z0.imag >= 0 else MINUS
        s.math(f"Q = √3 · U_h · I_h · sin φ = {sgn}{eng(SQRT3 * uh_r * ih_r * sinphi, 'VAR')}")
        s.math(f"S = √3 · U_h · I_h = {eng(SQRT3 * uh_r * ih_r, 'VA')}")
    else:
        s.text("Dengesiz devrede güç, kolların karmaşık güçlerinin toplamıdır "
               f"(S = {f_txt} her kol için; P = Re, Q = Im):")
        for k in _arm_keys(an):
            if an.conn_l == "Y":
                arm_v, arm_i = h["arm_v"][k], h["i_line"][k]
            else:
                arm_v, arm_i = h["arm_v"][k], h["i_phase"][k]
            sk = an.f * arm_v * arm_i.conjugate()
            s.math(f"S_{k} = {f_txt} = {rect(sk, 'VA')}")
        tot = complex(an.p, an.q)
        s.math(f"P = ΣP_k = {eng(an.p, 'W')},  Q = ΣQ_k = {eng(an.q, 'VAR')},  "
               f"S = √(P² + Q²) = {eng(an.s, 'VA')}")
    s.math(f"cos φ = P / S = {num(an.pf)}  →  {_pf_text(an)}")
    if an.pf_type == "lagging":
        s.note("Q > 0: yük endüktiftir, akım gerilimin gerisindedir (geri güç katsayısı).")
    elif an.pf_type == "leading":
        s.note("Q < 0: yük kapasitiftir, akım gerilimin ilerisindedir (ileri güç katsayısı).")
    return [s]


# ═══════════════════════════════════════════════════════
#  ARON
# ═══════════════════════════════════════════════════════

def _aron_section(an: ThreePhaseAnalysis) -> List[_Section]:
    if an.aron is None:
        return []
    pa, pb, v_rs, v_ts = an.aron
    s = _Section("Aron (İki Wattmetre) Yöntemi")
    f_txt = "" if an.is_rms else "½ · "
    s.text("3 iletkenli devrede toplam güç iki wattmetreyle ölçülebilir: birinci wattmetrenin akım "
           "bobini R hattında, ikincisinin T hattında, gerilim bobinleri S hattına bağlıdır "
           "(V_RS ve V_TS).")
    s.math(f"P_A = {f_txt}Re(V_RS · I_R*) = {eng(pa, 'W')}")
    s.math(f"P_B = {f_txt}Re(V_TS · I_T*) = {eng(pb, 'W')}")
    s.math(f"P = P_A + P_B = {eng(pa + pb, 'W')}")
    if abs(pa + pb - an.p) <= 1e-5 * max(abs(an.p), 1e-9) + 1e-6:
        s.check(f"P_A + P_B = {eng(pa + pb, 'W')}, kolların toplam gücüne ({eng(an.p, 'W')}) eşit.")
    if an.guided and an.balanced:
        phi = math.degrees(math.atan2(an.q, an.p))
        sign = "+" if an.sequence == "RST" else MINUS
        sign2 = MINUS if an.sequence == "RST" else "+"
        ih_r = an.to_rms(abs(an.hand["i_line"]["R"]))
        s.text("Dengeli yükte okumalar φ'ye bağlıdır "
               f"(φ = {num(phi)}°, faz sırası {an.sequence}):")
        s.math(f"P_A = U_h · I_h · cos(30° {sign} φ),  P_B = U_h · I_h · cos(30° {sign2} φ)")
        if abs(pa) < 1e-6 * max(abs(pb), 1e-9) or abs(pb) < 1e-6 * max(abs(pa), 1e-9):
            s.note("cos φ = 0,5 (φ = 60°) iken wattmetrelerden biri 0 okur; φ > 60° olursa biri "
                   "ters (negatif) sapar.")
    return [s]


# ═══════════════════════════════════════════════════════
#  KOMPANZASYON
# ═══════════════════════════════════════════════════════

def _compensation_section(an: ThreePhaseAnalysis) -> List[_Section]:
    c = an.comp
    if c is None:
        return []
    s = _Section("Kompanzasyon")
    s.text(f"Hedef güç katsayısı cos φ₂ = {num(c.target)}.")
    if not c.applied and c.reason:
        s.note(f"Kompanzasyon hesabı yapılamadı: {c.reason}")
        if c.q_c == 0.0:
            return [s]
    if c.q_c == 0.0 or not c.applied:
        return [s]
    s.math(f"φ₁ = arccos({num(an.pf)}) = {num(math.degrees(c.phi1))}°,  tan φ₁ = {num(math.tan(c.phi1))}")
    s.math(f"φ₂ = arccos({num(c.target)}) = {num(math.degrees(c.phi2))}°,  tan φ₂ = {num(math.tan(c.phi2))}")
    s.math(f"Q_C = P · (tan φ₁ {MINUS} tan φ₂) = {eng(an.p, 'W')} · ({num(math.tan(c.phi1))} {MINUS} "
           f"{num(math.tan(c.phi2))}) = {eng(c.q_c, 'VAR')}")
    s.text("Q_C üç kola eşit paylaştırılır: her kola düşen Q_C/3 = " + eng(c.q_per_arm, 'VAR') + ".")
    uh = an.uh_rms
    s.text("Yıldız bağlı kondansatörde her kol faz gerilimini (U_f = U_h/√3), üçgen bağlıda hat "
           "gerilimini görür:")
    s.math(f"C_Y = Q_C / (ω · U_h²) = {eng(c.q_c, 'VAR')} / ({num(an.omega)} · {num(uh)}²) = "
           f"{eng(c.c_y, 'F')}")
    s.math(f"C_Δ = C_Y / 3 = {eng(c.c_delta, 'F')}")
    s.math(f"I_h' = P / (√3 · U_h · cos φ₂) = {eng(an.p, 'W')} / (√3 · {num(uh)} · {num(c.target)}) = "
           f"{eng(an.to_rms(c.i_after), 'A')}  (etkin; kompanzasyondan önce {eng(an.to_rms(c.i_before), 'A')})")
    s.check("Kondansatörler devreye eklenip çözücüyle yeniden çözüldü: cos φ₂ = "
            f"{num(c.pf_check)}, hat akımı {eng(c.i_after, 'A')} ({_basis(an)}).")
    return [s]


# ═══════════════════════════════════════════════════════
#  WATTMETRE
# ═══════════════════════════════════════════════════════

def wattmeter_section(readings, is_rms: bool, is_dc: bool) -> _Section:
    return _meter_section(readings, is_rms, is_dc)


def _meter_section(readings, is_rms: bool, is_dc: bool) -> _Section:
    s = _Section("Wattmetre Okumaları")
    if is_dc:
        s.text("Wattmetre gerilim bobinindeki gerilim ile akım bobinindeki akımın çarpımını okur: P = V · I.")
    else:
        sym = "Re(V · I*)" if is_rms else "½ · Re(V · I*)"
        s.text("İdeal wattmetrenin akım bobini devreye seri (kısa devre), gerilim bobini paraleldir "
               f"(açık devre); okuma P = {sym}. V = V(V+) {MINUS} V(V{MINUS}), I akım bobininde "
               "I+ → I− yönündedir. Çözücüde akım bobini 0 V'luk bir ölçüm kaynağıyla modellenir.")
    for wid, p, v, i in readings:
        if is_dc:
            s.math(f"{wid}: V = {eng(v.real, 'V')}, I = {eng(i.real, 'A')}  →  P = {eng(p, 'W')}")
        else:
            s.math(f"{wid}: V = {_c(v, 'V')}, I = {_c(i, 'A')}  →  P = {eng(p, 'W')}")
    return s


# ═══════════════════════════════════════════════════════
#  KISA ANLATIM, KONTROL, SONUÇ
# ═══════════════════════════════════════════════════════

def _short_sections(an: ThreePhaseAnalysis, transformer: bool) -> List[_Section]:
    s = _Section("Çözücü Sonuçları")
    why = an.reason or "Devre adım adım anlatım kalıbına uymuyor"
    if transformer:
        why = "Devrede transformatör de var"
    s.note(f"Bu devrede adım adım üç faz anlatımı verilemiyor: {why}. "
           "Aşağıda çözücünün bulduğu sonuçlar gösteriliyor.")
    for ph in PHASES:
        s.math(f"I_{ph} = {_c(an.i_line[ph], 'A')}")
    if an.i_n is not None:
        s.math(f"I_N = I_R + I_S + I_T = {_c(an.i_n, 'A')}")
    if an.i_phase:
        for k in ("RS", "ST", "TR"):
            s.math(f"I_{k} = {_c(an.i_phase[k], 'A')}")
    f_txt = "V·I*" if an.is_rms else "½·V·I*"
    s.text(f"Kaynağın verdiği güç, her faz için S = {f_txt} toplanarak bulunur:")
    s.math(f"P = {eng(an.p, 'W')},  Q = {eng(an.q, 'VAR')},  S = {eng(an.s, 'VA')},  cos φ = {num(an.pf)} "
           f"({_pf_text(an)})")
    return [s]


def _check_section(an: ThreePhaseAnalysis) -> _Section:
    s = _Section("Kontrol")
    s.check("Elle türetilen hat akımları çözücünün (lcapy) sonuçlarıyla uyuşuyor.")
    if an.i_n is not None:
        s.check(f"Nötr akımı I_N = {eng(abs(an.i_n), 'A')}.")
    s.check("Toplam güç, kaynağın verdiği güçle aynı: "
            f"P = {eng(an.p, 'W')}, Q = {eng(an.q, 'VAR')}.")
    return s


def _result_section(an: ThreePhaseAnalysis) -> _Section:
    s = _Section("Sonuç")
    s.result("Hat akımları: " + ", ".join(f"I_{ph} = {_c(an.i_line[ph], 'A')}" for ph in PHASES))
    if an.i_phase:
        s.result("Faz (kol) akımları: " + ", ".join(f"I_{k} = {_c(an.i_phase[k], 'A')}"
                                                    for k in ("RS", "ST", "TR")))
    if an.i_n is not None:
        s.result(f"Nötr akımı: I_N = {_c(an.i_n, 'A')}")
    s.result(f"P = {eng(an.p, 'W')}, Q = {eng(an.q, 'VAR')}, S = {eng(an.s, 'VA')}, "
             f"cos φ = {num(an.pf)} ({_pf_text(an)})")
    if an.aron is not None:
        s.result(f"Aron: P_A = {eng(an.aron[0], 'W')}, P_B = {eng(an.aron[1], 'W')}")
    if an.comp is not None and an.comp.applied:
        s.result(f"Kompanzasyon: Q_C = {eng(an.comp.q_c, 'VAR')}, C_Y = {eng(an.comp.c_y, 'F')}, "
                 f"C_Δ = {eng(an.comp.c_delta, 'F')}")
    return s
