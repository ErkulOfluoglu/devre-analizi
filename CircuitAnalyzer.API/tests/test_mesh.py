"""
CircuitAnalyzer API — Çevre Akımları (Mesh-Current) Yöntemi Testleri

Test edilen modüller:
- solver/mesh.py (analyze_meshes, MeshAnalysis, Mesh)
- explainer/mesh_narrative.py (build_mesh_sections, verify)
- solver/circuit_solver.py (MESH analizi entegrasyonu ve fallback)
"""

import pytest

from explainer.formatting import MINUS
from parser.netlist_parser import parse_netlist
from solver.mesh import analyze_meshes
from tests.conftest import as_complex

GND = "* GND1 — Referans toprak (Node 0)"


def section_by_title(sections, prefix):
    """Başlığı verilen ön ek ile başlayan ilk bölümü bulur."""
    for s in sections:
        if s.title.startswith(prefix):
            return s
    return None


def all_texts(sections):
    """Tüm bölümlerdeki blok metinlerini düz liste olarak döndürür."""
    return [b.text for s in sections for b in s.blocks]


# ═══════════════════════════════════════════════════════
#  1. analyze_meshes TEMEL ÖZELLİKLER VE TOPOLOJİ
# ═══════════════════════════════════════════════════════

def test_analyze_meshes_mesh_count_and_branch_currents(solve):
    """
    1. Bağımsız çevre sayısı formülü: M = eleman − düğüm + 1
       Dört devre tipi için çevre sayısı ve dal akımları doğrulaması:
       a) Gerilim bölücü (divider):
          Eleman: 3 (V1, R1, R2), Düğüm: 3 (0, 1, 2) -> M = 3 - 3 + 1 = 1
          El hesabı: V1=10V, R1=1k, R2=1k -> I = 10 / 2k = 5 mA
       b) Merdiven devresi (ladder):
          Eleman: 5 (V1, R1, R2, R3, R4), Düğüm: 4 (0, 1, 2, 3) -> M = 5 - 4 + 1 = 2
          El hesabı: (R3+R4)||R2 = 2k||2k = 1k. R_toplam = 1k + 1k = 2k.
          I_kaynak = 12 / 2k = 6 mA. V2 = 6V. I_R2 = 3 mA, I_R3 = I_R4 = 3 mA.
       c) Wheatstone köprüsü + kaynak:
          Eleman: 6 (V1, R1, R2, R3, R4, R5), Düğüm: 4 (0, 1, 2, 3) -> M = 6 - 4 + 1 = 3
          El hesabı: 10V kaynak, simetrik 1k dirençler -> V2=5V, V3=5V, I_R5=0 mA.
       d) Paralel dirençler:
          Eleman: 3 (V1, R1, R2), Düğüm: 2 (0, 1) -> M = 3 - 2 + 1 = 2
          El hesabı: V1=10V, R1=1k -> I1=10 mA; R2=2k -> I2=5 mA. Toplam=15 mA.
    """
    circuits = [
        # (netlist, expected_meshes, expected_elements, expected_nodes)
        (
            f"{GND}\nV1 1 0 DC 10\nR1 1 2 1k\nR2 2 0 1k",
            1, 3, 3,
        ),
        (
            f"{GND}\nV1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\nR3 2 3 1k\nR4 3 0 1k",
            2, 5, 4,
        ),
        (
            f"{GND}\nV1 1 0 DC 10\nR1 1 2 1k\nR2 1 3 1k\nR3 2 0 1k\nR4 3 0 1k\nR5 2 3 1k",
            3, 6, 4,
        ),
        (
            f"{GND}\nV1 1 0 DC 10\nR1 1 0 1k\nR2 1 0 2k",
            2, 3, 2,
        ),
    ]

    for netlist, exp_m, exp_e, exp_n in circuits:
        parsed = parse_netlist(netlist)
        ma = analyze_meshes(parsed, is_dc=True, frequency=None)

        assert ma.ok is True
        assert ma.element_count == exp_e
        assert ma.node_count == exp_n
        assert len(ma.meshes) == exp_m
        assert exp_e - exp_n + 1 == exp_m

        # Çözücünün eleman akımları ile çevre analizi dal akımlarını karşılaştır
        res, _, _ = solve(netlist, "DC")
        for eid, i_mesh in ma.branch_currents.items():
            i_solver = as_complex(res.element_currents[eid].value)
            # Çözücü sonuçları 6 ondalığa yuvarlandığından mutlak tolerans 2e-6 kullanılır
            assert abs(i_mesh - i_solver) <= 2e-6


