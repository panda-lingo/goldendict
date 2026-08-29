#!/usr/bin/env python3
"""Smoke-test the combined FastAPI/native-worker container startup contract."""

from __future__ import annotations

import argparse
import json
import subprocess
import time


def docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="goldendict-api:native")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()

    container_id = docker("run", "--detach", "--rm", args.image).stdout.strip()
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

        response = docker(
            "exec",
            container_id,
            "python",
            "-c",
            (
                "import json,urllib.request; "
                "response=urllib.request.urlopen("
                "'http://127.0.0.1:8080/api/v1/health',timeout=3); "
                "print(json.dumps(json.load(response),separators=(',',':')))"
            ),
        ).stdout.strip()
        payload = json.loads(response)
        if payload.get("ready") is not True or payload.get("status") != "ok":
            raise RuntimeError(f"unexpected combined API health response: {payload}")
        if payload.get("startupErrors") != []:
            raise RuntimeError(f"combined API reported startup errors: {payload}")
        print(json.dumps({"ok": True, "health": payload}, separators=(",", ":")))
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
