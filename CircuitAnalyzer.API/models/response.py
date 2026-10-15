"""
CircuitAnalyzer API — Yanıt (Response) Şemaları

Python backend'in C# Frontend'e döndürdüğü yapılandırılmış çıktı.

★ Halüsinasyon Önleme Stratejisi:
   solution_steps alanı, LLM'in kendi matematik üretmesini önler.
   AI bu adımları okuyup pedagojik dille öğrenciye anlatır —
   tüm denklemler ve sonuçlar SymPy/lcapy'den gelir.
"""

from typing import Optional, List, Dict, Any, Union, Literal
from pydantic import BaseModel, Field, ConfigDict


# ═══════════════════════════════════════════════════════
#  DEĞER TİPLERİ
# ═══════════════════════════════════════════════════════

class ComplexNumber(BaseModel):
    """
    Karmaşık sayı gösterimi — AC analiz sonuçları için.

    İki form arasında tam dönüşüm sağlar:
        Dikdörtgensel: Z = a + jb
        Kutupsal:      Z = r∠θ°

    Dönüşüm formülleri:
        r = √(a² + b²)       θ = atan2(b, a) × 180/π
        a = r·cos(θ·π/180)   b = r·sin(θ·π/180)
    """
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "real": 3.0,
                    "imaginary": 4.0,
                    "magnitude": 5.0,
                    "phase_degrees": 53.1301,
                    "rectangular_str": "3+j4",
                    "polar_str": "5∠53.13°",
                }
            ]
        }
    )

    real: float = Field(..., description="Reel kısım (a)")
    imaginary: float = Field(..., description="Sanal kısım (b)")
    magnitude: float = Field(..., description="Büyüklük: |Z| = √(a²+b²)")
    phase_degrees: float = Field(..., description="Faz açısı (derece): θ = atan2(b,a)")
    rectangular_str: str = Field(..., description="Dikdörtgensel gösterim: '50+j30'")
    polar_str: str = Field(..., description="Kutupsal gösterim: '58.31∠30.96°'")


# ═══════════════════════════════════════════════════════
#  SONUÇ BİLEŞENLERİ
# ═══════════════════════════════════════════════════════

class NodeVoltage(BaseModel):
    """
    Düğüm gerilimi sonucu.

    DC modda: saf float (ör: 6.0 V)
    AC modda: ComplexNumber (ör: 7.07+j7.07 V = 10∠45° V)
    """
    value: Union[float, ComplexNumber] = Field(
        ..., description="Gerilim değeri (DC: float, AC: karmaşık)")
    unit: str = Field(default="V", description="Birim (Volt)")
    label: Optional[str] = Field(
        default=None, description="Düğüm etiketi (ör: Düğüm 0 için 'GND')")


class ElementCurrent(BaseModel):
    """
    Eleman akımı sonucu.

    direction alanı pasif işaret kuralına (PSC) göre akım yönünü belirtir:
        "1→2" = node_positive'den node_negative'e doğru
    """
    value: Union[float, ComplexNumber] = Field(
        ..., description="Akım değeri (DC: float, AC: karmaşık)")
    unit: str = Field(default="A", description="Birim (Amper)")
    direction: str = Field(
        ..., description="Akım yönü (ör: '1→2')")


class ProbeResult(BaseModel):
    """Ölçüm probu sonucu — C#'taki TestProbe elemanının cevabı."""
    probe_id: str = Field(..., description="Prob kimliği (ör: VP1)")
    type: str = Field(..., description="V=Gerilim, I=Akım")
    value: Union[float, ComplexNumber] = Field(
        ..., description="Ölçüm sonucu")
    unit: str = Field(..., description="Birim (V veya A)")