def test_analyze_meshes_removed_notes():
    """
    Uçta kalan (boşta) direnç ve DC'de açık devre kapasitör removed_notes'a eklenir.
    El hesabı:
      R3 düğüm 4'e bağlı, düğüm 4 derecesi 1 -> R3 akım taşımaz, budanır.
      C1 DC analizde açık devre -> çevrelere katılmaz, budanır.
    """
    net = (
        f"{GND}\n"
        "V1 1 0 DC 10\n"
        "R1 1 2 1k\n"
        "R2 2 0 1k\n"
        "R3 2 4 1k\n"
        "C1 2 0 1u\n"
    )
    parsed = parse_netlist(net)
    ma = analyze_meshes(parsed, is_dc=True, frequency=None)

    assert ma.ok is True
    notes_text = " ".join(ma.removed_notes)
    assert "R3 bir ucu boşta kaldığı için akım taşımaz" in notes_text
    assert "C1 DC'de açık devredir" in notes_text


def test_analyze_meshes_non_planar():
    """
    Düzlemsel olmayan devre (K3,3 iki parçalı tam graf):
    6 düğüm (1, 2, 3 vs 0, 4, 5) ve 9 direnç + 1 gerilim kaynağı.
    Kuratowski teoremine göre K3,3 alt grafı içeren devreler düzlemsel değildir.
    Çevre akımları yöntemi yalnızca düzlemsel devrelere uygulanabildiğinden
    ok=False dönmeli ve sebep 'düzlemsel' kelimesini içermelidir.
    """
    net_k33 = (
        f"{GND}\n"
        "V1 1 0 DC 10\n"
        "R0 1 0 1k\n"
        "R1 1 4 1k\n"
        "R2 1 5 1k\n"
        "R3 2 0 1k\n"
        "R4 2 4 1k\n"
        "R5 2 5 1k\n"
        "R6 3 0 1k\n"
        "R7 3 4 1k\n"
        "R8 3 5 1k\n"
    )
    parsed = parse_netlist(net_k33)
    ma = analyze_meshes(parsed, is_dc=True, frequency=None)

    assert ma.ok is False
    assert "düzlemsel" in ma.reason.lower()


def test_analyze_meshes_ac_missing_frequency():
    """
    AC analizde frekans None ve devrede reaktif eleman (kapasitör) varsa:
    Empedans Z_C = 1 / (j·ω·C) hesaplanamaz -> ok=False döner.
    """
    net = f"{GND}\nVAC1 1 0 AC_PHASOR(10, 0)\nC1 1 0 1u\n"
    parsed = parse_netlist(net)
    ma = analyze_meshes(parsed, is_dc=False, frequency=None)

    assert ma.ok is False
    assert "frekans" in ma.reason.lower()


# ═══════════════════════════════════════════════════════
#  2. YÖNLENDİRME (ORIENTATION) VE NODEPOS
# ═══════════════════════════════════════════════════════

