"""
CircuitAnalyzer API — Alıştırma Modu Soru Üretici (Questions) Testleri

Test edilen modül:
- practice/questions.py (build_questions)
- solver/circuit_solver.py (results.practice entegrasyonu)
"""

import pytest

from practice.checker import check_answer

GND = "* GND1 — Referans toprak (Node 0)"


def assert_question_integrity(questions):
    """
    Her sorunun zorunlu alanlarının doluluğunu ve ipuçlarında cevabın
    açıkça verilmediğini (sızdırılmadığını) doğrular.
    """
    for q in questions:
        assert q.description.strip(), f"{q.id} description alanı boş olamaz"
        assert q.hint.strip(), f"{q.id} hint alanı boş olamaz"
        assert q.sign_hint.strip(), f"{q.id} sign_hint alanı boş olamaz"
        r_str = q.expected.rectangular_str
        # 3 karakterden kısa değerler (ör. '3', '8') düğüm numaralarında da geçtiğinden atlanır
        if len(r_str) >= 3:
            assert r_str not in q.hint, f"{q.id} hint beklenen değeri ({r_str}) sızdırıyor: {q.hint}"
            assert r_str not in q.sign_hint, f"{q.id} sign_hint beklenen değeri ({r_str}) sızdırıyor: {q.sign_hint}"
            for alt in q.alternatives:
                assert r_str not in alt.message, (
                    f"{q.id} alternatif mesajı beklenen değeri ({r_str}) sızdırıyor: {alt.message}"
                )


def test_voltage_divider_nodal(solve):
    """Gerilim bölücü devrede düğüm analizi soruları ve beklenen değerlerin doğruluğu."""
    netlist = (
        f"{GND}\n"
        "V1 1 0 DC 12\n"
        "R1 1 2 1k\n"
        "R2 2 0 2k\n"
    )
    results, steps, errors = solve(netlist, mode="DC", analysis_type="NODAL")
    assert not errors

    assert [q.id for q in results.practice] == ["V2", "I_R1", "I_R2", "P_TOTAL"]
    q_map = {q.id: q for q in results.practice}

    # V2 düğüm gerilimi (asıl soru)
    assert q_map["V2"].group == "main"
    assert q_map["V2"].expected.real == pytest.approx(8.0, rel=1e-9)

    # I_R1 eleman akımı (ek soru)
    assert q_map["I_R1"].group == "extra"
    assert q_map["I_R1"].expected.real == pytest.approx(0.004, rel=1e-9)

    # P_TOTAL harcanan toplam güç (ek soru)
    assert q_map["P_TOTAL"].group == "extra"
    assert q_map["P_TOTAL"].expected.real == pytest.approx(0.048, rel=1e-9)
    assert q_map["P_TOTAL"].unit == "W"

    # DC devrede tüm sorular gerçel olmalıdır
    assert all(not q.is_ac for q in results.practice)

    # Asıl sorular kendi rectangular_str değeriyle check_answer'a verildiğinde "correct" dönmelidir
    main_questions = [q for q in results.practice if q.group == "main"]
    for q in main_questions:
        v = check_answer(q, q.expected.rectangular_str)
        assert v.status == "correct"

    assert_question_integrity(results.practice)


def test_thevenin_and_norton_ladder(solve):
    """Merdiven devrede Thevenin ve Norton analiz soruları, eşdeğer empedans ve Pmax."""
    netlist = (
        f"{GND}\n"
        "V1 1 0 DC 12\n"
        "R1 1 2 1k\n"
        "R2 2 0 2k\n"
        "R3 2 3 1k\n"
        "R4 3 0 1k\n"
    )

    # THEVENIN terminaller (3, 0)
    results_th, _, errors_th = solve(
        netlist, mode="DC", analysis_type="THEVENIN", terminals=("3", "0")
    )
    assert not errors_th
    assert [q.id for q in results_th.practice] == ["VTH", "RTH", "PMAX"]
    q_th = {q.id: q for q in results_th.practice}

    assert q_th["VTH"].expected.real == pytest.approx(3.0, rel=1e-9)
    assert q_th["RTH"].expected.real == pytest.approx(625.0, rel=1e-9)
    assert q_th["PMAX"].expected.real == pytest.approx(0.0036, rel=1e-9)  # 9 / (4 * 625)

    # PMAX sorusu 1 alternatif içerir (Vth² / Rth = 0.0144)
    assert len(q_th["PMAX"].alternatives) == 1
    assert q_th["PMAX"].alternatives[0].value.real == pytest.approx(0.0144, rel=1e-9)
    assert_question_integrity(results_th.practice)

    # NORTON aynı terminaller (3, 0)
    results_no, _, errors_no = solve(
        netlist, mode="DC", analysis_type="NORTON", terminals=("3", "0")
    )
    assert not errors_no
    assert [q.id for q in results_no.practice] == ["IN", "RN"]
    q_no = {q.id: q for q in results_no.practice}

    assert q_no["IN"].expected.real == pytest.approx(0.0048, rel=1e-9)
    assert q_no["RN"].expected.real == pytest.approx(625.0, rel=1e-9)
    assert_question_integrity(results_no.practice)


