"""
CircuitAnalyzer API — İstek (Request) Şemaları

C# WPF Frontend'ten gelen JSON payload'unu doğrular.

Kullanım:
    POST /analyze
    {
        "netlist": "R1 1 2 1000\nV1 1 0 DC 12",
        "mode": "DC",
        "frequency": null,
        "target_probes": [{"id": "VP1", "type": "V", "target": "2"}],
        "analysis_type": "NODAL",
        "thevenin_terminals": null
    }
"""

from enum import Enum
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, ConfigDict
from pydantic.json_schema import SkipJsonSchema
from models.response import PracticeQuestion


# ═══════════════════════════════════════════════════════
#  ENUM TİPLERİ
# ═══════════════════════════════════════════════════════

class AnalysisMode(str, Enum):
    """
    Devre analiz modu.

    DC:        Doğru akım — kapasitörler açık devre, bobinler kısa devre.
    AC_TIME:   Alternatif akım zaman alanı — v(t) = Vp·sin(2πft + φ)
    AC_PHASOR: Alternatif akım fazör alanı — V = Vm∠φ° (frekans alanı)
    """
    DC = "DC"
    AC_TIME = "AC_TIME"
    AC_PHASOR = "AC_PHASOR"


class ValueDisplay(str, Enum):
    """
    AC büyüklüklerin gösterim tabanı.

    PEAK: Tepe (maksimum) değer — V = Vm∠φ, S = ½·V·I*
    RMS:  Etkin (RMS) değer     — V = V_rms∠φ, S = V·I*
    """
    PEAK = "PEAK"
    RMS = "RMS"


class AnalysisType(str, Enum):
    """
    Çözüm yöntemi.

    NODAL:    Düğüm gerilimi analizi (KCL tabanlı)
    MESH:     Çevre akımı analizi (KVL tabanlı)
    THEVENIN: Thevenin eşdeğer devresi (Vth + Zth)
    NORTON:   Norton eşdeğer devresi (In + Zn)
    SUPERPOSITION: Süperpozisyon — her bağımsız kaynağın etkisi ayrı ayrı
              (kendi frekansında) bulunup toplanır; farklı frekanslı
              kaynaklar zaman domeninde toplanır
    MILLMAN:  Millman teoremi — iki ana düğüm arasındaki paralel kollar (yalnızca DC)
    SOURCE_TRANSFORM: Kaynak dönüşümü — seçilen iki terminalden Thevenin/Norton eşdeğerine
              gerilim↔akım kaynağı dönüşümleriyle ulaşılır (yalnızca DC)
    TRANSIENT: Geçici durum (Faz 2) — anahtarlı, tek C ya da tek L içeren DC devrede
              x(t) = x(∞) + [x(0) − x(∞)]·e^(−t/τ); sonuç yanıtın 'transient' alanında

    Not: 'thevenin_terminals' alanı THEVENIN, NORTON ve SOURCE_TRANSFORM analizi için
    hedef port (terminal çifti) tanımlamasında ortak kullanılır.
    """
    NODAL = "NODAL"
    MESH = "MESH"
    THEVENIN = "THEVENIN"
    NORTON = "NORTON"
    SUPERPOSITION = "SUPERPOSITION"
    MILLMAN = "MILLMAN"
    SOURCE_TRANSFORM = "SOURCE_TRANSFORM"
    TRANSIENT = "TRANSIENT"


# ═══════════════════════════════════════════════════════
#  ALT MODELLER
# ═══════════════════════════════════════════════════════

class ProbeTarget(BaseModel):
    """
    Ölçüm probu hedefi.

    Gerilim probu (V): Bir düğümün GND'ye göre gerilimini ölçer.
    Akım probu (I):    Bir eleman üzerinden geçen akımı ölçer.

    Örnekler:
        {"id": "VP1", "type": "V", "target": "2"}        → V(Node 2)
        {"id": "IP1", "type": "I", "target": "R1"}       → I(R1)
    """
    id: str = Field(
        ...,
        description="Prob kimliği (ör: VP1, IP1)",
        examples=["VP1"],
    )
    type: Literal["V", "I"] = Field(
        ...,
        description="Prob ölçüm türü: 'V'=Gerilim probu, 'I'=Akım probu",
        examples=["V"],
    )
    target: str = Field(
        ...,
        description="Ölçüm hedefi: Gerilim probu için düğüm numarası (ör: '2'), akım probu için eleman ID'si (ör: 'R1')",
        examples=["2"],
    )


class TheveninTerminals(BaseModel):
    """
    Thevenin / Norton eşdeğer devresi için terminal çifti.

    ★ Thevenin / Norton Teoremi:
    Herhangi bir doğrusal devrenin iki terminali arasındaki
    davranış, Thevenin (Vth + Zth) veya Norton (In + Zn)
    eşdeğeri ile modellenebilir.

    Önemli: Eşdeğer devre TEK bir noktaya değil, İKİ düğüm
    arasındaki bir PORT'a (terminal çiftine) göre hesaplanır.

    Örnek:
        {"node_positive": "2", "node_negative": "0"}
        → Node 2 ile GND (Node 0) arasındaki eşdeğer devre
    """
    node_positive: str = Field(
        ...,
        description="Pozitif terminal düğüm numarası (ör: '2')",
        examples=["2"],
    )
    node_negative: str = Field(
        default="0",
        description="Negatif terminal düğüm numarası (varsayılan: '0' = GND)",
        examples=["0"],
    )


