"""
Hata metinlerini öğrenciye Türkçe göstermek için küçük yardımcı.

lcapy, SymPy, NumPy ve Python'un hata iletileri İngilizcedir ve içlerinde "matrix",
"Could not open" gibi öğrencinin anlamayacağı sözler bulunur. Bu modül bir istisnayı
tek bir Türkçe cümleye çevirir:

  1. Bizim kendi Türkçe istisnalarımız (ayrıştırıcı, çözücü, rezonans …) aynen geçer.
  2. Bilinen İngilizce iletiler özel bir Türkçe cümleye eşlenir.
  3. Gerisi kısa ve genel bir Türkçe cümle olur.

Ham istisna her durumda stderr'e yazılır (WPF programı stderr'i geliştirici kaydına alır);
böylece hata ayıklamak için hiçbir şey kaybolmaz.
"""

import os
import re
import sys
import traceback
from typing import Optional

# Kendi Türkçe istisna sınıflarımız (ada göre eşleşir; içe aktarma döngüsü olmasın diye
# sınıflar import edilmez). Bu sınıfların iletisi bizim yazdığımız Türkçe cümledir.
_OWN_EXCEPTION_NAMES = {
    "InfiniteImpedanceError",
    "ResonanceNotApplicable",
    "TransientNotApplicable",
    "NumericAcUnsupported",
    "AnswerParseError",
}

_API_DIR = os.path.normcase(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TURKISH_LETTERS = set("çğıöşüÇĞİÖŞÜ")

GENERIC_TEXT = "beklenmeyen bir sorun oluştu."

# (ham iletide aranacak kalıp, Türkçe cümle) — ilk eşleşen kazanır; küçük harfe çevrilmiş iletide aranır
_KNOWN = [
    (re.compile(r"not invertible|singular|ill-conditioned|matrix is"),
     "devre denklemleri tek bir çözüme varmıyor (devrede kısa devre, çelişkili kaynak ya da "
     "bağlantısız bir bölüm olabilir)."),
    (re.compile(r"unknown component|unknown element|unknown cpt|unknown device"),
     "devrede çözücünün tanımadığı bir eleman var."),
    (re.compile(r"could not open|no such file|cannot open|not found|unable to open"),
     "devre tanımı okunamadı; devrede eksik ya da hatalı bir bağlantı olabilir."),
    (re.compile(r"could not convert|invalid literal|cannot convert|can't convert|not a valid number"),
     "bir değer sayı olarak okunamadı; değerleri kontrol edin (örnek: 4.7k, 100u, 2.5)."),
    (re.compile(r"division by zero|divide by zero|zerodivision|zoo\b|complex infinity"),
     "hesapta sıfıra bölme oluştu; sıfır değerli bir eleman ya da sıfır frekans olabilir."),
    (re.compile(r"\bnan\b|\binf\b|infinity|overflow"),
     "hesapta sonsuz ya da tanımsız bir değer çıktı."),
    (re.compile(r"recursion|maximum depth"),
     "devre bu yöntemle hesaplanamayacak kadar karmaşık."),
    (re.compile(r"freq|omega"),
     "frekans bilgisi eksik ya da geçersiz."),
]


def _raised_in_own_code(exc: BaseException) -> bool:
    """İstisnanın fırlatıldığı en iç çerçeve bu projenin dosyasında mı (kütüphanede değil)?"""
    tb = exc.__traceback__
    if tb is None:
        return False
    while tb.tb_next is not None:
        tb = tb.tb_next
    path = os.path.normcase(os.path.abspath(tb.tb_frame.f_code.co_filename))
    return path.startswith(_API_DIR) and "site-packages" not in path


def is_own_message(exc: BaseException) -> bool:
    """İleti bizim yazdığımız Türkçe bir cümle mi?"""
    if any(c.__name__ in _OWN_EXCEPTION_NAMES for c in type(exc).__mro__):
        return True
    text = str(exc)
    return (_raised_in_own_code(exc) and any(ch in _TURKISH_LETTERS for ch in text))


def is_singular_error(exc: BaseException) -> bool:
    """lcapy/NumPy "devre denklemleri tekil" mi dedi? (Çözücü bu durumu ayrıca açıklar.)"""
    msg = str(exc).lower()
    return "invertible" in msg or "singular" in msg


def log_raw(exc: BaseException, where: str = "") -> None:
    """Ham istisnayı stderr'e yazar (geliştirici kaydı). Asla hata fırlatmaz."""
    try:
        tail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()
        print(f"[çözücü hatası{': ' + where if where else ''}] {tail}", file=sys.stderr, flush=True)
    except Exception:
        pass


def turkish_error(exc: BaseException, where: str = "") -> str:
    """
    İstisnayı öğrenciye gösterilecek tek bir Türkçe cümleye çevirir (küçük harfle başlar,
    noktayla biter; "ℹ Anlatım oluşturulamadı: " gibi bir başlığın ardına eklenir).
    Ham istisna stderr'e yazılır.
    """
    log_raw(exc, where)
    if is_own_message(exc):
        text = str(exc).strip()
        return text if text else GENERIC_TEXT
    low = str(exc).lower()
    for pattern, turkish in _KNOWN:
        if pattern.search(low):
            return turkish
    return GENERIC_TEXT


def english_leak(text: str) -> Optional[str]:
    """Test yardımcısı: metinde öğrencinin görmemesi gereken İngilizce/teknik sözlerden biri varsa onu döndürür."""
    low = text.lower()
    for word in ("unknown", "could not", "invalid literal", "traceback", "error:", "matrix",
                 "not invertible", "singular", "exception", "typeerror", "valueerror",
                 "keyerror", "attributeerror", "sympy", "lcapy", "numpy", "nonetype"):
        if word in low:
            return word
    return None
