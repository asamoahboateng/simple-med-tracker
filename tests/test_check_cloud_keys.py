"""scripts/check_cloud_keys.py: the release build stops early when the MinIO keys are missing or wrong."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_cloud_keys.py"


def run(*args, keys=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("MINIO_")}
    env.update(keys or {})
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          env=env, cwd=ROOT)


def test_missing_keys_fail():
    result = run()
    assert result.returncode == 1
    assert "MINIO_ACCESS_KEY and MINIO_SECRET_KEY are not set" in result.stdout


def test_missing_keys_only_warn_when_allowed():
    result = run("--allow-missing")
    assert result.returncode == 0
    assert "::warning::" in result.stdout


def test_working_keys_pass(fake_s3):
    result = run("--endpoint", fake_s3.cfg.endpoint,
                 keys={"MINIO_ACCESS_KEY": "AKEY123", "MINIO_SECRET_KEY": "SKEY456"})
    assert result.returncode == 0, result.stdout
    assert "MinIO keys work" in result.stdout
    assert "AKEY123" not in result.stdout + result.stderr
    assert "SKEY456" not in result.stdout + result.stderr


def test_rejected_keys_fail(fake_s3):
    fake_s3.fail_with = (403, "InvalidAccessKeyId")
    result = run("--endpoint", fake_s3.cfg.endpoint,
                 keys={"MINIO_ACCESS_KEY": "AKEY123", "MINIO_SECRET_KEY": "SKEY456"})
    assert result.returncode == 1
    assert "::error::" in result.stdout and "refused access" in result.stdout
    assert "SKEY456" not in result.stdout + result.stderr