# ═══════════════════════════════════════════════════════
#  ÖĞRETİCİ / TEST PAYLOAD ÖRNEKLERİ
# ═══════════════════════════════════════════════════════

ANALYSIS_REQUEST_EXAMPLES = {
    "dc_nodal": {
        "summary": "DC Gerilim Bölücü — Düğüm Analizi (NODAL)",
        "description": "12V DC kaynak ve gerilim bölücü dirençler ile düğüm gerilimleri analizi ve V(2) prob ölçümü.",
        "value": {
            "netlist": (
                "V1 1 0 DC 12\n"
                "R1 1 2 1k\n"
                "R2 2 0 2k\n"
                "* GND1 — Referans toprak (Node 0)\n"
                "* PROBE VP1 V(2)"
            ),
            "mode": "DC",
            "frequency": None,
            "target_probes": [
                {"id": "VP1", "type": "V", "target": "2"}
            ],
            "analysis_type": "NODAL",
            "thevenin_terminals": None,
        },
    },
    "dc_dependent": {
        "summary": "DC Bağımlı Kaynak — Gerilim Kontrollü Gerilim Kaynağı (GKGK)",
        "description": (
            "E1 kaynağı R2 direncinin gerilimini 3 ile çarpıp 3 numaralı düğüme uygular: "
            "E1 3 0 V(R2) 3. Akım kontrollü kaynaklar için H1/F1 n+ n- I(R2) k, gerilim "
            "kontrollü akım kaynağı için G1 n+ n- V(R2) k yazılır. V(-R2) / I(-R2) "
            "kontrol büyüklüğünün işaretini çevirir. Beklenen: V(2) = 6.667 V, V(3) = 20 V."
        ),
        "value": {
            "netlist": (
                "V1 1 0 DC 10\n"
                "R1 1 2 2\n"
                "R2 2 0 4\n"
                "E1 3 0 V(R2) 3\n"
                "R3 3 0 6\n"
                "* GND1 — Referans toprak (Node 0)"
            ),
            "mode": "DC",
            "frequency": None,
            "target_probes": None,
            "analysis_type": "NODAL",
            "thevenin_terminals": None,
        },
    },
    "ac_phasor": {
        "summary": "AC Alçak Geçiren RC Filtre (50 Hz) — Fazör Analizi",
        "description": "50 Hz sinüzoidal kaynak altında RC devresinin fazör (frekans alanı) analizi.",
        "value": {
            "netlist": (
                "VAC1 1 0 AC_PHASOR(10, 0)\n"
                "R1 1 2 100\n"
                "C1 2 0 100u\n"
                "* GND1 — Referans toprak (Node 0)"
            ),
            "mode": "AC_PHASOR",
            "frequency": 50.0,
            "target_probes": None,
            "analysis_type": "NODAL",
            "thevenin_terminals": None,
        },
    },
    "ac_thevenin": {
        "summary": "AC Thevenin Eşdeğeri (1000 Hz) — Düğüm 2-3 Arası",
        "description": "1000 Hz frekansta karmaşık empedanslı devrenin düğüm 2 ve 3 terminalleri arasındaki Thevenin eşdeğeri.",
        "value": {
            "netlist": (
                "VAC1 1 0 AC_PHASOR(10, 30)\n"
                "Z1 1 2 COMPLEX(50, 30)\n"
                "C1 2 0 1u\n"
                "R2 2 3 100\n"
                "R3 3 0 200\n"
                "* GND1 — Referans toprak (Node 0)"
            ),
            "mode": "AC_PHASOR",
            "frequency": 1000.0,
            "target_probes": None,
            "analysis_type": "THEVENIN",
            "thevenin_terminals": {
                "node_positive": "2",
                "node_negative": "3",
            },
        },
    },
    "dc_norton": {
        "summary": "DC Norton Eşdeğeri — Düğüm 2 ile GND Arası",
        "description": "DC gerilim bölücü devresinin düğüm 2 ve GND (0) arasındaki Norton eşdeğer devresi (In ve Zn).",
        "value": {
            "netlist": (
                "V1 1 0 DC 12\n"
                "R1 1 2 1k\n"
                "R2 2 0 2k\n"
                "* GND1 — Referans toprak (Node 0)\n"
                "* PROBE VP1 V(2)"
            ),
            "mode": "DC",
            "frequency": None,
            "target_probes": None,
            "analysis_type": "NORTON",
            "thevenin_terminals": {
                "node_positive": "2",
                "node_negative": "0",
            },
        },
    },
}


# ═══════════════════════════════════════════════════════
#  ANA İSTEK MODELİ
# ═══════════════════════════════════════════════════════

