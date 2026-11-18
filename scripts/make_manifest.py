"""
make_manifest.py - Write latest.json, the file installed copies of MedTracker read to find updates.

    python scripts/make_manifest.py --installer dist/MedTracker-Setup-1.2.0.exe --version 1.2.0 \
        --url-base https://github.com/asamoahboateng/simple-med-tracker/releases/download/v1.2.0 \
        --notes "What changed" --out latest.json

Pure standard library, so it runs anywhere (the release workflow uses it).
"""

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path


def build_manifest(installer, version, url_base, notes="", min_version="1.2.0",
                   released=None) -> dict:
    installer = Path(installer)
    digest = hashlib.sha256()
    with open(installer, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "version": version.lstrip("vV"),
        "released": released or date.today().isoformat(),
        "url": f"{url_base.rstrip('/')}/{installer.name}",
        "sha256": digest.hexdigest(),
        "size": installer.stat().st_size,
        "min_version": min_version,
        "notes": notes.strip(),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Write latest.json for a MedTracker release.")
    parser.add_argument("--installer", required=True, help="the MedTracker-Setup-X.Y.Z.exe file")
    parser.add_argument("--version", required=True, help="release version, e.g. 1.2.0")
    parser.add_argument("--url-base", required=True, help="folder URL the installer is published at")
    parser.add_argument("--notes", default="", help="release notes text")
    parser.add_argument("--notes-file", help="read the release notes from this file")
    parser.add_argument("--min-version", default="1.2.0",
                        help="oldest version that can update itself (older ones install by hand)")
    parser.add_argument("--out", default="latest.json")
    args = parser.parse_args(argv)

    notes = args.notes
    if args.notes_file:
        notes = Path(args.notes_file).read_text(encoding="utf-8")
    manifest = build_manifest(args.installer, args.version, args.url_base, notes, args.min_version)
    Path(args.out).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.out} for version {manifest['version']} ({manifest['size']} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