def test_mesh_orientation_with_and_without_nodepos():
    """
    2. Çevre akımlarının dönüş yönü ve işaret tutarlılığı:
       Merdiven devresi (ladder):
         V1 1 0 DC 12, R1 1 2 1k, R2 2 0 2k, R3 2 3 1k, R4 3 0 1k
       El hesabı:
         Sol çevre (Çevre 1): V1, R1, R2. I₁ = 6 mA (0.006 A)
         Sağ çevre (Çevre 2): R2, R3, R4. I₂ = 3 mA (0.003 A)

       a) * NODEPOS satırları varsa:
          0: 340 260, 1: 140 120, 2: 340 120, 3: 540 120
          clockwise=True olur ve her iki çevre akımı pozitif çıkar (6 mA ve 3 mA).
       b) Konumlar yoksa:
          clockwise=False olsa bile tüm çevreler karşılıklı tutarlıdır;
          iki çevrenin paylaştığı R2 direncinin bu çevrelerdeki yön işaretleri zıttır.
    """
    ladder_body = (
        "V1 1 0 DC 12\n"
        "R1 1 2 1k\n"
        "R2 2 0 2k\n"
        "R3 2 3 1k\n"
        "R4 3 0 1k\n"
    )
    nodepos = (
        "* NODEPOS 0 340 260\n"
        "* NODEPOS 1 140 120\n"
        "* NODEPOS 2 340 120\n"
        "* NODEPOS 3 540 120\n"
    )

    # a) Konumlu merdiven
    net_with_pos = f"{GND}\n{nodepos}{ladder_body}"
    parsed_pos = parse_netlist(net_with_pos)
    ma_pos = analyze_meshes(parsed_pos, is_dc=True, frequency=None, node_positions=parsed_pos.node_positions)
    assert ma_pos.ok is True
    assert ma_pos.clockwise is True
    assert ma_pos.mesh_currents[0].real == pytest.approx(0.006, abs=1e-6)
    assert ma_pos.mesh_currents[1].real == pytest.approx(0.003, abs=1e-6)

    # b) Konumsuz merdiven
    net_no_pos = f"{GND}\n{ladder_body}"
    ma_no_pos = analyze_meshes(parse_netlist(net_no_pos), is_dc=True, frequency=None)
    assert ma_no_pos.ok is True
    # R2'nin her iki çevredeki işaretini kontrol et
    sign_m1 = ma_no_pos.meshes[0].sign("R2")
    sign_m2 = ma_no_pos.meshes[1].sign("R2")
    assert sign_m1 != 0 and sign_m2 != 0
    assert sign_m1 == -sign_m2


# ═══════════════════════════════════════════════════════
#  3. TÜRKÇE ANLATIM (NARRATIVE) VE ÖZEL DURUMLAR
# ═══════════════════════════════════════════════════════

def test_mesh_narrative_ladder(solve):
    """
    3. Merdiven devresinin MESH anlatımı:
       Bölümler:
         - "Çevreler (Gözler)"
         - "Çevre Denklemleri (KVL)"
         - "Denklemlerin Çözümü"
         - "Eleman Akımları (Çevre Akımlarından)"
       Metin kontrolleri:
         - "çevre sayısı = eleman sayısı − düğüm sayısı + 1 = 5 − 4 + 1 = 2"
         - "Çevre 1: R1·I₁ + R2·(I₁ − I₂) = V1"
         - "Δ = 3·4 − (−2)·(−2) = 8"
         - "I₁ = Δ₁/Δ = 48 / 8 = 6 mA"
         - "I_R2 = I₁ − I₂ = 6 mA − 3 mA = 3 mA  (Düğüm 2 → Düğüm 0)"
       results.meshes:
         2 elemanlı, akımlar sırasıyla 0.006 ve 0.003 A.
    """
    net = (
        f"{GND}\n"
        "* NODEPOS 0 340 260\n"
        "* NODEPOS 1 140 120\n"
        "* NODEPOS 2 340 120\n"
        "* NODEPOS 3 540 120\n"
        "V1 1 0 DC 12\n"
        "R1 1 2 1k\n"
        "R2 2 0 2k\n"
        "R3 2 3 1k\n"
        "R4 3 0 1k\n"
    )
    res, steps, errs = solve(net, "DC", None, "MESH")
    assert not errs

    # Bölüm varlıkları
    assert section_by_title(res.explanation, "Çevreler (Gözler)") is not None
    assert section_by_title(res.explanation, "Çevre Denklemleri (KVL)") is not None
    assert section_by_title(res.explanation, "Denklemlerin Çözümü") is not None
    assert section_by_title(res.explanation, "Eleman Akımları (Çevre Akımlarından)") is not None

    texts = all_texts(res.explanation)
    assert any("çevre sayısı = eleman sayısı − düğüm sayısı + 1 = 5 − 4 + 1 = 2" in t for t in texts)
    assert any("Çevre 1: R1·I₁ + R2·(I₁ − I₂) = V1" in t for t in texts)
    assert any("Δ = 3·4 − (−2)·(−2) = 8" in t for t in texts)
    assert any("I₁ = Δ₁/Δ = 48 / 8 = 6 mA" in t for t in texts)
    assert any("I_R2 = I₁ − I₂ = 6 mA − 3 mA = 3 mA  (Düğüm 2 → Düğüm 0)" in t for t in texts)

    # results.meshes dökümü
    assert len(res.meshes) == 2
    assert res.meshes[0].current.real == pytest.approx(0.006, abs=1e-6)
    assert res.meshes[1].current.real == pytest.approx(0.003, abs=1e-6)


