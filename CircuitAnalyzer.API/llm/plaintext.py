"""
CircuitAnalyzer API — Model cevabını düz metne çevirme

Dil modelleri formülleri LaTeX ($V = I \times R$) ve Markdown (**kalın**,
### başlık) ile yazmaya eğilimli; uygulama düz metin gösterdiği için bunlar
okunur Unicode metne çevrilir: "V = I × R".
"""

import re

_SYMBOLS = {
    r"\times": "×", r"\cdot": "·", r"\div": "÷", r"\pm": "±", r"\mp": "∓",
    r"\approx": "≈", r"\neq": "≠", r"\ne": "≠", r"\leq": "≤", r"\le": "≤",
    r"\geq": "≥", r"\ge": "≥", r"\to": "→", r"\rightarrow": "→", r"\Rightarrow": "⇒",
    r"\Omega": "Ω", r"\omega": "ω", r"\pi": "π", r"\varphi": "φ", r"\phi": "φ",
    r"\theta": "θ", r"\Delta": "Δ", r"\delta": "δ", r"\mu": "µ", r"\alpha": "α",
    r"\beta": "β", r"\Sigma": "Σ", r"\sum": "Σ", r"\infty": "∞", r"\angle": "∠",
    r"\parallel": "∥", r"\|": "∥", r"\degree": "°", r"\%": "%",
}
_SUPERSCRIPT = str.maketrans("0123456789-+", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺")
_SUBSCRIPT = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")

_TEXT_CMD = re.compile(r"\\(?:text|mathrm|mathbf|textbf|mathit|operatorname)\s*\{([^{}]*)\}")
_FRAC = re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_SQRT = re.compile(r"\\sqrt\s*\{([^{}]*)\}")
_SUP_BRACED = re.compile(r"\^\{([0-9+\-]+)\}")
_SUP_SIMPLE = re.compile(r"\^([0-9])")
_SUB_DIGITS = re.compile(r"_\{([0-9]+)\}|_([0-9]+)")


def _wrap(s: str) -> str:
    s = s.strip()
    return s if re.fullmatch(r"[\w.,·]+", s) else f"({s})"


def to_plain_text(text: str) -> str:
    s = text or ""

    # ── LaTeX ──
    s = s.replace("^\\circ", "°").replace("^{\\circ}", "°").replace("\\circ", "°")
    # Üs/alt simgeler önce: \frac{V_{th}^2}{…} içindeki iç parantezler kalksın
    s = _SUP_BRACED.sub(lambda m: m.group(1).translate(_SUPERSCRIPT), s)
    s = _SUP_SIMPLE.sub(lambda m: m.group(1).translate(_SUPERSCRIPT), s)
    s = _SUB_DIGITS.sub(lambda m: (m.group(1) or m.group(2)).translate(_SUBSCRIPT), s)
    s = re.sub(r"_\{([A-Za-z]+)\}", r"_\1", s)
    for _ in range(3):   # iç içe {…} için birkaç tur
        s = _TEXT_CMD.sub(lambda m: m.group(1), s)
        s = _FRAC.sub(lambda m: f"{_wrap(m.group(1))}/{_wrap(m.group(2))}", s)
        s = _SQRT.sub(lambda m: f"√{_wrap(m.group(1))}", s)
    for cmd in sorted(_SYMBOLS, key=len, reverse=True):
        s = re.sub(re.escape(cmd) + r"(?![A-Za-z])", _SYMBOLS[cmd], s)
    s = re.sub(r"\\left|\\right|\\big|\\Big", "", s)
    s = re.sub(r"\\[,;:! ]|\\quad|\\qquad", " ", s)
    s = _SUP_BRACED.sub(lambda m: m.group(1).translate(_SUPERSCRIPT), s)
    s = _SUP_SIMPLE.sub(lambda m: m.group(1).translate(_SUPERSCRIPT), s)
    s = _SUB_DIGITS.sub(lambda m: (m.group(1) or m.group(2)).translate(_SUBSCRIPT), s)
    s = re.sub(r"\$\$|\$|\\\(|\\\)|\\\[|\\\]", "", s)
    s = re.sub(r"\\([A-Za-z]+)", r"\1", s)        # tanınmayan komut: adını bırak
    s = s.replace("{", "").replace("}", "")

    # ── Markdown ──
    s = s.replace("**", "").replace("__", "").replace("`", "")
    s = re.sub(r"^\s{0,3}#{1,6}\s*", "", s, flags=re.MULTILINE)      # başlıklar
    s = re.sub(r"^(\s*)[*+]\s+", r"\1• ", s, flags=re.MULTILINE)     # madde işaretleri

    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()
