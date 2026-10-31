"""infrastructure/deploy-on-merge.sh against a fake box.

The box-side deploy restarts telos-web and then probes it. It used to probe once,
4s after the restart, and read HTTP 000 whenever Next.js had not started listening
yet (telos deploy runs 40582494053 and 41174930868) although the service came up
moments later. These tests pin the bounded retry that replaced it: a slow start
passes, a service that never answers still fails within the deadline, and a failed
build never restarts anything.

Every external command (git, npm, sudo, systemctl, curl) is a stub on PATH; nothing
here touches a real box or real data.
"""

import os
import re
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "infrastructure" / "deploy-on-merge.sh"

STUBS = {
    "git": 'echo abc1234\n',
    "npm": 'echo "npm $*" >> "$FAKE_LOG"\n'
    'if [ "$1" = build ] || [ "$2" = build ]; then exit "${FAKE_BUILD_RC:-0}"; fi\n',
    "sudo": 'exec "$@"\n',
    "systemctl": 'echo "systemctl $*" >> "$FAKE_LOG"\n'
    'if [ "$1" = is-active ]; then echo activating; fi\n',
    # Answers 000 (no connection) for the first FAKE_DOWN_PROBES calls, then 200.
    "curl": 'n=$(cat "$FAKE_PROBES" 2>/dev/null || echo 0); n=$((n + 1))\n'
    'echo "$n" > "$FAKE_PROBES"\n'
    'if [ "$n" -le "${FAKE_DOWN_PROBES:-0}" ]; then printf 000; exit 7; fi\n'
    'printf 200\n',
}


@pytest.fixture
def box(tmp_path):
    (tmp_path / "telos" / "web").mkdir(parents=True)
    (tmp_path / "telos-ops").mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in STUBS.items():
        stub = bindir / name
        stub.write_text("#!/bin/bash\n" + body)
        stub.chmod(0o755)
    return tmp_path


def run(box, **env):
    full_env = {
        "PATH": f"{box / 'bin'}:{os.environ['PATH']}",
        "TELOS_REPO": str(box / "telos"),
        "TELOS_HEALTH_INTERVAL": "0.1",
        "FAKE_LOG": str(box / "calls.log"),
        "FAKE_PROBES": str(box / "probes"),
        **env,
    }
    started = time.monotonic()
    proc = subprocess.run(
        ["bash", str(SCRIPT)], env=full_env, capture_output=True, text=True, timeout=60
    )
    return proc, time.monotonic() - started


def calls(box):
    log = box / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def probes(box):
    return int((box / "probes").read_text()) if (box / "probes").exists() else 0


def test_slow_start_is_waited_for_not_failed(box):
    proc, _ = run(box, FAKE_DOWN_PROBES="3", TELOS_HEALTH_TIMEOUT="10")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "deploy OK — telos-web HTTP 200" in proc.stdout
    assert probes(box) == 4
    assert calls(box).count("systemctl restart telos-web") == 1


def test_service_that_never_answers_fails_within_the_deadline(box):
    proc, elapsed = run(box, FAKE_DOWN_PROBES="100000", TELOS_HEALTH_TIMEOUT="2")
    assert proc.returncode == 1
    assert "telos-web check FAILED (HTTP 000" in proc.stdout
    assert "telos-web unit: activating" in proc.stdout
    assert probes(box) > 1
    assert elapsed < 10


def test_failed_build_never_restarts_or_probes(box):
    proc, _ = run(box, FAKE_BUILD_RC="1")
    assert proc.returncode == 1
    assert "web build FAILED" in proc.stdout
    assert not any(c.startswith("systemctl") for c in calls(box))
    assert probes(box) == 0


def test_default_deadline_fits_the_workflow_wait_budget():
    # .github/workflows/deploy.yml waits with `aws ssm wait command-executed`
    # (20 x 5s = 100s) and a deploy's install + build already takes ~45s, so the
    # probe deadline must leave room for the output of a failed probe to be read.
    match = re.search(r'TELOS_HEALTH_TIMEOUT:-(\d+)', SCRIPT.read_text())
    assert match and int(match.group(1)) <= 30
    assert "http://127.0.0.1:3001/dash" in SCRIPT.read_text()
