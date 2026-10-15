"""
Logo dosyalarını üretir ("Kitap" logosu, assets/logo.svg ile aynı çizim):
sayfaları devre yolu olan açık bir kitap — programın asıl işi öğretmek.

    python tools/make_icons.py

Üretilenler:
    assets/logo-1024.png, assets/logo-256.png      (README, kurulum)
    CircuitAnalyzer.WPF/Assets/app.ico               (16…256 px, Windows ikonu)
    CircuitAnalyzer.WPF/Assets/logo-128.png          (uygulama içi: başlık, tanıtım)

Küçük boyutlarda (≤ 32 px) sol sayfadaki direnç ayrıntısı kalkar ve çizgiler
kalınlaşır ki 16 px'te de kitap ve devre yolu seçilebilsin. Kenarlar yumuşak
olsun diye her boyut büyük çizilip küçültülür. Gereken tek paket: Pillow.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BG = (29, 29, 31, 255)            # #1D1D1F
BG_EDGE = (58, 58, 60, 255)       # #3A3A3C — koyu görev çubuğunda da kenar seçilsin
PAGE = (255, 255, 255, 255)       # kitap çizgisi
TRACE = (90, 169, 255, 255)       # #5AA9FF — devre yolu

ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def cubic(p0, p1, p2, p3, n=48):
    """Kübik Bézier eğrisinden nokta listesi."""
    pts = []
    for i in range(n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3
        pts.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                    a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return pts


def page_outline(mirror: bool):
    """Sol sayfa: M512 300 C430 250 300 240 210 262 V722 C300 700 430 710 512 760 Z"""
    def m(p):
        return (1024 - p[0], p[1]) if mirror else p
    pts = cubic(m((512, 300)), m((430, 250)), m((300, 240)), m((210, 262)))
    pts += cubic(m((210, 722)), m((300, 700)), m((430, 710)), m((512, 760)))
    pts.append(m((512, 300)))
    return pts


def render(px: int) -> Image.Image:
    ss = 8 if px < 512 else 2
    size = px * ss
    k = size / 1024.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def P(pts):
        return [(x * k, y * k) for x, y in pts]

    def thick(pts, w, color):
        # Her parça ayrı çizgi + her köşede daire: yuvarlak birleşim ve uçlar.
        # (Pillow'un joint="curve" seçeneği kısa parçalı eğrilerde çentik bırakıyor.)
        r = w * k / 2
        width = max(1, round(w * k))
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            d.line([(x0 * k, y0 * k), (x1 * k, y1 * k)], fill=color, width=width)
        for x, y in pts:
            d.ellipse([x * k - r, y * k - r, x * k + r, y * k + r], fill=color)

    small = px <= 32
    edge = 16 if px >= 48 else 24
    d.rounded_rectangle([0, 0, size, size], radius=232 * k, fill=BG_EDGE)
    d.rounded_rectangle([edge * k, edge * k, (1024 - edge) * k, (1024 - edge) * k],
                        radius=(232 - edge) * k, fill=BG)

    page_w = 80 if px <= 16 else 64 if small else 44
    for mirror in (False, True):
        thick(page_outline(mirror), page_w, PAGE)

    trace_w = 72 if px <= 16 else 58 if small else 40
    thick([(600, 420), (720, 420), (720, 560), (610, 560)], trace_w, TRACE)
    dot = 40 if small else 26
    for cx, cy in ((600, 420), (610, 560)):
        d.ellipse([(cx - dot) * k, (cy - dot) * k, (cx + dot) * k, (cy + dot) * k], fill=TRACE)

    if not small:
        # Sol sayfa: bir direnç (kutu içi boş görünsün diye ince çizgi) ve bir yol
        w = 30
        thick([(274, 420), (330, 420)], w, TRACE)
        thick([(442, 420), (462, 420)], w, TRACE)
        d.rounded_rectangle([(330 - w / 2) * k, (394 - w / 2) * k, (442 + w / 2) * k, (446 + w / 2) * k],
                            radius=(12 + w / 2) * k, fill=TRACE)
        d.rounded_rectangle([(330 + w / 2) * k, (394 + w / 2) * k, (442 - w / 2) * k, (446 - w / 2) * k],
                            radius=max(1.0, 12 - w / 2) * k, fill=BG)
        thick([(290, 560), (440, 560)], trace_w, TRACE)

    return img.resize((px, px), Image.LANCZOS)


def main():
    (ROOT / "assets").mkdir(exist_ok=True)
    wpf_assets = ROOT / "CircuitAnalyzer.WPF" / "Assets"
    wpf_assets.mkdir(exist_ok=True)

    render(1024).save(ROOT / "assets" / "logo-1024.png")
    render(256).save(ROOT / "assets" / "logo-256.png")
    render(128).save(wpf_assets / "logo-128.png")

    images = [render(s) for s in ICO_SIZES]
    images[-1].save(wpf_assets / "app.ico", format="ICO",
                    sizes=[(s, s) for s in ICO_SIZES], append_images=images[:-1])
    print("Üretildi:", ", ".join(str(p.relative_to(ROOT)) for p in [
        ROOT / "assets" / "logo-1024.png", ROOT / "assets" / "logo-256.png",
        wpf_assets / "logo-128.png", wpf_assets / "app.ico"]))


if __name__ == "__main__":
    main()
