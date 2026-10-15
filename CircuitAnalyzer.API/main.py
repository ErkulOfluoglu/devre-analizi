"""
CircuitAnalyzer API — FastAPI Uygulama Giriş Noktası

Çalıştırma:
    uvicorn main:app --reload --port 8000

Endpoint'ler:
    GET  /health     → Sağlık kontrolü
    POST /analyze    → Devre analizi
    POST /parse-only → Sadece Netlist ayrıştırma (test/debug)
    POST /practice/check → Alıştırma modu: öğrenci cevaplarını değerlendir
    GET  /llm/status → İsteğe bağlı yerel yapay zekâ (Ollama) durumu
    POST /llm/ask    → Çözüm hakkında yapay zekâya soru (sayılar denetlenir)
    POST /llm/start  → Kurulu ama kapalı Ollama'yı başlat
    POST /llm/pull   → Modeli indir (GET: ilerleme, POST /llm/pull/cancel: iptal)
"""

from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware

from llm import ollama, pull, system_info
from llm.assistant import answer_question
from models.request import (
    AnalysisRequest, AnalysisMode, AnalysisType, ProbeTarget,
    AnswerCheckRequest, LlmAskRequest, LlmPullRequest, ANALYSIS_REQUEST_EXAMPLES
)
from models.response import (
    AnalysisResponse, AnalysisResults, SolutionStep,
    NodeVoltage, ElementCurrent, ProbeResult, ComplexNumber,
    AnswerCheckResponse, LlmActionResult, LlmAnswerResponse, LlmNumberCheck,
    LlmPullStatus, LlmStatusResponse
)
from practice.checker import check_answer
from parser.netlist_parser import parse_netlist, to_lcapy_netlist
from solver.circuit_solver import solve_circuit


# ═══════════════════════════════════════════════════════
#  UYGULAMA OLUŞTURMA
# ═══════════════════════════════════════════════════════

tags_metadata = [
    {
        "name": "Sistem",
        "description": "Sunucu durumu, sürüm bilgisi ve sağlık kontrolü işlemleri.",
    },
    {
        "name": "Analiz",
        "description": "SPICE Netlist devre analizi, sembolik çözümleme ve adım adım çözüm dökümü.",
    },
    {
        "name": "Alıştırma",
        "description": "Öğrenci alıştırma modu: cevap okuma, değerlendirme ve hata teşhisi.",
    },
    {
        "name": "Yapay Zekâ",
        "description": (
            "İsteğe bağlı yerel dil modeli (Ollama). Kurulu değilse uygulama "
            "yapay zekâsız çalışır. Cevaplardaki sayılar çözümle denetlenir."
        ),
    },
]

app = FastAPI(
    title="Circuit Analyzer API",
    description=(
        "Devre analizi eğitim uygulaması — Python Backend.\n\n"
        "C# WPF Frontend'ten gelen SPICE Netlist'i alır,\n"
        "lcapy ile sembolik olarak çözer ve adım adım açıklama üretir."
    ),
    version="0.2.0",
    openapi_tags=tags_metadata,
)

# CORS — C# WPF HttpClient'ten gelen istekleri kabul et
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════
#  ENDPOINT'LER
# ═══════════════════════════════════════════════════════

@app.get(
    "/health",
    tags=["Sistem"],
    summary="Sağlık kontrolü",
    description=(
        "Sunucunun ve sembolik çözücü servisinin çalışır durumda olduğunu doğrular.\n\n"
        "C# tarafı uygulama başladığında bu endpoint'i çağırarak "
        "Python backend'in hazır olup olmadığını kontrol eder."
    ),
    response_description="Servis sağlık durumu ve sürüm bilgisi",
)
async def health_check():
    """
    Sağlık kontrolü — sunucunun çalıştığını doğrular.

    C# tarafı uygulama başladığında bu endpoint'i çağırarak
    Python backend'in hazır olup olmadığını kontrol eder.
    """
    return {
        "status": "healthy",
        "service": "CircuitAnalyzer API",
        "version": "0.2.0",
        "solver": "lcapy (SymPy tabanlı sembolik çözücü)"
    }