class TheveninResult(BaseModel):
    """
    Thevenin eşdeğer devresi sonucu.

    İki terminal (port) arasındaki devrenin eşdeğeri:
        Vth: Açık devre gerilimi (Open Circuit Voltage)
        Zth: Thevenin empedansı (tüm bağımsız kaynaklar sıfırlanır)

    Thevenin Eşdeğer Devre:
        ┌──── Zth ────┐
        │              │
       (+)            (+)
       Vth        Terminal Çifti
       (−)            (−)
        │              │
        └──────────────┘
    """
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "vth": {
                        "real": 6.0,
                        "imaginary": 0.0,
                        "magnitude": 6.0,
                        "phase_degrees": 0.0,
                        "rectangular_str": "6",
                        "polar_str": "6∠0°",
                    },
                    "zth": {
                        "real": 666.67,
                        "imaginary": 0.0,
                        "magnitude": 666.67,
                        "phase_degrees": 0.0,
                        "rectangular_str": "666.67",
                        "polar_str": "666.67∠0°",
                    },
                    "node_positive": "2",
                    "node_negative": "0",
                }
            ]
        }
    )

    vth: ComplexNumber = Field(
        ..., description="Thevenin gerilimi (Vth)")
    zth: ComplexNumber = Field(
        ..., description="Thevenin empedansı (Zth)")
    node_positive: str = Field(
        ..., description="Pozitif terminal düğümü")
    node_negative: str = Field(
        ..., description="Negatif terminal düğümü")


class NortonResult(BaseModel):
    """
    Norton eşdeğer devresi sonucu — Thevenin'in dual'i.

        In: Kısa devre akımı (Short Circuit Current) — terminaller
            kısa devre edildiğinde (+)'dan (−)'ye dış yoldan akan akım.
        Zn: Norton empedansı = Zth (kaynaklar sıfırlanmış port empedansı)
        Yn: Norton admitansı = 1 / Zn

    Thevenin ↔ Norton dönüşümü:
        In = Vth / Zth      Zn = Zth

    Norton Eşdeğer Devre (akım kaynağı (+) terminale doğru akıtır):
        ┌───────┬───────┐
        │       │       │
       (↑)In   Zn     (+)
        │       │   Terminal Çifti
        │       │     (−)
        └───────┴───────┘
    """
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "i_n": {
                        "real": 0.009,
                        "imaginary": 0.0,
                        "magnitude": 0.009,
                        "phase_degrees": 0.0,
                        "rectangular_str": "0.009",
                        "polar_str": "0.009∠0°",
                    },
                    "z_n": {
                        "real": 666.67,
                        "imaginary": 0.0,
                        "magnitude": 666.67,
                        "phase_degrees": 0.0,
                        "rectangular_str": "666.67",
                        "polar_str": "666.67∠0°",
                    },
                    "y_n": {
                        "real": 0.0015,
                        "imaginary": 0.0,
                        "magnitude": 0.0015,
                        "phase_degrees": 0.0,
                        "rectangular_str": "0.0015",
                        "polar_str": "0.0015∠0°",
                    },
                    "node_positive": "2",
                    "node_negative": "0",
                }
            ]
        }
    )

    i_n: ComplexNumber = Field(
        ..., description="Norton akımı (In) — kısa devre akımı")
    z_n: Optional[ComplexNumber] = Field(
        default=None,
        description="Norton empedansı (Zn = Zth). Yn = 0 ise sonsuzdur ve null döner.")
    y_n: ComplexNumber = Field(
        ..., description="Norton admitansı (Yn = 1/Zn), birim: S (Siemens)")
    node_positive: str = Field(
        ..., description="Pozitif terminal düğümü")
    node_negative: str = Field(
        ..., description="Negatif terminal düğümü")


class SourceContribution(BaseModel):
    """Süperpozisyon: yalnızca bir kaynak aktifken bulunan değerler."""
    source_id: str = Field(..., description="Aktif kaynağın kimliği (ör: V1, I1)")
    frequency: Optional[float] = Field(
        default=None, description="Kaynağın frekansı (Hz); DC kaynak için null")
    zeroed_sources: List[str] = Field(
        default_factory=list,
        description="Sıfırlanan diğer kaynaklar ve nasıl sıfırlandıkları")
    node_voltages: Dict[str, ComplexNumber] = Field(
        default_factory=dict, description="Bu kaynağın düğüm gerilimlerine katkısı")
    element_currents: Dict[str, ComplexNumber] = Field(
        default_factory=dict, description="Bu kaynağın eleman akımlarına katkısı")
    error: Optional[str] = Field(
        default=None, description="Alt devre çözülemediyse sebebi")


class MeshInfo(BaseModel):
    """Çevre akımları yönteminde bir çevre (göz)."""
    index: int = Field(..., description="Çevre numarası (I₁ için 1)")
    current: ComplexNumber = Field(..., description="Çevre akımı (A)")
    nodes: List[str] = Field(
        ..., description="Çevrenin dolaştığı düğümler (ilk düğüm sonda tekrar eder)")
    elements: List[str] = Field(
        ..., description="Çevredeki elemanlar (dolaşma sırasıyla)")


