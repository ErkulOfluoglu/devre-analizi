# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller tarifi: Python çözücüsünü, Python kurulu olmayan bilgisayarlarda
# da çalışan bir klasöre (onedir) paketler → backend\CircuitAnalyzerAPI.exe
#
# Çalıştırma (installer\build.ps1 bunu yapar):
#   pyinstaller installer\backend.spec --noconfirm --distpath build\dist --workpath build\work
#
# Lisans notu (LGPL): lcapy, PYZ arşivine gömülmez; değiştirilmemiş .py
# kaynak dosyaları olarak _internal\lcapy\ klasörüne konur. Böylece kullanıcı
# lcapy'yi kendi sürümüyle değiştirebilir.

import os

from PyInstaller.utils.hooks import collect_submodules

API_DIR = os.path.abspath(os.path.join(SPECPATH, '..', 'CircuitAnalyzer.API'))
ICON = os.path.abspath(os.path.join(SPECPATH, '..', 'CircuitAnalyzer.WPF', 'Assets', 'app.ico'))

# Testlerin tamamı çalışırken bu paketler hiç yüklenmiyor (ölçüldü);
# paketi küçültmek için dışarıda bırakılır.
EXCLUDES = [
    'matplotlib', 'mpl_toolkits', 'pylab', 'scipy', 'IPython', 'PIL',
    'tkinter', '_tkinter', 'pandas', 'pytest', '_pytest', 'httpx', 'jedi',
    'notebook', 'nbformat', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
    'wordcloud', 'zmq', 'lxml', 'jinja2', 'markupsafe', 'pygments', 'rich',
    'markdown_it', 'mdurl', 'psutil', 'pyparsing', 'pkg_resources',
    'setuptools', 'tomli', 'charset_normalizer', 'pyreadline3',
]

a = Analysis(
    [os.path.join(API_DIR, 'run_server.py')],
    pathex=[API_DIR],
    binaries=[],
    datas=[],
    # uvicorn döngü/protokol modüllerini ada göre yükler; statik analiz göremez
    hiddenimports=collect_submodules('uvicorn') + ['lcapy'],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    module_collection_mode={'lcapy': 'py'},
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CircuitAnalyzerAPI',
    icon=ICON,
    console=True,   # pencere WPF tarafında gizlenir (CreateNoWindow)
    upx=False,
    debug=False,
    strip=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name='backend',
)