@app.post(
    "/analyze",
    response_model=AnalysisResponse,
    tags=["Analiz"],
    summary="Devre analizi",
    description=(
        "Ana devre analizi endpoint'i.\n\n"
        "İş akışı:\n"
        "1. Netlist'i ayrıştır (parser)\n"
        "2. Analiz moduna göre devre çöz (solver — lcapy)\n"
        "3. Çözüm adımlarını üret\n"
        "4. Yapılandırılmış JSON yanıt döndür"
    ),
    response_description="Devre analizi sonuçları ve adım adım çözüm dökümü",
    responses={
        400: {"description": "Netlist ayrıştırma hatası"},
        422: {"description": "Doğrulama hatası"},
    },
)
async def analyze_circuit(
    request: AnalysisRequest = Body(
        ...,
        openapi_examples=ANALYSIS_REQUEST_EXAMPLES,
    )
):
    """
    Ana devre analizi endpoint'i.

    İş akışı:
        1. Netlist'i ayrıştır (parser)
        2. Analiz moduna göre devre çöz (solver — lcapy)
        3. Çözüm adımlarını üret
        4. Yapılandırılmış JSON yanıt döndür

    Args:
        request: AnalysisRequest — Netlist + mod + hedefler

    Returns:
        AnalysisResponse — Sonuçlar + adım adım çözüm
    """

    # ── 1. NETLIST AYRIŞTIRMA ──
    try:
        parsed = parse_netlist(request.netlist)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Netlist ayrıştırma hatası: {str(e)}"
        )

    if not parsed.elements:
        raise HTTPException(
            status_code=400,
            detail="Netlist'te hiçbir devre elemanı bulunamadı."
        )

    # Netlist'teki prob bilgilerini request'teki ile birleştir
    probes = list(request.target_probes or [])
    if parsed.probes:
        existing_ids = {p.id for p in probes}
        for pp in parsed.probes:
            if pp.id not in existing_ids:
                probes.append(
                    ProbeTarget(id=pp.id, type=pp.probe_type, target=pp.target)
                )

    # ── 2. DEVRE ÇÖZÜMÜ (lcapy) ──
    warnings: list = []
    results, solution_steps, errors = solve_circuit(
        parsed=parsed,
        mode=request.mode,
        frequency=request.frequency,
        analysis_type=request.analysis_type,
        thevenin_terminals=request.thevenin_terminals,
        target_probes=probes if probes else None,
        warnings=warnings
    )

    has_problem = any("⚠" in m for m in errors + warnings)
    return AnalysisResponse(
        status="warning" if has_problem else "success",
        mode=request.mode.value,
        analysis_type=request.analysis_type.value,
        results=results,
        solution_steps=solution_steps,
        errors=errors,
        warnings=warnings
    )


@app.post(
    "/parse-only",
    tags=["Analiz"],
    summary="Sadece Netlist ayrıştırma",
    description=(
        "Sadece Netlist ayrıştırma (debug endpoint'i).\n\n"
        "Solver'ı çağırmadan parser çıktısını ve lcapy dönüşümünü döndürür.\n"
        "C# tarafında Netlist formatını test etmek için kullanışlıdır."
    ),
    response_description="Ayrıştırılmış elemanlar ve lcapy netlist metni",
    responses={
        400: {"description": "Netlist ayrıştırma hatası"},
        422: {"description": "Doğrulama hatası"},
    },
)
async def parse_only(
    request: AnalysisRequest = Body(
        ...,
        openapi_examples=ANALYSIS_REQUEST_EXAMPLES,
    )
):
    """
    Sadece Netlist ayrıştırma (debug endpoint'i).

    Solver'ı çağırmadan parser çıktısını ve lcapy dönüşümünü döndürür.
    C# tarafında Netlist formatını test etmek için kullanışlıdır.
    """
    try:
        parsed = parse_netlist(request.netlist)
        lcapy_text = to_lcapy_netlist(parsed, request.frequency)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Ayrıştırma hatası: {str(e)}"
        )

    return {
        "status": "parsed",
        "element_count": len(parsed.elements),
        "elements": [
            {
                "id": e.id,
                "type": e.element_type.value,
                "node_positive": e.node_positive,
                "node_negative": e.node_negative,
                "value": e.value,
                "params": {
                    k: str(v) if isinstance(v, complex) else v
                    for k, v in e.params.items()
                }
            }
            for e in parsed.elements
        ],
        "probes": [
            {"id": p.id, "type": p.probe_type, "target": p.target}
            for p in parsed.probes
        ],
        "has_ground": parsed.has_ground,
        "node_count": parsed.node_count,
        "lcapy_netlist": lcapy_text,
        "warnings": parsed.warnings
    }