class ExplanationBlock(BaseModel):
    """
    Anlatımın tek bir parçası.

    kind:
        text   → düz açıklama paragrafı
        math   → denklem / formül satırı (eşit aralıklı yazı tipiyle gösterilir)
        result → bölümün vardığı sonuç (vurgulanır)
        note   → ek bilgi / ipucu
        check  → doğrulama (✓) satırı
    """
    kind: Literal["text", "math", "result", "note", "check"] = Field(
        ..., description="Blok türü: text, math, result, note veya check")
    text: str = Field(..., description="Blok metni (Türkçe; formüller düz metin)")


class ExplanationSection(BaseModel):
    """Anlatımın bir bölümü (ör: 'Düğüm Denklemleri (KCL)')."""
    title: str = Field(..., description="Bölüm başlığı")
    blocks: List[ExplanationBlock] = Field(
        default_factory=list, description="Bölümün sıralı içerik blokları")


class SeriesParallelReduction(BaseModel):
    """
    Tek bir seri/paralel indirgeme adımı (topoloji analizi).

    Örnek: R1 ∥ R2 → Req1 = R1·R2/(R1+R2) = 666.7 Ω
    """
    type: Literal["series", "parallel"] = Field(
        ..., description="Bağlantı tipi: 'series' (seri) veya 'parallel' (paralel)")
    elements: List[str] = Field(
        ..., description="Birleştirilen iki kol (orijinal eleman veya önceki eşdeğer, ör: ['R1', 'Req1'])")
    result_name: str = Field(
        ..., description="Oluşan eşdeğer kolun adı (ör: Req1, Ceq1, Zeq1)")
    nodes: List[str] = Field(
        ..., description="Eşdeğer kolun bağlandığı iki düğüm")
    formula: str = Field(
        ..., description="Sayısal formül (ör: 'Req1 = R1·R2/(R1+R2) = 1000·2000/(1000+2000) = 666.7 Ω')")
    latex: str = Field(..., description="Formülün LaTeX gösterimi")
    impedance: Optional[ComplexNumber] = Field(
        default=None,
        description="Eşdeğer empedans (Ω); AC'de frekans yoksa null")
    original_elements: List[str] = Field(
        ..., description="Eşdeğerin kapsadığı tüm orijinal elemanlar")


class ElementPower(BaseModel):
    """
    Tek bir elemanın gücü — pasif işaret kuralıyla (PSC) EMİLEN güç.

    V = V(+) − V(−), I = (+)'dan (−)'ye eleman içinden akan akım.
        AC:  S = ½ · V · I*   (fazör genlikleri tepe değerdir)
        DC:  S = V · I        (Q = 0)

    Güç veren kaynaklarda P negatiftir (emilen güç < 0).
    """
    element_id: str = Field(..., description="Eleman kimliği (ör: R1, VAC1)")
    role: Literal["source", "load"] = Field(
        ..., description="'source' = bağımsız kaynak, 'load' = pasif eleman")
    complex_power: ComplexNumber = Field(
        ..., description="Karmaşık güç S = P + jQ (emilen, VA)")
    active_power: float = Field(
        ..., description="Aktif güç P = Re(S) [W] — negatifse eleman güç verir")
    reactive_power: float = Field(
        ..., description="Reaktif güç Q = Im(S) [VAR] — L: Q>0, C: Q<0")
    apparent_power: float = Field(
        ..., description="Görünür güç |S| = √(P²+Q²) [VA]")
    power_factor: Optional[float] = Field(
        default=None,
        description="Güç faktörü cos φ = |P|/|S| (|S| = 0 ise null)")
    power_factor_type: Optional[Literal["geri", "ileri", "birim"]] = Field(
        default=None,
        description="'geri' = endüktif (akım gerilimin gerisinde), "
                    "'ileri' = kapasitif, 'birim' = saf direnç")


