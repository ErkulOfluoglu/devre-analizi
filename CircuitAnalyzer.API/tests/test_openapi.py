"""
OpenAPI / Swagger belgeleri ve şema regresyon testleri.

FastAPI tarafından üretilen OpenAPI 3.1.0 JSON şemasının eksiksizliğini,
şema açıklamalarını, enum tanımlarını, örnek yükleri ve C# istemcisi için
kritik olan kablo formatı (wire format) kararlılığını doğrular.
"""

import pytest


def test_docs_and_openapi_endpoints(client):
    """GET /docs ve GET /openapi.json uç noktalarının 200 döndürdüğünü doğrular."""
    res_docs = client.get("/docs")
    assert res_docs.status_code == 200

    res_openapi = client.get("/openapi.json")
    assert res_openapi.status_code == 200


def test_components_schemas_presence(client):
    """components.schemas altında beklenen tüm model ve enum şemalarının bulunduğunu doğrular."""
    res = client.get("/openapi.json")
    assert res.status_code == 200
    schemas = res.json().get("components", {}).get("schemas", {})

    expected_schemas = {
        "AnalysisRequest",
        "AnalysisResponse",
        "AnalysisResults",
        "ComplexNumber",
        "TheveninResult",
        "NortonResult",
        "PowerAnalysis",
        "ElementPower",
        "SeriesParallelReduction",
        "SolutionStep",
        "ProbeTarget",
        "TheveninTerminals",
        "AnalysisMode",
        "AnalysisType",
    }

    missing = expected_schemas - set(schemas.keys())
    assert not missing, f"components.schemas içinde eksik şemalar: {missing}"


def test_enum_definitions(client):
    """AnalysisMode ve AnalysisType enum değerlerinin tam olarak eşleştiğini doğrular."""
    res = client.get("/openapi.json")
    schemas = res.json()["components"]["schemas"]

    assert schemas["AnalysisMode"]["enum"] == ["DC", "AC_TIME", "AC_PHASOR"]
    assert schemas["AnalysisType"]["enum"] == ["NODAL", "MESH", "THEVENIN", "NORTON", "SUPERPOSITION",
                                                  "MILLMAN", "SOURCE_TRANSFORM", "TRANSIENT"]


def test_all_schema_properties_have_descriptions(client):
    """
    components.schemas içindeki her modelin her özelliğinin (property)
    boş olmayan bir açıklamaya (description) sahip olduğunu genel bir gezinici ile doğrular.
    FastAPI'nin yerleşik HTTPValidationError ve ValidationError şemaları hariç tutulur.
    """
    res = client.get("/openapi.json")
    schemas = res.json()["components"]["schemas"]
    skip_schemas = {"HTTPValidationError", "ValidationError"}

    missing_descriptions = []
    for schema_name, schema_def in schemas.items():
        if schema_name in skip_schemas:
            continue
        properties = schema_def.get("properties", {})
        for prop_name, prop_def in properties.items():
            desc = prop_def.get("description")
            if not desc or not str(desc).strip():
                missing_descriptions.append(f"{schema_name}.{prop_name}")

    assert not missing_descriptions, f"Açıklaması (description) eksik özellikler: {missing_descriptions}"


def test_analyze_request_body_examples_and_execution(client):
    """
    POST /analyze isteği için 5 adlandırılmış OpenAPI örneğinin (dc_nodal, dc_dependent,
    ac_phasor, ac_thevenin, dc_norton) tanımlı olduğunu ve her birinin /analyze uç noktasına
    gönderildiğinde 200 döndürerek başarıyla çözüldüğünü doğrular.
    """
    res = client.get("/openapi.json")
    openapi = res.json()
    request_body = openapi["paths"]["/analyze"]["post"]["requestBody"]
    examples = request_body["content"]["application/json"]["examples"]

    expected_examples = {"dc_nodal", "dc_dependent", "ac_phasor", "ac_thevenin", "dc_norton"}
    assert set(examples.keys()) == expected_examples

    for example_name, example_obj in examples.items():
        payload = example_obj["value"]
        resp = client.post("/analyze", json=payload)
        assert resp.status_code == 200, (
            f"Örnek payload '{example_name}' başarısız oldu (kod {resp.status_code}): {resp.text}"
        )
        data = resp.json()
        assert data["status"] in ("success", "warning"), (
            f"Örnek '{example_name}' beklenmeyen durum: {data['status']}"
        )

        results = data.get("results", {})
        if example_name == "ac_thevenin":
            assert results.get("thevenin") is not None, "ac_thevenin örneğinde results.thevenin null olmamalıdır"
        elif example_name == "dc_norton":
            assert results.get("norton") is not None, "dc_norton örneğinde results.norton null olmamalıdır"


def test_analyze_documented_responses_and_operations_metadata(client):
    """
    /analyze uç noktasının 200, 400 ve 422 yanıtlarını belgelediğini ve
    API'deki tüm işlemlerin özet (summary) ve etiket (tags) meta verilerine sahip olduğunu doğrular.
    """
    res = client.get("/openapi.json")
    openapi = res.json()

    # /analyze yanıt kodları
    analyze_responses = openapi["paths"]["/analyze"]["post"]["responses"]
    for status_code in ("200", "400", "422"):
        assert status_code in analyze_responses, f"/analyze uç noktasında {status_code} yanıtı belgelenmemiş"

    # Tüm işlemler için summary ve tags kontrolü
    paths = openapi.get("paths", {})
    for path, path_item in paths.items():
        for method in ("get", "post", "put", "delete", "patch", "options", "head"):
            if method in path_item:
                op = path_item[method]
                summary = op.get("summary")
                tags = op.get("tags")
                assert summary and str(summary).strip() != "", f"{method.upper()} {path} özet (summary) bilgisi eksik"
                assert tags and len(tags) > 0, f"{method.upper()} {path} etiket (tags) bilgisi eksik"


def test_wire_format_regression_guard(client):
    """
    C# WPF istemcisinin bağımlı olduğu JSON kablo formatının (wire format) değişmediğini
    AnalysisRequest ve AnalysisResponse model alanlarını tam küme olarak denetleyerek korur.
    """
    res = client.get("/openapi.json")
    schemas = res.json()["components"]["schemas"]

    request_props = set(schemas["AnalysisRequest"].get("properties", {}).keys())
    expected_request_props = {
        "netlist",
        "mode",
        "frequency",
        "target_probes",
        "analysis_type",
        "thevenin_terminals",
    }
    assert request_props == expected_request_props, f"AnalysisRequest alanları değişmiş: {request_props}"

    response_props = set(schemas["AnalysisResponse"].get("properties", {}).keys())
    expected_response_props = {
        "status",
        "mode",
        "analysis_type",
        "results",
        "solution_steps",
        "errors",
        "warnings",   # Madde 8 — eklemeli (additive) alan
        "transient",  # Faz 2 — eklemeli alan (yalnızca TRANSIENT başarılıysa dolu)
    }
    assert response_props == expected_response_props, f"AnalysisResponse alanları değişmiş: {response_props}"


def test_health_check_version(client):
    """/health endpoint'inin güncellenen 0.2.0 sürümünü döndürdüğünü doğrular."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.2.0"
