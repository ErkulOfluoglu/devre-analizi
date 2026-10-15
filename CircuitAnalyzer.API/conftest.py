"""
API kök conftest'i.

Kökteki test_api.py / test_ac.py / test_solver.py / test_lcapy_api.py
pytest testi DEĞİLDİR: canlı sunucuya (127.0.0.1:8000) istek atan veya
lcapy'yi keşfeden eski betiklerdir ve import anında çalışırlar. pytest
hangi klasörden ya da hangi argümanla çalıştırılırsa çalıştırılsın
bunları toplamasın. Elle çalıştırma: python -X utf8 test_ac.py
"""

collect_ignore = [
    "test_ac.py",
    "test_api.py",
    "test_solver.py",
    "test_lcapy_api.py",
]