class PowerAnalysis(BaseModel):
    """
    Güç analizi — eleman güçleri + kaynak/yük toplamları + güç dengesi.

    Tellegen teoremi: Σ S (tüm elemanlar, emilen) = 0
        → kaynakların verdiği karmaşık güç = yüklerin çektiği karmaşık güç
    """
    convention: str = Field(
        ..., description="Kullanılan formül: AC'de 'S = ½·V·I* (tepe fazör)', DC'de 'P = V·I'")
    elements: Dict[str, ElementPower] = Field(
        default_factory=dict, description="Eleman bazında güçler")
    total_supplied: ComplexNumber = Field(
        ..., description="Kaynakların verdiği toplam karmaşık güç (Σ −S_kaynak)")
    total_absorbed: ComplexNumber = Field(
        ..., description="Pasif elemanların çektiği toplam karmaşık güç (Σ S_yük)")
    power_factor: Optional[float] = Field(
        default=None,
        description="Kaynaklardan görülen devre güç faktörü cos φ = P/|S|")
    power_factor_type: Optional[Literal["geri", "ileri", "birim"]] = Field(
        default=None, description="Devre güç faktörü tipi")
    balance_error: float = Field(
        ..., description="Güç dengesi hatası |S_verilen − S_çekilen| (≈0 olmalı)")


# ═══════════════════════════════════════════════════════
#  ÇÖZÜM ADIMLARI (LLM Halüsinasyon Kalkanı)
# ═══════════════════════════════════════════════════════

class SolutionStep(BaseModel):
    """
    Çözümün tek bir adımı.

    Bu yapı, LLM'e (yapay zekaya) hazır matematik verir:
    - equations: Python/sembolik denklemler (SymPy çıktısı)
    - latex_formula: LaTeX formülü (doğrudan render edilebilir)
    - result_snapshot: Bu adımdaki ara sonuçlar

    LLM bu adımı alır ve pedagojik dille öğrenciye anlatır:
    "Adım 2'de KCL uygulayarak şu denklemi elde ederiz: ..."
    """
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "step_number": 1,
                    "title": "KCL — Düğüm 2 Denklemi",
                    "description": "Düğüm 2'ye bağlı kolların akımları toplamı Kirchhoff Akım Yasası (KCL) gereği sıfıra eşitlenir.",
                    "equations": ["(V2 - 12)/1000 + V2/2000 = 0"],
                    "latex_formula": r"\frac{V_2 - 12}{1000} + \frac{V_2}{2000} = 0",
                    "result_snapshot": {"V2": 8.0},
                }
            ]
        }
    )

    step_number: int = Field(..., description="Adım sırası (1, 2, 3...)")
    title: str = Field(
        ..., description="Adım başlığı (ör: 'KCL — Düğüm 2 Denklemi')")
    description: str = Field(
        ..., description="Açıklayıcı metin (Türkçe)")
    equations: List[str] = Field(
        default_factory=list,
        description="Sembolik denklemler (ör: ['V2/1000 + V2/2000 = 0.012'])")
    latex_formula: Optional[str] = Field(
        default=None,
        description="LaTeX formülü (ör: '\\frac{V_2}{1000} + ...')")
    result_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Bu adımdaki ara sonuçlar (ör: {'V2': 8.0})")


# ═══════════════════════════════════════════════════════
#  BİRLEŞİK SONUÇLAR
# ═══════════════════════════════════════════════════════

class PracticeAlternative(BaseModel):
    """Yaygın bir hatanın vereceği değer ve öğrenciye söylenecek açıklama."""
    value: ComplexNumber = Field(..., description="Hatalı yolun verdiği değer")
    message: str = Field(..., description="Bu değer girilirse gösterilecek Türkçe açıklama")


class PracticeQuestion(BaseModel):
    """
    Alıştırma modunda öğrenciye sorulan tek bir büyüklük.

    Cevap 'expected' ile karşılaştırılır; arayüz bu değeri öğrenci
    'Çözümü Göster' diyene kadar göstermez.
    """
    id: str = Field(..., description="Soru kimliği (ör: V2, I_R1, MESH1, VTH, RTH)")
    label: str = Field(..., description="Gösterim sembolü (ör: V₂, I_R1, I₁, Vth)")
    description: str = Field(..., description="Türkçe soru metni")
    unit: Literal["V", "A", "Ω", "W"] = Field(..., description="Beklenen birim")
    group: Literal["main", "extra"] = Field(
        ..., description="main: yöntemin asıl bilinmeyenleri; extra: ek sorular")
    is_ac: bool = Field(..., description="True → cevap fazör (karmaşık) olmalı")
    frequency: Optional[float] = Field(
        default=None, description="AC sorularında fazörün frekansı (Hz)")
    expected: ComplexNumber = Field(..., description="Doğru cevap")
    scale: float = Field(
        ..., description="Aynı türdeki büyüklüklerin tipik değeri — beklenen 0 iken tolerans için")
    hint: str = Field(..., description="Yanlış cevapta gösterilecek genel ipucu (cevabı vermez)")
    sign_hint: str = Field(..., description="İşaret ters girildiğinde gösterilecek açıklama")
    alternatives: List[PracticeAlternative] = Field(
        default_factory=list, description="Yaygın hataların değerleri ve açıklamaları")


