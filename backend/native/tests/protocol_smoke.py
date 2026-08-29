#!/usr/bin/env python3
"""Generate tiny DSL/StarDict bundles and smoke-test the Docker worker."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import selectors
import struct
import subprocess
import tempfile


def make_dsl(root: Path) -> None:
    body = (
        '#NAME "Native DSL Fixture"\n'
        '#INDEX_LANGUAGE "English"\n'
        '#CONTENTS_LANGUAGE "French"\n'
        "\n"
        "hello\n"
        "\t[b]DSL native definition[/b]\n"
    )
    (root / "fixture.dsl").write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))


def make_stardict(root: Path) -> None:
    records = [(b"hello", b"<b>StarDict native definition</b>"), (b"help", b"Help entry")]
    dictionary = bytearray()
    index = bytearray()
    for word, article in records:
        offset = len(dictionary)
        dictionary.extend(article)
        index.extend(word + b"\0" + struct.pack(">II", offset, len(article)))
    (root / "fixture.dict").write_bytes(dictionary)
    (root / "fixture.idx").write_bytes(index)
    (root / "fixture.ifo").write_text(
        "StarDict's dict ifo file\n"
        "version=2.4.2\n"
        "bookname=Native StarDict Fixture\n"
        f"wordcount={len(records)}\n"
        f"idxfilesize={len(index)}\n"
        "sametypesequence=h\n",
        encoding="utf-8",
    )


def read_json_line(process: subprocess.Popen[str], timeout: float) -> dict:
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        if not selector.select(timeout):
            raise RuntimeError("timed out waiting for worker output")
        line = process.stdout.readline()
    finally:
        selector.close()
    if not line:
        stderr = process.stderr.read() if process.stderr is not None else ""
        raise RuntimeError(f"worker exited before a response: {stderr}")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise RuntimeError("worker emitted a non-object JSON value")
    return value


def request(process: subprocess.Popen[str], request_id: str, operation: str, **values) -> dict:
    assert process.stdin is not None
    process.stdin.write(json.dumps({"id": request_id, "op": operation, **values}) + "\n")
    process.stdin.flush()
    response = read_json_line(process, 30)
    if response.get("id") != request_id or response.get("ok") is not True:
        raise RuntimeError(f"worker request failed: {response}")
    result = response.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"worker returned malformed result: {response}")
    return result


def request_error(
    process: subprocess.Popen[str],
    request_id: str,
    operation: str,
    expected_code: str,
    **values,
) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps({"id": request_id, "op": operation, **values}) + "\n")
    process.stdin.flush()
    response = read_json_line(process, 30)
    error = response.get("error")
    if (
        response.get("id") != request_id
        or response.get("ok") is not False
        or not isinstance(error, dict)
        or error.get("code") != expected_code
    ):
        raise RuntimeError(f"worker did not reject unsafe request: {response}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="goldendict-api:native")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="goldendict-native-smoke-") as temporary:
        temporary_path = Path(temporary)
        temporary_path.chmod(0o755)
        root = temporary_path / "dictionaries"
        root.mkdir()
        make_dsl(root)
        make_stardict(root)
        process = subprocess.Popen(
            [
                "docker",
                "run",
                "--rm",
                "-i",
                "--mount",
                f"type=bind,source={root},target=/dictionaries,readonly",
                "--entrypoint",
                "goldendict-native-worker",
                args.image,
                "--dictionary-root",
                "/dictionaries",
                "--index-dir",
                "/var/lib/goldendict/indices",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            ready = read_json_line(process, 120)
            if ready.get("event") != "ready":
                raise RuntimeError(f"worker did not become ready: {ready}")
            dictionaries = ready.get("dictionaries")
            if not isinstance(dictionaries, list):
                raise RuntimeError("ready event has no dictionaries")
            by_format = {item.get("format"): item for item in dictionaries if isinstance(item, dict)}
            for format_name, expected in (
                ("dsl", "DSL native definition"),
                ("stardict", "StarDict native definition"),
            ):
                metadata = by_format.get(format_name)
                if not isinstance(metadata, dict) or not metadata.get("mainPath"):
                    raise RuntimeError(f"{format_name} metadata/mainPath was not published: {ready}")
                result = request(
                    process,
                    f"lookup-{format_name}",
                    "lookup",
                    word="hello",
                    dictionaryIds=[metadata["id"]],
                )
                articles = result.get("articles")
                if not isinstance(articles, list) or expected not in articles[0].get("html", ""):
                    raise RuntimeError(f"{format_name} lookup did not return expected article: {result}")
                if articles[0].get("format") != format_name:
                    raise RuntimeError(f"{format_name} lookup reported wrong format: {result}")
                suggestions = request(
                    process,
                    f"suggest-{format_name}",
                    "suggestions",
                    prefix="hel",
                    limit=10,
                    dictionaryIds=[metadata["id"]],
                )
                if "hello" not in [str(value).casefold() for value in suggestions.get("suggestions", [])]:
                    raise RuntimeError(f"{format_name} suggestions missing hello: {suggestions}")
            request_error(
                process,
                "resource-traversal",
                "resource",
                "validationFailed",
                dictionaryId=by_format["dsl"]["id"],
                path="../etc/hostname",
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "formats": sorted(by_format),
                        "upstreamCommit": ready.get("upstreamCommit"),
                        "upstreamDirty": ready.get("upstreamDirty"),
                    },
                    separators=(",", ":"),
                )
            )
        finally:
            if process.stdin is not None:
                process.stdin.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