def test_mesh_narrative_current_source_outer_branch(solve):
    """
    Dış kolda akım kaynağı içeren devre:
      V1 1 0 DC 10, R1 1 2 1k, R2 2 0 2k, R3 2 3 1k, I1 0 3 DC 2m + NODEPOS
    El hesabı:
      I1 akımı 0'dan 3'e 2 mA akar.
      Düğüm 3'e giren 2 mA, R3 üzerinden düğüm 2'ye geçer.
      Düğüm 2 KCL: (10 - V2)/1k + 2 mA = V2/2k => 20 - 2·V2 + 4 = V2 => 3·V2 = 24 => V2 = 8 V.
      Düğüm 3 gerilimi: V3 = V2 + 2 mA · 1k = 8 + 2 = 10 V.
      Çevre 2 akımı doğrudan bilinen akım kaynağıdır: I₂ = -2 mA.
      Çevre 1: 3000·I₁ + (-2000)·(-0.002) = 10 => 3000·I₁ = 6 => I₁ = 6 / 3000 = 2 mA.
    """
    net = (
        f"{GND}\n"
        "* NODEPOS 0 340 260\n"
        "* NODEPOS 1 140 120\n"
        "* NODEPOS 2 340 120\n"
        "* NODEPOS 3 540 120\n"
        "V1 1 0 DC 10\n"
        "R1 1 2 1k\n"
        "R2 2 0 2k\n"
        "R3 2 3 1k\n"
        "I1 0 3 DC 2m\n"
    )
    res, steps, errs = solve(net, "DC", None, "MESH")
    assert not errs

    texts = all_texts(res.explanation)
    # KVL bölümünde kaynağın çevre akımının bilindiği belirtilir
    kvl_sec = section_by_title(res.explanation, "Çevre Denklemleri (KVL)")
    assert kvl_sec is not None
    kvl_texts = [b.text for b in kvl_sec.blocks]
    assert any("bu çevrenin akımı doğrudan kaynağın akımıdır" in t for t in kvl_texts)

    # Çözüm bölümünde bilinen akımın yerine konduğu yer alır
    assert any("Çevre 1 denkleminde bilinen akımları yerine koyalım:" in t for t in texts)
    assert any("I₁ = 6 / 3000 = 2 mA" in t for t in texts)

    # Düğüm gerilimleri kontrolü: V2 = 8 V, V3 = 10 V
    assert res.node_voltages["2"].value == pytest.approx(8.0, abs=1e-4)
    assert res.node_voltages["3"].value == pytest.approx(10.0, abs=1e-4)


def test_mesh_narrative_supermesh(solve):
    """
    İki çevre arasında ortak akım kaynağı (Süperçevre / Supermesh):
      V1 1 0 DC 10, R1 1 2 1k, I1 2 3 DC 2m, R2 2 0 2k, R3 3 0 3k, R4 1 3 4k
      + NODEPOS konumları ile I1 iç kola yerleşir.
    El hesabı:
      I1 kaynağı Çevre 2 ve Çevre 3 arasında ortaktır.
      Kaynak gerilimi bilinmediğinden iki çevrenin KVL'si toplanır (süperçevre).
      Kısıt denklemi: I₂ − I₃ = 0.002 A.
      Denklemler birlikte çözülünce çevre akımları bulunur.
      Bulunan dal akımları tam çözücü sonucuyla eşleşir.
    """
    net = (
        f"{GND}\n"
        "* NODEPOS 0 340 260\n"
        "* NODEPOS 1 140 120\n"
        "* NODEPOS 2 340 120\n"
        "* NODEPOS 3 540 120\n"
        "V1 1 0 DC 10\n"
        "R1 1 2 1k\n"
        "I1 2 3 DC 2m\n"
        "R2 2 0 2k\n"
        "R3 3 0 3k\n"
        "R4 1 3 4k\n"
    )
    res, steps, errs = solve(net, "DC", None, "MESH")
    assert not errs

    texts = all_texts(res.explanation)
    assert any("süperçevre" in t.lower() for t in texts)
    assert any("= 0.002 A" in t for t in texts)
    assert any("birlikte çözülünce" in t for t in texts)

    # Dal akımları çözücüyle eşleşmeli
    res_nodal, _, _ = solve(net, "DC", None, "NODAL")
    for eid in ("R1", "R2", "R3", "R4", "V1"):
        i_mesh = as_complex(res.element_currents[eid].value)
        i_nodal = as_complex(res_nodal.element_currents[eid].value)
        assert abs(i_mesh - i_nodal) <= 2e-6