def test_superposition_dc(solve):
    """DC süperpozisyon devresinde kaynak katkıları ve toplam gerilim soruları."""
    netlist = (
        f"{GND}\n"
        "V1 1 0 DC 12\n"
        "R1 1 2 1k\n"
        "R2 2 0 2k\n"
        "R3 2 3 1k\n"
        "V2 3 0 DC 6\n"
    )
    results, _, errors = solve(netlist, mode="DC", analysis_type="SUPERPOSITION")
    assert not errors

    assert [q.id for q in results.practice] == ["V2_V1", "V2_V2", "V2"]
    q_map = {q.id: q for q in results.practice}

    assert q_map["V2_V1"].expected.real == pytest.approx(4.8, rel=1e-9)
    assert q_map["V2_V2"].expected.real == pytest.approx(2.4, rel=1e-9)
    assert q_map["V2"].expected.real == pytest.approx(7.2, rel=1e-9)

    assert q_map["V2_V1"].label == "V₂′"
    assert q_map["V2_V2"].label == "V₂″"
    assert q_map["V2"].label == "V₂"

    # V2_V1 sorusunda toplam değere (7.2) ait alternatif olmalı
    assert any(abs(a.value.real - 7.2) < 1e-6 for a in q_map["V2_V1"].alternatives)

    # Toplam V2 sorusunda tekil katkılara (4.8 ve 2.4) ait alternatifler olmalı
    v2_alt_vals = [a.value.real for a in q_map["V2"].alternatives]
    assert any(abs(v - 4.8) < 1e-6 for v in v2_alt_vals)
    assert any(abs(v - 2.4) < 1e-6 for v in v2_alt_vals)

    assert_question_integrity(results.practice)


def test_superposition_mixed_frequency(solve):
    """Farklı frekanslı (DC + AC) süperpozisyon devresinde toplam soru üretilmemesi."""
    netlist = (
        f"{GND}\n"
        "V1 1 0 DC 12\n"
        "R1 1 2 1k\n"
        "C1 2 0 1u\n"
        "R3 2 3 1k\n"
        "VAC1 3 0 AC_PHASOR(5, 0)\n"
    )
    results, _, _ = solve(
        netlist, mode="AC_PHASOR", frequency=50, analysis_type="SUPERPOSITION"
    )

    # Frekanslar farklı olduğu için toplam soru sorulmaz
    assert [q.id for q in results.practice] == ["V2_V1", "V2_VAC1"]
    q_map = {q.id: q for q in results.practice}

    # V2_V1 DC katkısı
    assert q_map["V2_V1"].is_ac is False
    assert q_map["V2_V1"].frequency is None

    # V2_VAC1 AC katkısı (50 Hz)
    assert q_map["V2_VAC1"].is_ac is True
    assert q_map["V2_VAC1"].frequency == pytest.approx(50.0, rel=1e-9)

    assert_question_integrity(results.practice)


def test_mesh_with_current_source(solve):
    """Akım kaynaklı kolda belirlenmiş çevrenin sorulmaması (yalnızca serbest çevre akımı)."""
    netlist = (
        f"{GND}\n"
        "V1 1 0 DC 10\n"
        "R1 1 2 1k\n"
        "R2 2 0 2k\n"
        "R3 2 3 1k\n"
        "I1 0 3 DC 2m\n"
    )
    results, _, errors = solve(netlist, mode="DC", analysis_type="MESH")
    assert not errors

    main_qs = [q for q in results.practice if q.group == "main"]
    assert len(main_qs) == 1
    assert main_qs[0].id == "MESH1"
    assert main_qs[0].expected.real == pytest.approx(0.002, rel=1e-9)

    # I1 tarafından belirlenen çevre akımı sorulmamalı
    assert "MESH2" not in [q.id for q in results.practice]

    # Ek sorular eleman akımları ve toplam gücü içermelidir
    extra_ids = [q.id for q in results.practice if q.group == "extra"]
    assert {"I_R1", "I_R2", "I_R3", "P_TOTAL"}.issubset(set(extra_ids))

    assert_question_integrity(results.practice)


def test_dc_capacitor_no_current_question(solve):
    """DC devrede kondansatör akımı her zaman 0 olduğundan I_C1 sorusu üretilmez."""
    netlist = (
        f"{GND}\n"
        "V1 1 0 DC 10\n"
        "R1 1 2 1k\n"
        "C1 2 0 1u\n"
        "R2 2 0 1k\n"
    )
    results, _, errors = solve(netlist, mode="DC", analysis_type="NODAL")
    assert not errors

    practice_ids = [q.id for q in results.practice]
    assert "I_C1" not in practice_ids
    assert_question_integrity(results.practice)


def test_all_nodes_known(solve):
    """Tüm düğüm gerilimleri kaynaklarla biliniyorsa asıl soru olarak eleman akımları sorulur."""
    netlist = (
        f"{GND}\n"
        "V1 1 0 DC 12\n"
        "R1 1 0 1k\n"
    )
    results, _, errors = solve(netlist, mode="DC", analysis_type="NODAL")
    assert not errors

    q_map = {q.id: q for q in results.practice}
    assert "I_R1" in q_map
    assert q_map["I_R1"].group == "main"

    assert_question_integrity(results.practice)


def test_ac_rc_circuit(solve):
    """AC RC devresinde fazör düğüm gerilimi ve alternatifli aktif güç soruları."""
    netlist = (
        f"{GND}\n"
        "VAC1 1 0 AC_PHASOR(10, 0)\n"
        "R1 1 2 100\n"
        "C1 2 0 100u\n"
    )
    results, _, errors = solve(
        netlist, mode="AC_PHASOR", frequency=50, analysis_type="NODAL"
    )
    assert not errors

    q_map = {q.id: q for q in results.practice}
    v2 = q_map["V2"]
    assert v2.is_ac is True
    assert v2.frequency == pytest.approx(50.0, rel=1e-9)
    assert v2.expected.magnitude == pytest.approx(3.033, rel=1e-3)
    assert v2.expected.phase_degrees == pytest.approx(-72.34, abs=0.01)

    p_tot = q_map["P_TOTAL"]
    assert p_tot.is_ac is False
    assert p_tot.frequency is None
    assert len(p_tot.alternatives) == 3

    assert_question_integrity(results.practice)