@app.post(
    "/practice/check",
    response_model=AnswerCheckResponse,
    tags=["Alıştırma"],
    summary="Öğrenci cevaplarını değerlendir",
    description=(
        "Alıştırma modunda öğrencinin yazdığı cevapları değerlendirir.\n\n"
        "Sorular /analyze yanıtındaki `results.practice` listesinden aynen gönderilir; "
        "sunucu durum tutmaz.\n\n"
        "Cevap yazımları: `4m`, `4 mA`, `0.004`, `2.5k`, `1k5`, `3.03∠-72.3`, "
        "`0.92-j2.89`, `(0.92 - j2.89) mA`.\n\n"
        "Yanlış cevaplarda sık yapılan hatalar teşhis edilir (işaret, birim öneki, "
        "tepe/etkin değer, radyan/derece, açının işareti) — doğru cevap söylenmez."
    ),
    response_description="Her soru için durum ve Türkçe geri bildirim",
)
async def practice_check(request: AnswerCheckRequest):
    verdicts = [check_answer(item.question, item.answer) for item in request.items]
    return AnswerCheckResponse(
        verdicts=verdicts,
        correct_count=sum(1 for v in verdicts if v.status == "correct"),
        total=len(verdicts),
    )


_OLLAMA_INSTALL_HELP = (
    "Yerel yapay zekâ bulunamadı. İsterseniz ücretsiz Ollama programını "
    "ollama.com adresinden indirip her program gibi kurun; ardından programdaki "
    "“Modeli indir” düğmesiyle modeli indirin (terminal gerekmez). Uygulamanın "
    "geri kalanı yapay zekâ olmadan da tam çalışır."
)
_OLLAMA_STOPPED_HELP = (
    "Ollama bu bilgisayarda kurulu ama şu an kapalı. “Başlat” düğmesiyle açabilirsiniz."
)


@app.get(
    "/llm/status",
    response_model=LlmStatusResponse,
    tags=["Yapay Zekâ"],
    summary="Yerel yapay zekâ durumu",
    description="Ollama çalışıyor mu ve hangi modeller kurulu? Hata fırlatmaz; en fazla ~2 sn sürer.",
)
def llm_status():
    st = ollama.get_status()
    ram = system_info.total_ram_gb()
    advice = system_info.recommend(ram)
    installed = st.available or system_info.find_ollama_app() is not None
    selected = ollama.pick_model(None, st.models, preferred=advice.model)
    if not st.available:
        message = _OLLAMA_STOPPED_HELP if installed else _OLLAMA_INSTALL_HELP
    elif not st.models:
        message = (f"Ollama çalışıyor ama kurulu model yok. “Modeli indir” düğmesiyle "
                   f"{advice.model} modelini indirin (ya da terminalde: “ollama pull {advice.model}”).")
    else:
        message = f"Yapay zekâ hazır — model: {selected}"
    disk = system_info.free_disk_gb()
    return LlmStatusResponse(
        available=st.available, version=st.version, models=st.models,
        recommended_model=advice.model, selected_model=selected, message=message,
        ollama_installed=installed,
        ram_gb=round(ram, 1) if ram is not None else None,
        free_disk_gb=round(disk, 1) if disk is not None else None,
        fit=advice.fit, approx_size_gb=advice.approx_size_gb, advice_message=advice.message,
    )


@app.post(
    "/llm/start",
    response_model=LlmActionResult,
    tags=["Yapay Zekâ"],
    summary="Kurulu ama kapalı Ollama'yı başlat",
    description="Ollama'yı açar; hazır olmasını beklemez (durum /llm/status ile yoklanır).",
)
def llm_start():
    if ollama.get_status().available:
        return LlmActionResult(ok=True, message="Ollama zaten çalışıyor.")
    if system_info.start_ollama():
        return LlmActionResult(ok=True, message="Ollama başlatılıyor…")
    return LlmActionResult(ok=False, message="Ollama bu bilgisayarda bulunamadı. Önce kurmanız gerekiyor.")


def _pull_status() -> LlmPullStatus:
    s = pull.MANAGER.snapshot()
    return LlmPullStatus(
        model=s.model, state=s.state, completed_bytes=s.completed, total_bytes=s.total,
        percent=round(s.percent, 1) if s.percent is not None else None,
        speed_bps=round(s.speed_bps, 1), eta_seconds=round(s.eta_seconds) if s.eta_seconds else None,
        message=s.message,
    )