class AnswerVerdict(BaseModel):
    """Bir cevabın değerlendirmesi."""
    question_id: str = Field(..., description="Soru kimliği")
    status: Literal["correct", "close", "partial", "wrong", "invalid", "empty"] = Field(
        ..., description=(
            "correct: doğru (±%1) · close: çok yakın (±%5, yuvarlama) · "
            "partial: kısmen (ör. büyüklük doğru açı eksik, birim yanlış) · "
            "wrong: yanlış · invalid: okunamadı · empty: boş"))
    message: str = Field(..., description="Öğrenciye gösterilecek Türkçe geri bildirim")
    understood_as: Optional[str] = Field(
        default=None, description="Cevabın nasıl okunduğu (ör: '4 mA')")


class AnswerCheckResponse(BaseModel):
    """POST /practice/check yanıtı."""
    verdicts: List[AnswerVerdict] = Field(default_factory=list, description="Soru sırasıyla değerlendirmeler")
    correct_count: int = Field(..., description="Doğru cevap sayısı")
    total: int = Field(..., description="Değerlendirilen soru sayısı")


class LlmStatusResponse(BaseModel):
    """GET /llm/status — yerel yapay zekâ (Ollama) durumu."""
    available: bool = Field(..., description="Ollama çalışıyor mu")
    version: Optional[str] = Field(default=None, description="Ollama sürümü")
    models: List[str] = Field(default_factory=list, description="Kurulu modeller")
    recommended_model: str = Field(..., description="Önerilen model adı")
    selected_model: Optional[str] = Field(
        default=None, description="Model belirtilmezse kullanılacak model")
    message: str = Field(..., description="Öğrenciye gösterilecek Türkçe durum / kurulum bilgisi")
    ollama_installed: bool = Field(
        default=False, description="Ollama programı bu bilgisayarda kurulu mu (çalışmıyor olsa bile)")
    ram_gb: Optional[float] = Field(default=None, description="Toplam bellek (GB)")
    free_disk_gb: Optional[float] = Field(default=None, description="Modellerin ineceği diskteki boş yer (GB)")
    fit: str = Field(
        default="unknown",
        description="Belleğe göre uygunluk: good (≥16 GB), ok (8–16 GB), low (<8 GB), unknown")
    approx_size_gb: float = Field(default=0.0, description="Önerilen modelin yaklaşık indirme boyutu (GB)")
    advice_message: str = Field(default="", description="Belleğe göre Türkçe tavsiye cümlesi")


class LlmPullStatus(BaseModel):
    """GET/POST /llm/pull — model indirme durumu."""
    model: Optional[str] = Field(default=None, description="İndirilen model")
    state: Literal["idle", "running", "done", "error", "cancelled"] = Field(..., description="İndirme durumu")
    completed_bytes: int = Field(default=0, description="İnen bayt")
    total_bytes: int = Field(default=0, description="Toplam bayt (bilinmiyorsa 0)")
    percent: Optional[float] = Field(default=None, description="Yüzde (toplam bilinmiyorsa null)")
    speed_bps: float = Field(default=0.0, description="Hız (bayt/sn)")
    eta_seconds: Optional[float] = Field(default=None, description="Tahmini kalan süre (sn)")
    message: str = Field(default="", description="Türkçe durum mesajı")


class LlmActionResult(BaseModel):
    """POST /llm/start ve /llm/pull/cancel yanıtı."""
    ok: bool = Field(..., description="İşlem yapıldı mı")
    message: str = Field(..., description="Türkçe açıklama")


class LlmNumberCheck(BaseModel):
    """Cevaptaki bir sayının denetimi."""
    text: str = Field(..., description="Sayının cevaptaki hâli (ör. '4 mA')")
    status: Literal["verified", "unverified", "redacted"] = Field(
        ..., description="verified: çözümle uyuşuyor · unverified: doğrulanamadı · redacted: alıştırmada gizlendi")


