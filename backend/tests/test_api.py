from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

from conftest import FakeAdapter


def test_api_contract_is_camel_case_and_has_no_upload_route(settings, dictionary_root: Path):
    app = create_app(settings)
    app.state.dictionary_service.catalog.replace_all([FakeAdapter(dictionary_root / "fixture.mdx")])

    with TestClient(app) as client:
        response = client.get("/api/v1/lookup/hello")
        paths = client.get("/openapi.json").json()["paths"]

    assert response.status_code == 200
    payload = response.json()
    assert payload["lookupTimeMs"] >= 0
    assert payload["articles"][0]["dictionaryId"] == "fake-dictionary"
    assert "/api/v1/dictionaries/upload" not in paths
    assert "/api/v1/dictionaries/load" not in paths
    assert "/api/v1/dictionaries/{dictionary_id}" not in paths


def test_runtime_catalog_mutations_are_explicitly_opt_in(settings):
    app = create_app(replace(settings, runtime_catalog_mutations=True))

    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]

    assert "/api/v1/dictionaries/load" in paths
    assert "/api/v1/dictionaries/{dictionary_id}" in paths


def test_explicit_opaque_sandbox_origin_is_allowed_for_dictionary_scripts(settings):
    app = create_app(
        replace(settings, cors_origins=("http://localhost:5173", "null"))
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/health", headers={"Origin": "null"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "null"


def test_lookup_path_accepts_an_encoded_slash(settings):
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.get("/api/v1/lookup/ice%20cream%2F%E2%80%A6")

    assert response.status_code == 200
    assert response.json()["word"] == "ice cream/…"


def test_resource_has_mime_etag_cache_and_conditional_response(settings, dictionary_root: Path):
    app = create_app(settings)
    app.state.dictionary_service.catalog.replace_all([FakeAdapter(dictionary_root / "fixture.mdx")])

    with TestClient(app) as client:
        first = client.get("/api/v1/dictionaries/fake-dictionary/resources/fake.png")
        second = client.get(
            "/api/v1/dictionaries/fake-dictionary/resources/fake.png",
            headers={"If-None-Match": first.headers["etag"]},
        )
        partial = client.get(
            "/api/v1/dictionaries/fake-dictionary/resources/fake.png",
            headers={"Range": "bytes=0-3"},
        )

    assert first.status_code == 200
    assert first.headers["content-type"] == "image/png"
    assert first.headers["cache-control"].startswith("public")
    assert "must-revalidate" in first.headers["cache-control"]
    assert first.headers["x-content-type-options"] == "nosniff"
    assert second.status_code == 304
    assert second.content == b""
    assert partial.status_code == 206
    assert partial.content == b"fake"
    assert partial.headers["content-range"] == "bytes 0-3/8"
    assert partial.headers["accept-ranges"] == "bytes"


def test_errors_use_stable_structured_shape(settings):
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.get("/api/v1/suggestions?prefix=x&limit=0")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validationFailed"
    assert response.json()["error"]["details"]["violations"]


def test_health_and_dictionary_list_contract(settings, dictionary_root: Path):
    app = create_app(settings)
    app.state.dictionary_service.catalog.replace_all([FakeAdapter(dictionary_root / "fixture.mdx")])

    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        dictionaries = client.get("/api/v1/dictionaries")

    assert health.json()["dictionaryCount"] == 1
    assert health.json()["ready"] is True
    assert dictionaries.json()[0]["wordCount"] == 2
    assert dictionaries.json()[0]["resourceBaseUrl"].endswith("/resources/")