@app.post(
    "/llm/pull",
    response_model=LlmPullStatus,
    tags=["Yapay Zekâ"],
    summary="Yapay zekâ modelini indir (terminal gerekmez)",
    description=(
        "İndirmeyi arka planda başlatır ve hemen döner; ilerleme GET /llm/pull ile yoklanır. "
        "Model verilmezse bilgisayarın belleğine göre önerilen model indirilir. "
        "Diskte yer yoksa 400, zaten bir indirme sürüyorsa 409, Ollama kapalıysa 503."
    ),
    responses={400: {"description": "Diskte yer yok"}, 409: {"description": "İndirme zaten sürüyor"},
               503: {"description": "Ollama çalışmıyor"}},
)
def llm_pull(request: LlmPullRequest = Body(default=LlmPullRequest())):
    if not ollama.get_status().available:
        raise HTTPException(status_code=503, detail=_OLLAMA_INSTALL_HELP)
    advice = system_info.recommend(system_info.total_ram_gb())
    model = (request.model or advice.model).strip()
    size = system_info.APPROX_SIZE_GB.get(model, advice.approx_size_gb)
    disk = system_info.free_disk_gb()
    if disk is not None and disk < size + system_info.DISK_MARGIN_GB:
        raise HTTPException(
            status_code=400,
            detail=f"Diskte yeterli yer yok: yaklaşık {size + system_info.DISK_MARGIN_GB:.0f} GB gerekli, "
                   f"{disk:.1f} GB boş.")
    if not pull.MANAGER.start(model):
        raise HTTPException(status_code=409, detail="Bir model indirmesi zaten sürüyor.")
    return _pull_status()


@app.get(
    "/llm/pull",
    response_model=LlmPullStatus,
    tags=["Yapay Zekâ"],
    summary="Model indirme durumu",
)
def llm_pull_status():
    return _pull_status()


@app.post(
    "/llm/pull/cancel",
    response_model=LlmActionResult,
    tags=["Yapay Zekâ"],
    summary="Model indirmeyi iptal et",
    description="İptal edilen indirme yeniden başlatılınca kaldığı yerden devam eder.",
)
def llm_pull_cancel():
    if pull.MANAGER.cancel():
        return LlmActionResult(ok=True, message="İndirme iptal ediliyor…")
    return LlmActionResult(ok=False, message="Süren bir indirme yok.")


@app.post(
    "/llm/ask",
    response_model=LlmAnswerResponse,
    tags=["Yapay Zekâ"],
    summary="Çözüm hakkında yapay zekâya soru",
    description=(
        "Devre yeniden çözülür ve modele yalnızca doğrulanmış anlatım verilir. "
        "Cevaptaki her sayı çözümle karşılaştırılır (doğrulanamayanlar `note` alanında). "
        "`practice: true` iken model sonuçları görmez ve cevabı veren sayılar ■■ ile gizlenir.\n\n"
        "İşlemcide çalışan modellerde cevap 1 dakikayı bulabilir."
    ),
    responses={
        400: {"description": "Netlist hatası ya da kurulu model yok"},
        503: {"description": "Ollama çalışmıyor"},
    },
)
def llm_ask(request: LlmAskRequest):
    # Senkron uç nokta: FastAPI iş parçacığı havuzunda çalıştırır, uzun model
    # cevabı beklenirken diğer istekler (ör. /health) bloklanmaz.
    st = ollama.get_status()
    if not st.available:
        raise HTTPException(status_code=503, detail=_OLLAMA_INSTALL_HELP)
    model = ollama.pick_model(request.model, st.models,
                              preferred=system_info.recommend(system_info.total_ram_gb()).model)
    if model is None:
        raise HTTPException(
            status_code=400,
            detail=f"Ollama'da kurulu model yok. Terminalde “ollama pull {ollama.RECOMMENDED_MODEL}” yazın.")

    try:
        parsed = parse_netlist(request.netlist)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Netlist ayrıştırma hatası: {str(e)}")
    if not parsed.elements:
        raise HTTPException(status_code=400, detail="Netlist'te hiçbir devre elemanı bulunamadı.")

    results, _, _ = solve_circuit(
        parsed=parsed, mode=request.mode, frequency=request.frequency,
        analysis_type=request.analysis_type, thevenin_terminals=request.thevenin_terminals,
        warnings=[],
    )
    is_dc = request.mode == AnalysisMode.DC
    frequency = request.frequency
    if frequency is None and not is_dc:
        # Frekans boşsa çözücü kaynak frekansını kullanır; anlatımdaki ω ile aynı olsun
        frequency = next((e.params["frequency"] for e in parsed.elements
                          if e.params.get("frequency")), None)

    try:
        out = answer_question(
            parsed, results, request.analysis_type, is_dc, frequency,
            request.thevenin_terminals, request.question,
            [t.model_dump() for t in request.history], model,
            practice=request.practice, practice_questions=request.practice_questions,
        )
    except ollama.OllamaUnavailable:
        raise HTTPException(status_code=503, detail=_OLLAMA_INSTALL_HELP)
    except ollama.OllamaError as e:
        raise HTTPException(status_code=400, detail=f"Yapay zekâ hatası: {e}")

    return LlmAnswerResponse(
        answer=out["answer"], model=model,
        numbers=[LlmNumberCheck(text=t, status=s) for t, s in out["numbers"]],
        note=out["note"],
    )
