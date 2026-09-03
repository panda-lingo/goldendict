from __future__ import annotations

import json
import os
from pathlib import Path
import textwrap

from app.adapters.native import NativeDictionaryAdapter, NativeWorkerClient
from app.config import Settings
from app.service import DictionaryService

def _fake_worker(tmp_path: Path) -> Path:
    worker = tmp_path / "fake-native-worker"
    worker.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import argparse
            import base64
            import json
            from pathlib import Path
            import sys

            parser = argparse.ArgumentParser()
            parser.add_argument("--dictionary-root", action="append", required=True)
            parser.add_argument("--index-dir", required=True)
            parser.add_argument("--timeout-ms", required=True)
            args = parser.parse_args()
            main_path = str((Path(args.dictionary_root[0]) / "fixture.mdx").resolve())
            dictionary_id = "native-fixture"

            def emit(value):
                print(json.dumps(value, separators=(",", ":")), flush=True)

            emit({
                "event": "ready",
                "upstreamCommit": "5ad66765aa423d381025566bff990f7d8007be84",
                "supportedFormats": [
                    "bgl", "stardict", "lsa", "dsl", "dictd", "xdxf", "sdict",
                    "aard", "zipsounds", "mdx", "gls", "slob", "zim", "epwing"
                ],
                "dictionaries": [{
                    "id": dictionary_id,
                    "name": "Native Fixture",
                    "format": "mdx",
                    "wordCount": 2,
                    "mainPath": main_path,
                    "sourceLanguage": "en",
                    "targetLanguage": "fr",
                    "iconUrl": None,
                    "iconResourcePath": "icon.png",
                    "resourceBaseUrl": "/api/v1/dictionaries/native-fixture/resources/",
                }],
            })
            for line in sys.stdin:
                request = json.loads(line)
                request_id = request["id"]
                operation = request["op"]
                with (Path(args.index_dir) / "requests.log").open("a", encoding="utf-8") as log:
                    log.write(operation + "\\n")
                if operation == "lookup":
                    articles = []
                    if request["word"].casefold() == "hello":
                        articles.append({
                            "dictionaryId": dictionary_id,
                            "dictionaryName": "Native Fixture",
                            "format": "mdx",
                            "html": (
                                "<div class='mdict'><a href='gdlookup://world'>World</a>"
                                "<img src='bres://native-fixture/image.png'>"
                                "<script src='bres://native-fixture/oaldpe-jquery.js'></script>"
                                "<script src='bres://native-fixture/oaldpe.js'></script></div>"
                            ),
                        })
                    values = [
                        value for value in ("Hello", "Help")
                        if value.lower().startswith(request["word"].lower())
                    ][:request.get("suggestionLimit", 0)]
                    result = {"word": request["word"], "articles": articles, "suggestions": values}
                    emit({"id": request_id, "ok": True, "result": result})
                elif operation == "suggestions":
                    values = [value for value in ("Hello", "Help") if value.lower().startswith(request["prefix"].lower())]
                    emit({"id": request_id, "ok": True, "result": {"suggestions": values[:request["limit"]]}})
                elif operation == "resource":
                    bodies = {
                        "style.css": (
                            b".entry{background:url('image.png');"
                            b"src:url('bres://native-fixture/Fonts/A.WOFF2')}"
                        ),
                        "icon.png": b"\\x89PNG\\r\\n\\x1a\\nnative-icon",
                        "image.png": b"fake-png",
                        "scan.tiff": b"\\x89PNG\\r\\n\\x1a\\nconverted",
                        "oaldpe-jquery.js": b"globalThis.jQuery = {};",
                        "oaldpe.js": b"globalThis.oaldpe = true;",
                        "Dictionary-UI.js": b"globalThis.dictionaryUI = true;",
                        "leak.js": b"secret",
                    }
                    body = bodies.get(request["path"])
                    if body is None:
                        emit({"id": request_id, "ok": False, "error": {"code": "resourceNotFound", "message": "missing"}})
                    else:
                        emit({"id": request_id, "ok": True, "result": {
                            "bodyBase64": base64.b64encode(body).decode("ascii"),
                            "mediaType": (
                                "text/css" if request["path"].endswith(".css")
                                else "text/javascript" if request["path"].endswith(".js")
                                else "image/tiff" if request["path"].endswith(".tiff")
                                else "image/png"
                            ),
                        }})
                else:
                    emit({"id": request_id, "ok": False, "error": {"code": "unsupportedOperation", "message": operation}})
            """
        ),
        encoding="utf-8",
    )
    worker.chmod(0o755)
    return worker


def test_native_worker_adapter_preserves_browser_contract(tmp_path: Path) -> None:
    root = tmp_path / "dictionaries"
    root.mkdir()
    (root / "fixture.mdx").write_bytes(b"fixture")
    client = NativeWorkerClient(
        _fake_worker(tmp_path),
        (root,),
        tmp_path / "indices",
        startup_timeout_seconds=2,
        request_timeout_seconds=2,
    )
    adapter = NativeDictionaryAdapter(
        client,
        client.dictionaries[0],
        max_resource_bytes=1024,
    )

    try:
        assert adapter.metadata.main_path == (root / "fixture.mdx").resolve()
        assert adapter.metadata.format == "mdict"
        assert adapter.metadata.icon_resource_path == "icon.png"
        assert adapter.suggestions("he", 1) == ["Hello"]
        article = adapter.lookup("hello")
        assert article is not None
        assert "gdlookup://world" in article.html
        assert "bres://native-fixture/image.png" in article.html
        assert "bres://native-fixture/oaldpe-jquery.js" in article.html
        assert "bres://native-fixture/oaldpe.js" in article.html
        css = adapter.resource("style.css")
        assert css is not None
        assert css.media_type == "text/css; charset=utf-8"
        assert b"/api/v1/dictionaries/native-fixture/resources/image.png" in css.body
        assert b"/api/v1/dictionaries/native-fixture/resources/Fonts/A.WOFF2" in css.body
        assert b"/resources/native-fixture/Fonts/A.WOFF2" not in css.body
        icon = adapter.resource("icon.png")
        assert icon is not None
        assert icon.media_type == "image/png"
        assert icon.body.startswith(b"\x89PNG\r\n\x1a\n")
        converted_tiff = adapter.resource("scan.tiff")
        assert converted_tiff is not None
        assert converted_tiff.media_type == "image/png"
        for script_name in ("oaldpe-jquery.js", "oaldpe.js"):
            script = adapter.resource(script_name)
            assert script is not None
            assert script.media_type == "text/javascript"
        case_sensitive_script = adapter.resource("Dictionary-UI.js")
        assert case_sensitive_script is not None
        assert case_sensitive_script.body == b"globalThis.dictionaryUI = true;"
        assert adapter.resource("missing.png") is None
        assert adapter.resource("../outside") is None
    finally:
        client.close()

    assert client._process.poll() == 0


def test_native_local_sidecar_symlink_cannot_escape_bundle(tmp_path: Path) -> None:
    root = tmp_path / "dictionaries"
    root.mkdir()
    (root / "fixture.mdx").write_bytes(b"fixture")
    outside = tmp_path / "outside.js"
    outside.write_bytes(b"secret")
    (root / "leak.js").symlink_to(outside)
    client = NativeWorkerClient(
        _fake_worker(tmp_path),
        (root,),
        tmp_path / "indices",
        startup_timeout_seconds=2,
        request_timeout_seconds=2,
    )
    adapter = NativeDictionaryAdapter(
        client,
        client.dictionaries[0],
        max_resource_bytes=1024,
    )

    try:
        assert adapter.resource("leak.js") is None
    finally:
        client.close()


def test_startup_scan_publishes_only_the_goldendict_worker_catalog(tmp_path: Path) -> None:
    root = tmp_path / "dictionaries"
    root.mkdir()
    mdx = root / "fixture.mdx"
    mdx.write_bytes(b"fixture")
    (root / "fixture.mdx.json").write_text(
        json.dumps(
            {
                "name": "Personal Native Fixture",
                "sourceLanguage": "auto",
                "targetLanguage": "pt-BR",
            }
        ),
        encoding="utf-8",
    )
    # The REST process never attempts to parse dictionary data itself.
    # GoldenDict-ng is the sole catalog authority, including for formats it
    # elects not to load; the JSON file only overlays published metadata.
    (root / "not-published.dsl").write_text(
        "#NAME ignored-by-fake-worker\nhello\n definition\n", encoding="utf-8"
    )
    settings = Settings(
        dictionary_roots=(root,),
        native_worker=_fake_worker(tmp_path),
        native_index_dir=tmp_path / "indices",
        native_startup_timeout_seconds=2,
        native_request_timeout_seconds=2,
    )
    service = DictionaryService(settings)
    service.scan()

    try:
        assert service.ready is True
        assert [item.id for item in service.dictionaries()] == ["native-fixture"]
        assert service.dictionaries()[0].name == "Personal Native Fixture"
        assert service.dictionaries()[0].source_language == "en"
        assert service.dictionaries()[0].target_language == "pt-br"
        response = service.lookup("hello", ["native-fixture"])
        assert response.articles[0].format == "mdict"
        assert response.articles[0].dictionary_name == "Personal Native Fixture"
        assert response.articles[0].source_language == "en"
        assert response.articles[0].target_language == "pt-br"
        assert response.articles[0].icon_url is not None
        assert response.articles[0].icon_url.endswith("/resources/icon.png")
        assert response.suggestions == ["Hello"]
        # Article bodies and prefix suggestions share one native request. The
        # previous per-adapter path emitted lookup + suggestions for every
        # selected dictionary.
        assert (tmp_path / "indices" / "requests.log").read_text(
            encoding="utf-8"
        ).splitlines() == ["lookup"]
    finally:
        service.close()


def test_invalid_dictionary_json_keeps_service_unready_and_omits_dictionary(
    tmp_path: Path,
) -> None:
    root = tmp_path / "dictionaries"
    root.mkdir()
    (root / "fixture.mdx").write_bytes(b"fixture")
    (root / "fixture.mdx.json").write_text(
        '{"sourceLangauge":"en"}',
        encoding="utf-8",
    )
    service = DictionaryService(
        Settings(
            dictionary_roots=(root,),
            native_worker=_fake_worker(tmp_path),
            native_index_dir=tmp_path / "indices",
            native_startup_timeout_seconds=2,
            native_request_timeout_seconds=2,
        )
    )

    service.scan()

    try:
        assert service.ready is False
        assert service.dictionaries() == []
        assert any(
            "fixture.mdx: native metadata: DictionaryConfigError:" in error
            for error in service.startup_errors
        )
    finally:
        service.close()


def test_native_start_failure_records_error_and_keeps_catalog_empty(tmp_path: Path) -> None:
    root = tmp_path / "dictionaries"
    root.mkdir()
    mdx = root / "fixture.mdx"
    mdx.write_bytes(b"fixture")
    settings = Settings(
        dictionary_roots=(root,),
        native_worker=tmp_path / "does-not-exist",
        native_index_dir=tmp_path / "indices",
    )
    service = DictionaryService(settings)

    service.scan()

    assert service.ready is False
    assert service.dictionaries() == []
    assert any(error.startswith("native worker: NativeWorkerError:") for error in service.startup_errors)
    service.close()


def test_unavailable_dictionary_roots_keep_service_unready(tmp_path: Path) -> None:
    root = tmp_path / "missing-dictionaries"
    service = DictionaryService(
        Settings(
            dictionary_roots=(root,),
            native_worker=_fake_worker(tmp_path),
            native_index_dir=tmp_path / "indices",
        )
    )

    service.scan()

    assert service.ready is False
    assert service.dictionaries() == []
    assert any("dictionary root is unavailable" in error for error in service.startup_errors)
    service.close()


def test_rescan_retires_previous_native_process(tmp_path: Path) -> None:
    root = tmp_path / "dictionaries"
    root.mkdir()
    (root / "fixture.mdx").write_bytes(b"fixture")
    service = DictionaryService(
        Settings(
            dictionary_roots=(root,),
            native_worker=_fake_worker(tmp_path),
            native_index_dir=tmp_path / "indices",
            native_startup_timeout_seconds=2,
            native_request_timeout_seconds=2,
        )
    )

    service.scan()
    first_process = service._native_clients[0]._process
    service.scan()

    try:
        assert first_process.poll() == 0
        assert len(service._native_clients) == 1
        assert service._native_clients[0]._process.pid != first_process.pid
    finally:
        service.close()


def test_settings_enable_native_worker_from_environment(monkeypatch, tmp_path: Path) -> None:
    worker = tmp_path / "worker"
    index = tmp_path / "indices"
    monkeypatch.setenv("GOLDENDICT_NATIVE_WORKER", os.fspath(worker))
    monkeypatch.setenv("GOLDENDICT_NATIVE_INDEX_DIR", os.fspath(index))

    settings = Settings.from_env()

    assert settings.native_worker == worker
    assert settings.native_index_dir == index