class LlmAnswerResponse(BaseModel):
    """POST /llm/ask yanıtı."""
    answer: str = Field(..., description="Modelin cevabı (alıştırmada cevap sayıları ■■ ile gizlenmiş)")
    model: str = Field(..., description="Kullanılan model")
    numbers: List[LlmNumberCheck] = Field(default_factory=list, description="Cevaptaki sayıların denetimi")
    note: Optional[str] = Field(
        default=None, description="Doğrulanamayan / gizlenen sayılar için Türkçe uyarı")


class AnalysisResults(BaseModel):
    """Tüm analiz sonuçlarını birleştiren konteyner."""
    node_voltages: Dict[str, NodeVoltage] = Field(
        default_factory=dict,
        description="Düğüm gerilimleri: {'0': ..., '1': ..., '2': ...}")
    element_currents: Dict[str, ElementCurrent] = Field(
        default_factory=dict,
        description="Eleman akımları: {'R1': ..., 'L1': ...}")
    probe_results: List[ProbeResult] = Field(
        default_factory=list,
        description="Ölçüm probu sonuçları")
    thevenin: Optional[TheveninResult] = Field(
        default=None,
        description="Thevenin eşdeğeri (sadece THEVENIN modunda)")
    norton: Optional[NortonResult] = Field(
        default=None,
        description="Norton eşdeğeri (sadece NORTON modunda)")
    superposition: List[SourceContribution] = Field(
        default_factory=list,
        description="Süperpozisyon katkıları (sadece SUPERPOSITION yönteminde)")
    meshes: List[MeshInfo] = Field(
        default_factory=list,
        description="Çevre akımları (sadece MESH yönteminde ve yöntem uygulanabildiyse)")
    explanation: List[ExplanationSection] = Field(
        default_factory=list,
        description=(
            "Öğrenci için adım adım Türkçe anlatım — kalıp tabanlı, tüm sayılar "
            "çözücüden gelir; her türetme çözücü sonucuyla doğrulanır"))
    reductions: List[SeriesParallelReduction] = Field(
        default_factory=list,
        description="Seri/paralel indirgeme adımları (pedagojik topoloji analizi)")
    power: Optional[PowerAnalysis] = Field(
        default=None,
        description="Güç analizi (P, Q, S, cos φ) — eleman ve kaynak bazında")
    practice: List[PracticeQuestion] = Field(
        default_factory=list,
        description="Alıştırma modu soruları — öğrenci önce kendisi çözer, cevaplar /practice/check ile kontrol edilir")


# ═══════════════════════════════════════════════════════
#  ANA YANIT MODELİ
# ═══════════════════════════════════════════════════════

class AnalysisResponse(BaseModel):
    """
    Devre analizi yanıtı — Python Backend → C# Frontend.

    Üç katmanlı yapı:
    1. results     → Sayısal sonuçlar (düğüm gerilimleri, akımlar)
    2. solution_steps → Adım adım çözüm (LLM için yapılandırılmış veri)
    3. errors      → Hata/uyarı mesajları

    Tam JSON örneği response.py modül docstring'inde verilmiştir.
    """
    status: str = Field(
        default="success",
        description="İşlem durumu: 'success' veya 'error'")
    mode: str = Field(
        ..., description="Kullanılan analiz modu")
    analysis_type: str = Field(
        ..., description="Kullanılan çözüm yöntemi")
    results: AnalysisResults = Field(
        default_factory=AnalysisResults,
        description="Analiz sonuçları")
    solution_steps: List[SolutionStep] = Field(
        default_factory=list,
        description="Adım adım çözüm açıklaması (LLM halüsinasyon kalkanı)")
    errors: List[str] = Field(
        default_factory=list,
        description="Hata ve uyarı mesajları")
    warnings: List[str] = Field(
        default_factory=list,
        description=(
            "Pedagojik analiz uyarıları — ör: farklı frekanslı kaynaklar "
            "(süperpozisyon gerekli), kaynak/analiz frekansı uyuşmazlığı, "
            "AC analizde sıfırlanan DC bileşenler. '⚠' ile başlayanlar "
            "sonuçların geçersiz/eksik olabileceğini belirtir (status = "
            "'warning'); 'ℹ' ile başlayanlar bilgilendirmedir."
        ))
