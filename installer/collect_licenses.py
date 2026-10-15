"""
Kurulum paketine giren her açık kaynak bileşenin lisans metnini
<hedef>\\licenses\\ klasörüne kopyalar.

    python installer\\collect_licenses.py <hedef_klasör> [<dotnet_kök_klasörü>]

Liste, PyInstaller paketinin içinde gerçekten bulunan dağıtımlardır
(build\\work\\backend\\PYZ-00.toc incelenerek çıkarıldı). Yeni bir paket
eklenirse buraya da eklenmeli; eksik lisans dosyası derlemeyi durdurur.
"""

import re
import shutil
import sys
from importlib import metadata
from pathlib import Path

# Dağıtım adı → lisans (THIRD_PARTY_NOTICES.md ile aynı)
PYTHON_DISTS = {
    "fastapi": "MIT",
    "starlette": "BSD-3-Clause",
    "pydantic": "MIT",
    "pydantic-core": "MIT",
    "uvicorn": "BSD-3-Clause",
    "lcapy": "LGPL-2.1-or-later",
    "sympy": "BSD-3-Clause",
    "mpmath": "BSD-3-Clause",
    "numpy": "BSD-3-Clause (+ paketlenmiş OpenBLAS vb., LICENSE.txt içinde)",
    "networkx": "BSD-3-Clause",
    "anyio": "MIT",
    "sniffio": "MIT veya Apache-2.0",
    "h11": "MIT",
    "httptools": "MIT",
    "websockets": "BSD-3-Clause",
    "watchfiles": "MIT",
    "python-dotenv": "BSD-3-Clause",
    "PyYAML": "MIT",
    "click": "BSD-3-Clause",
    "colorama": "BSD-3-Clause",
    "idna": "BSD-3-Clause",
    "annotated-types": "MIT",
    "annotated-doc": "MIT",
    "typing_extensions": "PSF-2.0",
    "typing-inspection": "MIT",
    "exceptiongroup": "MIT",
    "attrs": "MIT",
    "packaging": "Apache-2.0 veya BSD-2-Clause",
    "property-cached": "BSD-3-Clause",
}

LICENSE_RE = re.compile(r"(LICEN[CS]E|COPYING|NOTICE|AUTHORS)", re.IGNORECASE)


def copy_python_licenses(dest: Path) -> list[str]:
    lines = []
    for dist, lic in PYTHON_DISTS.items():
        files = [f for f in (metadata.files(dist) or [])
                 if LICENSE_RE.search(f.name) and ".dist-info" in str(f)]
        if not files:
            raise SystemExit(f"[HATA] {dist} için lisans dosyası bulunamadı")
        version = metadata.version(dist)
        target = dest / "python" / f"{dist}-{version}"
        target.mkdir(parents=True, exist_ok=True)
        for f in files:
            # dist-info altındaki göreli yolu koru (ör. licenses/vendor/llhttp/LICENSE
            # ile licenses/LICENSE aynı ada sahip; biri ötekini ezmesin)
            rel = Path(*f.parts[1:])
            (target / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f.locate(), target / rel)
        lines.append(f"{dist} {version} — {lic}")
    return lines


def copy_runtime_licenses(dest: Path, dotnet_root: Path | None) -> list[str]:
    lines = []
    # Python çalışma zamanı (python310.dll vb.) — PSF lisansı
    py_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not py_license.exists():
        raise SystemExit(f"[HATA] Python lisansı bulunamadı: {py_license}")
    shutil.copyfile(py_license, dest / "Python-LICENSE.txt")
    lines.append(f"Python {sys.version.split()[0]} — PSF-2.0 (Python-LICENSE.txt; "
                 "OpenSSL, libffi vb. lisansları da bu dosyadadır)")

    # .NET çalışma zamanı (uygulama kendi içinde .NET ile gelir) — MIT
    if dotnet_root is not None:
        for name in ("LICENSE.txt", "ThirdPartyNotices.txt"):
            src = dotnet_root / name
            if not src.exists():
                raise SystemExit(f"[HATA] .NET lisans dosyası bulunamadı: {src}")
            shutil.copyfile(src, dest / f"dotnet-{name}")
        lines.append(".NET çalışma zamanı ve WPF — MIT (dotnet-LICENSE.txt, "
                     "dotnet-ThirdPartyNotices.txt)")
    return lines


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    dest = Path(sys.argv[1]) / "licenses"
    dotnet_root = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    lines = copy_runtime_licenses(dest, dotnet_root) + copy_python_licenses(dest)
    index = dest / "OKUBENI.txt"
    index.write_text(
        "Bu klasörde, Devre Analizi ile birlikte dağıtılan açık kaynak\n"
        "bileşenlerin lisans metinleri bulunur.\n\n"
        "lcapy (LGPL-2.1 veya üstü) değiştirilmeden kullanılır ve\n"
        "backend\\_internal\\lcapy\\ klasöründe .py kaynak dosyaları olarak\n"
        "durur; dilerseniz kendi lcapy sürümünüzle değiştirebilirsiniz.\n"
        "Kaynak kodu: https://github.com/mph-/lcapy\n\n"
        + "\n".join(lines) + "\n",
        encoding="utf-8")
    print(f"{len(lines)} bileşenin lisansı kopyalandı → {dest}")


if __name__ == "__main__":
    main()
