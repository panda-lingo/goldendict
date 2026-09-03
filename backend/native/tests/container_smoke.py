#!/usr/bin/env python3
"""Smoke-test the combined FastAPI/native-worker container startup contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time


def docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def make_dictionary(root: Path) -> None:
    body = (
        '#NAME "Native DSL Fixture"\n'
        '#INDEX_LANGUAGE "English"\n'
        '#CONTENTS_LANGUAGE "French"\n'
        "\n"
        "hello\n"
        "\t[b]DSL native definition[/b]\n"
    )
    (root / "fixture.dsl").write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    (root / "fixture.dsl.json").write_text(
        json.dumps(
            {
                "name": "Personal DSL Fixture",
                "sourceLanguage": "auto",
                "targetLanguage": "es-MX",
            }
        ),
        encoding="utf-8",
    )


def api_get(container_id: str, path: str) -> object:
    response = docker(
        "exec",
        container_id,
        "python",
        "-c",
        (
            "import json,sys,urllib.request; "
            "response=urllib.request.urlopen(sys.argv[1],timeout=3); "
            "print(json.dumps(json.load(response),separators=(',',':')))"
        ),
        "http://127.0.0.1:8080" + path,
    ).stdout.strip()
    return json.loads(response)


def has_metadata(value: object, expected: dict[str, str]) -> bool:
    return isinstance(value, dict) and all(
        value.get(key) == expected_value for key, expected_value in expected.items()
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="goldendict-api:native")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="goldendict-api-smoke-") as temporary:
        temporary_path = Path(temporary)
        temporary_path.chmod(0o755)
        root = temporary_path / "dictionaries"
        root.mkdir()
        make_dictionary(root)
        container_id = docker(
            "run",
            "--detach",
            "--rm",
            "--mount",
            f"type=bind,source={root},target=/dictionaries,readonly",
            args.image,
        ).stdout.strip()
        deadline = time.monotonic() + args.timeout
        try:
            while time.monotonic() < deadline:
                running = docker(
                    "inspect",
                    "--format",
                    "{{.State.Running}}",
                    container_id,
                    check=False,
                )
                if running.returncode != 0 or running.stdout.strip() != "true":
                    raise RuntimeError("combined API container exited during startup")
                health = docker(
                    "exec",
                    container_id,
                    "python",
                    "-m",
                    "app.healthcheck",
                    check=False,
                )
                if health.returncode == 0:
                    break
                time.sleep(2)
            else:
                raise RuntimeError("combined API did not become ready before the timeout")

            payload = api_get(container_id, "/api/v1/health")
            if not isinstance(payload, dict):
                raise RuntimeError(f"malformed combined API health response: {payload}")
            if payload.get("ready") is not True or payload.get("status") != "ok":
                raise RuntimeError(f"unexpected combined API health response: {payload}")
            if payload.get("dictionaryCount") != 1 or payload.get("startupErrors") != []:
                raise RuntimeError(f"combined API did not load its fixture: {payload}")

            catalog = api_get(container_id, "/api/v1/dictionaries")
            expected_metadata = {
                "name": "Personal DSL Fixture",
                "sourceLanguage": "en",
                "targetLanguage": "es-mx",
            }
            if (
                not isinstance(catalog, list)
                or len(catalog) != 1
                or not has_metadata(catalog[0], expected_metadata)
            ):
                raise RuntimeError(f"dictionary JSON metadata was not applied: {catalog}")
            for query in (
                "language=en",
                "source_language=en",
                "target_language=es",
            ):
                filtered = api_get(container_id, f"/api/v1/dictionaries?{query}")
                if not isinstance(filtered, list) or len(filtered) != 1:
                    raise RuntimeError(f"catalog filter {query} did not match: {filtered}")
            if api_get(container_id, "/api/v1/dictionaries?language=fr") != []:
                raise RuntimeError("overridden native target language still matched")

            lookup = api_get(container_id, "/api/v1/lookup/hello")
            if (
                not isinstance(lookup, dict)
                or not isinstance(lookup.get("articles"), list)
                or len(lookup["articles"]) != 1
                or not has_metadata(
                    lookup["articles"][0],
                    {
                        "dictionaryName": "Personal DSL Fixture",
                        "sourceLanguage": "en",
                        "targetLanguage": "es-mx",
                    },
                )
            ):
                raise RuntimeError(f"lookup did not use JSON metadata: {lookup}")
            print(
                json.dumps(
                    {"ok": True, "health": payload, "dictionary": catalog[0]},
                    separators=(",", ":"),
                )
            )
        except Exception:
            logs = docker("logs", container_id, check=False)
            if logs.stdout:
                print(logs.stdout)
            if logs.stderr:
                print(logs.stderr)
            raise
        finally:
            docker("rm", "--force", container_id, check=False)


if __name__ == "__main__":
    main()