class AnalysisRequest(BaseModel):
    """
    Devre analizi isteği — C# Frontend → Python Backend.

    Tam JSON örneği:
    {
        "netlist": "R1 1 2 1000\\nR2 2 0 2000\\nV1 1 0 DC 12\\n* PROBE VP1 V(2)",
        "mode": "DC",
        "frequency": null,
        "target_probes": [
            {"id": "VP1", "type": "V", "target": "2"}
        ],
        "analysis_type": "NODAL",
        "thevenin_terminals": null
    }
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [ex["value"] for ex in ANALYSIS_REQUEST_EXAMPLES.values()]
        }
    )

    netlist: str = Field(
        ...,
        description="C#'tan gelen SPICE Netlist metni (satırlar \\n ile ayrılır, ör: 'R1 1 2 1000')",
        min_length=1,
        examples=[
            "V1 1 0 DC 12\nR1 1 2 1k\nR2 2 0 2k\n* GND1 — Referans toprak (Node 0)\n* PROBE VP1 V(2)"
        ],
    )

    mode: AnalysisMode = Field(
        ...,
        description="Analiz çalışma modu: DC (doğru akım), AC_TIME (zaman alanı AC) veya AC_PHASOR (fazör alanı AC)",
        examples=["DC"],
    )

    frequency: Optional[float] = Field(
        default=None,
        description="AC modları için global devre frekansı (Hz). DC analizinde None olmalıdır.",
        ge=0,
        examples=[50.0],
    )

    target_probes: Optional[List[ProbeTarget]] = Field(
        default=None,
        description="Ölçüm probu hedefleri listesi. Netlist'teki * PROBE satırlarından otomatik ayrıştırılabilir veya C# tarafından gönderilebilir.",
        examples=[[{"id": "VP1", "type": "V", "target": "2"}]],
    )

    analysis_type: AnalysisType = Field(
        default=AnalysisType.NODAL,
        description="Çözüm yöntemi: NODAL (Düğüm gerilimleri), MESH (Çevre akımları), THEVENIN (Thevenin eşdeğeri), NORTON (Norton eşdeğeri), SUPERPOSITION, MILLMAN (Millman teoremi), SOURCE_TRANSFORM (kaynak dönüşümü) veya TRANSIENT (anahtarlı RC/RL geçici durum)",
        examples=["NODAL"],
    )

    thevenin_terminals: Optional[TheveninTerminals] = Field(
        default=None,
        description="Thevenin, Norton veya kaynak dönüşümü analizi yapılırken eşdeğer devrenin hesaplanacağı iki terminal düğümü.",
        examples=[{"node_positive": "2", "node_negative": "0"}],
    )

    value_display: SkipJsonSchema[ValueDisplay] = Field(
        default=ValueDisplay.PEAK,
        description="AC büyüklüklerin gösterim tabanı: 'PEAK' (tepe değer, varsayılan) veya 'RMS' (etkin değer).",
        examples=["PEAK"],
    )


# ═══════════════════════════════════════════════════════
#  ALIŞTIRMA MODU
# ═══════════════════════════════════════════════════════

class AnswerCheckItem(BaseModel):
    """Bir soru ve öğrencinin yazdığı cevap."""
    question: PracticeQuestion = Field(
        ..., description="/analyze yanıtındaki results.practice listesinden soru")
    answer: str = Field(
        default="", description="Öğrencinin yazdığı cevap (ör: '4 mA', '3.03∠-72.3')")


class AnswerCheckRequest(BaseModel):
    """POST /practice/check isteği."""
    items: List[AnswerCheckItem] = Field(..., description="Kontrol edilecek cevaplar")


# ═══════════════════════════════════════════════════════
#  YEREL YAPAY ZEKÂ (OLLAMA)
# ═══════════════════════════════════════════════════════

class ChatTurn(BaseModel):
    """Önceki bir soru ya da cevap."""
    role: Literal["user", "assistant"] = Field(..., description="user: öğrenci, assistant: model")
    content: str = Field(..., max_length=4000, description="Mesaj metni")


class LlmPullRequest(BaseModel):
    """POST /llm/pull — model indirmeyi başlat."""
    model: Optional[str] = Field(
        default=None, description="İndirilecek model; boşsa bu bilgisayarın belleğine göre önerilen model")


class LlmAskRequest(AnalysisRequest):
    """
    POST /llm/ask — çözülmüş devre hakkında soru.

    Devre bilgileri /analyze ile aynıdır; sunucu devreyi yeniden çözüp
    modele doğrulanmış anlatımı verir (istemci sonuç göndermez).
    """
    question: str = Field(..., min_length=1, max_length=1000, description="Öğrencinin sorusu")
    model: Optional[str] = Field(default=None, description="Ollama model adı; boşsa otomatik seçilir")
    history: List[ChatTurn] = Field(default_factory=list, description="Önceki soru-cevaplar (en eski önce)")
    practice: bool = Field(
        default=False, description="Alıştırma sürüyor mu — True ise model sonuçları görmez, cevap sayıları gizlenir")
    practice_questions: List[PracticeQuestion] = Field(
        default_factory=list, description="Alıştırma soruları (cevap sızıntısını engellemek için)")

