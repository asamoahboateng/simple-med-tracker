"""
scripts/check_cloud_keys.py - Check the MinIO keys before a release is built.

Reads MINIO_ACCESS_KEY / MINIO_SECRET_KEY (GitHub Actions secrets) and makes one read-only
request to the bucket, so a release never ships with missing or wrong keys. The keys are
never printed. Messages use GitHub's ::error:: / ::warning:: format.

    python scripts/check_cloud_keys.py [--allow-missing] [--endpoint URL]

--allow-missing: missing keys only give a warning (manual runs, which publish no release).
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from s3client import S3Config, S3Error, list_objects  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-missing", action="store_true")
    parser.add_argument("--endpoint", default=config.CLOUD_ENDPOINT)
    args = parser.parse_args()

    access = os.environ.get("MINIO_ACCESS_KEY", "").strip()
    secret = os.environ.get("MINIO_SECRET_KEY", "").strip()
    if not (access and secret):
        level = "warning" if args.allow_missing else "error"
        print(f"::{level}::MINIO_ACCESS_KEY and MINIO_SECRET_KEY are not set "
              f"(Settings > Secrets and variables > Actions). Without them cloud backup "
              f"will not be available in this build.")
        return 0 if args.allow_missing else 1

    cfg = S3Config(args.endpoint, config.CLOUD_BUCKET, access, secret)
    try:
        list_objects(cfg, "medtracker-key-check/", timeout=30)   # read-only, matches nothing
    except S3Error as exc:
        print(f"::error::The MinIO keys did not work with {args.endpoint} "
              f"(bucket '{config.CLOUD_BUCKET}'): {exc}")
        return 1
    print(f"MinIO keys work with {args.endpoint} (bucket '{config.CLOUD_BUCKET}').")
    return 0


if __name__ == "__main__":
    sys.exit(main())
