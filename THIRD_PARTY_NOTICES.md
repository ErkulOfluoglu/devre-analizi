# Üçüncü taraf bileşenler

Devre Analizi'nin kendi kodu [MIT Lisansı](LICENSE) ile dağıtılır.
Kurulum paketi, aşağıdaki açık kaynak bileşenleri **değiştirmeden** içerir.
Her birinin tam lisans metni, kurulumdan sonra program klasöründeki
`licenses\` klasöründe bulunur (`installer/collect_licenses.py` bunları
derleme sırasında otomatik toplar).

## Çalışma zamanları

| Bileşen | Lisans | Kaynak |
|---|---|---|
| .NET 8 çalışma zamanı ve WPF | MIT | https://github.com/dotnet/runtime · https://github.com/dotnet/wpf |
| Python 3.10 (OpenSSL, libffi vb. dahil) | PSF-2.0 (+ dosyada listelenen lisanslar) | https://www.python.org |

## Python çözücüsünün kullandığı paketler

| Paket | Lisans | Kaynak |
|---|---|---|
| **lcapy** | **LGPL-2.1 veya üstü** — bkz. aşağıdaki not | https://github.com/mph-/lcapy |
| SymPy | BSD-3-Clause | https://github.com/sympy/sympy |
| mpmath | BSD-3-Clause | https://github.com/mpmath/mpmath |
| NumPy (paketlenmiş OpenBLAS dahil) | BSD-3-Clause | https://github.com/numpy/numpy |
| NetworkX | BSD-3-Clause | https://github.com/networkx/networkx |
| FastAPI | MIT | https://github.com/fastapi/fastapi |
| Starlette | BSD-3-Clause | https://github.com/encode/starlette |
| Pydantic, pydantic-core | MIT | https://github.com/pydantic/pydantic |
| Uvicorn | BSD-3-Clause | https://github.com/encode/uvicorn |
| AnyIO | MIT | https://github.com/agronholm/anyio |
| sniffio | MIT veya Apache-2.0 | https://github.com/python-trio/sniffio |
| h11 | MIT | https://github.com/python-hyper/h11 |
| httptools | MIT | https://github.com/MagicStack/httptools |
| websockets | BSD-3-Clause | https://github.com/python-websockets/websockets |
| watchfiles | MIT | https://github.com/samuelcolvin/watchfiles |
| python-dotenv | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| PyYAML | MIT | https://github.com/yaml/pyyaml |
| Click | BSD-3-Clause | https://github.com/pallets/click |
| colorama | BSD-3-Clause | https://github.com/tartley/colorama |
| idna | BSD-3-Clause | https://github.com/kjd/idna |
| annotated-types | MIT | https://github.com/annotated-types/annotated-types |
| annotated-doc | MIT | https://github.com/fastapi/annotated-doc |
| typing_extensions | PSF-2.0 | https://github.com/python/typing_extensions |
| typing-inspection | MIT | https://github.com/pydantic/typing-inspection |
| exceptiongroup | MIT | https://github.com/agronholm/exceptiongroup |
| attrs | MIT | https://github.com/python-attrs/attrs |
| packaging | Apache-2.0 veya BSD-2-Clause | https://github.com/pypa/packaging |
| property-cached | BSD-3-Clause | https://github.com/althonos/property-cached |

### lcapy ve LGPL hakkında

lcapy, GNU Lesser General Public License 2.1 (veya üstü) ile lisanslıdır;
tam metin: [licenses/LGPL-2.1.txt](licenses/LGPL-2.1.txt).

- lcapy **hiç değiştirilmeden** kullanılır; yalnızca kütüphane olarak çağrılır.
- Kurulum paketinde lcapy, derlenmiş bir arşivin içine gömülmez;
  `backend\_internal\lcapy\` klasöründe okunabilir `.py` kaynak dosyaları
  olarak durur. Kullanıcı bu klasörü kendi lcapy sürümüyle değiştirebilir.
- lcapy'nin kaynak kodu: https://github.com/mph-/lcapy

## Programla birlikte dağıtılMAYAN isteğe bağlı bileşenler

Yapay zekâ yardımcısı isteğe bağlıdır. Aşağıdakiler kurulum paketinde
**yoktur**; kullanıcı isterse kendisi kurar ve kendi lisans koşulları geçerlidir:

| Bileşen | Lisans |
|---|---|
| Ollama | MIT — https://github.com/ollama/ollama/blob/main/LICENSE |
| Gemma 4 modeli (gemma4:e4b / gemma4:e2b) | Apache 2.0 — https://ai.google.dev/gemma/terms |

Program bu bileşenleri kendisi indirmez veya kurmaz: "Ollama'yı indir" düğmesi
yalnızca resmi indirme sayfasını tarayıcıda açar; model, kullanıcı "Modeli indir"
düğmesine bastığında Ollama'nın kendi indirme mekanizmasıyla indirilir.