def test_mesh_fallback_non_planar(solve):
    """
    Düzlemsel olmayan devre MESH ile çözülmek istendiğinde:
    - Anlatımda 'çevre akımları yöntemi uygulanamadı' notu yer alır.
    - Düğüm yöntemine dönülür; 'Düğüm Denklemleri (KCL)' bölümü anlatımda kalır.
    - Hata/uyarı listesinde 'ℹ' bilgilendirme mesajı bulunur.
    """
    net_k33 = (
        f"{GND}\n"
        "V1 1 0 DC 10\n"
        "R0 1 0 1k\n"
        "R1 1 4 1k\n"
        "R2 1 5 1k\n"
        "R3 2 0 1k\n"
        "R4 2 4 1k\n"
        "R5 2 5 1k\n"
        "R6 3 0 1k\n"
        "R7 3 4 1k\n"
        "R8 3 5 1k\n"
    )
    res, steps, errors = solve(net_k33, "DC", None, "MESH")

    texts = all_texts(res.explanation)
    assert any("çevre akımları yöntemi uygulanamadı" in t for t in texts)
    assert section_by_title(res.explanation, "Düğüm Denklemleri (KCL)") is not None
    assert any("ℹ" in err and "çevre akımları" in err.lower() for err in errors)


# ═══════════════════════════════════════════════════════
#  4. AC MESH ANALİZİ
# ═══════════════════════════════════════════════════════

def test_ac_mesh(solve):
    """
    4. AC MESH analizi:
       VAC1 1 0 AC_PHASOR(10, 30)
       Z1 1 2 COMPLEX(50, 30)
       C1 2 0 1u
       R2 2 3 100
       R3 3 0 200
       Frekans = 1000 Hz.
       El hesabı:
         ω = 2·π·1000 = 6283.185 rad/s
         Z_C1 = 1 / (j·ω·1e-6) = -j159.155 Ω
         VAC1 = 10∠30° = 8.660 + j5.000 V
         Z1 = 50 + j30 Ω
       Çevre 1 KVL: Z1·I₁ + Z_C1·(I₁ − I₂) = VAC1
       KVL sayısal satırı: '(50 + j30)·I₁' içerir.
       Tüm dal akımları lcapy tam çözücüsüyle eşleşir (abs tolerance 2e-6).
    """
    net_ac = (
        f"{GND}\n"
        "VAC1 1 0 AC_PHASOR(10, 30)\n"
        "Z1 1 2 COMPLEX(50, 30)\n"
        "C1 2 0 1u\n"
        "R2 2 3 100\n"
        "R3 3 0 200\n"
    )
    parsed = parse_netlist(net_ac)
    ma = analyze_meshes(parsed, is_dc=False, frequency=1000)
    assert ma.ok is True

    res, steps, errs = solve(net_ac, "AC_PHASOR", 1000, "MESH")
    assert not errs

    # Dal akımlarının çözücü ile birebir karşılaştırılması
    for eid, i_mesh in ma.branch_currents.items():
        i_solver = as_complex(res.element_currents[eid].value)
        assert abs(i_mesh - i_solver) <= 2e-6

    # KVL sayısal denklem satırında empedans ifadesinin kontrolü
    kvl_sec = section_by_title(res.explanation, "Çevre Denklemleri (KVL)")
    assert kvl_sec is not None
    kvl_texts = [b.text for b in kvl_sec.blocks]
    assert any("(50 + j30)·I₁" in t for t in kvl_texts)
