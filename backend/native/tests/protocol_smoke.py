#!/usr/bin/env python3
"""Generate tiny DSL/StarDict bundles and smoke-test the Docker worker."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import selectors
import struct
import subprocess
import tempfile


SUPPORTED_LOCAL_FORMATS = (
    "bgl",
    "stardict",
    "lsa",
    "dsl",
    "dictd",
    "xdxf",
    "sdict",
    "aard",
    "zipsounds",
    "mdx",
    "gls",
    "slob",
    "zim",
    "epwing",
)


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
    records = [
        (b"empty", b""),
        (b"hello", b"<b>StarDict native definition</b>"),
        (b"help", b"Help entry"),
    ]
    dictionary = bytearray()
    index = bytearray()
    for word, article in records:
        offset = len(dictionary)
        dictionary.extend(article)
        index.extend(word + b"\0" + struct.pack(">II", offset, len(article)))
    (root / "fixture.dict").write_bytes(dictionary)
    (root / "fixture.idx").write_bytes(index)
    # StarDict synonyms point to the zero-based article position in .idx.
    # Cross-dictionary lookup should resolve this alias to "hello" and pass
    # that shared alternate to the DSL reader as GoldenDict-ng ArticleMaker does.
    (root / "fixture.syn").write_bytes(b"greeting\0" + struct.pack(">I", 1))
    (root / "fixture.ifo").write_text(
        "StarDict's dict ifo file\n"
        "version=2.4.2\n"
        "bookname=Native StarDict Fixture\n"
        f"wordcount={len(records)}\n"
        "synwordcount=1\n"
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
        dsl_root = root / "dsl"
        stardict_root = root / "stardict"
        dsl_root.mkdir()
        stardict_root.mkdir()
        make_dsl(dsl_root)
        make_stardict(stardict_root)
        (dsl_root / "metadata.toml").write_text(
            'fts = true\n[metadata]\nname = "Metadata DSL Fixture"\n',
            encoding="utf-8",
        )
        (stardict_root / "metadata.toml").write_text(
            '[metadata]\nname = "Metadata StarDict Fixture"\n',
            encoding="utf-8",
        )
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
            if tuple(ready.get("supportedFormats", [])) != SUPPORTED_LOCAL_FORMATS:
                raise RuntimeError(
                    f"worker does not advertise complete local format parity: {ready}"
                )
            by_format = {item.get("format"): item for item in dictionaries if isinstance(item, dict)}
            for format_name, expected, expected_name in (
                ("dsl", "DSL native definition", "Metadata DSL Fixture"),
                (
                    "stardict",
                    "StarDict native definition",
                    "Metadata StarDict Fixture",
                ),
            ):
                metadata = by_format.get(format_name)
                if not isinstance(metadata, dict) or not metadata.get("mainPath"):
                    raise RuntimeError(f"{format_name} metadata/mainPath was not published: {ready}")
                if metadata.get("name") != expected_name:
                    raise RuntimeError(
                        f"{format_name} metadata.toml name was not applied: {metadata}"
                    )
                if format_name == "dsl" and (
                    metadata.get("sourceLanguage") != "en"
                    or metadata.get("targetLanguage") != "fr"
                ):
                    raise RuntimeError(
                        "DSL in-file language headers were not detected: "
                        f"{metadata}"
                    )
                icon_path = metadata.get("iconResourcePath")
                if not isinstance(icon_path, str) or not icon_path:
                    raise RuntimeError(f"{format_name} native icon was not published: {metadata}")
                icon = request(
                    process,
                    f"icon-{format_name}",
                    "resource",
                    dictionaryId=metadata["id"],
                    path=icon_path,
                )
                try:
                    icon_bytes = base64.b64decode(icon.get("bodyBase64", ""), validate=True)
                except (ValueError, TypeError) as error:
                    raise RuntimeError(f"{format_name} icon was not valid base64: {icon}") from error
                if icon.get("mediaType") != "image/png" or not icon_bytes.startswith(
                    b"\x89PNG\r\n\x1a\n"
                ):
                    raise RuntimeError(f"{format_name} icon was not a PNG: {icon}")
                result = request(
                    process,
                    f"lookup-{format_name}",
                    "lookup",
                    word="hello",
                    dictionaryIds=[metadata["id"]],
                    suggestionLimit=10,
                )
                articles = result.get("articles")
                if not isinstance(articles, list) or expected not in articles[0].get("html", ""):
                    raise RuntimeError(f"{format_name} lookup did not return expected article: {result}")
                if articles[0].get("format") != format_name:
                    raise RuntimeError(f"{format_name} lookup reported wrong format: {result}")
                if "hello" not in [
                    str(value).casefold() for value in result.get("suggestions", [])
                ]:
                    raise RuntimeError(
                        f"{format_name} batched lookup suggestions missing hello: {result}"
                    )
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
            batch = request(
                process,
                "lookup-batch",
                "lookup",
                word="hello",
                dictionaryIds=[item["id"] for item in by_format.values()],
                suggestionLimit=10,
            )
            batch_formats = {
                article.get("format")
                for article in batch.get("articles", [])
                if isinstance(article, dict)
            }
            if batch_formats != {"dsl", "stardict"}:
                raise RuntimeError(f"batched lookup did not return both dictionaries: {batch}")
            if "hello" not in [
                str(value).casefold() for value in batch.get("suggestions", [])
            ]:
                raise RuntimeError(f"batched lookup suggestions missing hello: {batch}")
            synonym_batch = request(
                process,
                "lookup-cross-dictionary-synonym",
                "lookup",
                word="greeting",
                dictionaryIds=[item["id"] for item in by_format.values()],
                suggestionLimit=0,
            )
            synonym_html = {
                article.get("format"): article.get("html", "")
                for article in synonym_batch.get("articles", [])
                if isinstance(article, dict)
            }
            if "StarDict native definition" not in synonym_html.get(
                "stardict", ""
            ) or "DSL native definition" not in synonym_html.get("dsl", ""):
                raise RuntimeError(
                    "shared StarDict synonym was not applied across the selected "
                    f"catalog: {synonym_batch}"
                )
            empty = request(
                process,
                "lookup-empty",
                "lookup",
                word="empty",
                dictionaryIds=[by_format["stardict"]["id"]],
                suggestionLimit=0,
            )
            empty_articles = empty.get("articles")
            if (
                not isinstance(empty_articles, list)
                or len(empty_articles) != 1
                or "Query error:" in empty_articles[0].get("html", "")
            ):
                raise RuntimeError(
                    f"successful zero-byte record was mislabeled as an error: {empty}"
                )
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
