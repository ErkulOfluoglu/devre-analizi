"""
CircuitAnalyzer API — LLM Düz Metin (Plaintext) Çevirici Testleri

Test edilen modül:
- llm/plaintext.py (to_plain_text)
"""

import pytest

from llm.plaintext import to_plain_text


@pytest.mark.parametrize(
    ("raw_input", "expected_output"),
    [
        (r"Bu yasa, $V = I \times R$ formülüyle", "Bu yasa, V = I × R formülüyle"),
        (r"**Gerilim = Akım $\times$ Direnç**", "Gerilim = Akım × Direnç"),
        (r"$\text{V} = \text{I} \times \text{R}$", "V = I × R"),
        (r"$$I = \frac{V_1 - V_2}{R_1}$$", "I = (V₁ - V₂)/R₁"),
        (r"$P_{max} = \frac{V_{th}^2}{4 R_{th}}$", "P_max = V_th²/(4 R_th)"),
        (r"$V_{th} = 12 \cdot \frac{2}{3}$", "V_th = 12 · 2/3"),
        (r"$Z_C = -j \frac{1}{\omega C}$", "Z_C = -j 1/(ω C)"),
        (r"açı $-72.34^\circ$", "açı -72.34°"),
        (r"$\sqrt{2}$ kat", "√2 kat"),
        ("### Başlık", "Başlık"),
        ("* madde bir", "• madde bir"),
        ("2*3 = 6", "2*3 = 6"),
        (r"$\Omega$ ve $\pi$", "Ω ve π"),
        ("", ""),
        (None, ""),
    ],
)
def test_to_plain_text_expected_conversions(raw_input, expected_output):
    """LaTeX formüllerinin, sembollerin ve Markdown işaretlerinin düz metne çevrilmesi."""
    assert to_plain_text(raw_input) == expected_output


def test_to_plain_text_unchanged_without_formatting():
    """LaTeX veya Markdown içermeyen metnin yalnızca kırpılarak (strip) aynen korunması."""
    text = "Düğüm 2 gerilimi Kirchhoff akım yasası kullanılarak hesaplanır."
    assert to_plain_text(text) == text

    text_with_spaces = "   Devre analizi tamamlandı.   "
    assert to_plain_text(text_with_spaces) == "Devre analizi tamamlandı."


def test_to_plain_text_collapse_blank_lines():
    """Üç veya daha fazla boş satırın tek bir boş satıra daraltılması."""
    text_three_blank_lines = "Birinci paragraf\n\n\n\nİkinci paragraf"
    expected = "Birinci paragraf\n\nİkinci paragraf"
    assert to_plain_text(text_three_blank_lines) == expected

    text_many_blank_lines = "Başlangıç\n\n\n\n\n\nBitiş"
    assert to_plain_text(text_many_blank_lines) == "Başlangıç\n\nBitiş"
