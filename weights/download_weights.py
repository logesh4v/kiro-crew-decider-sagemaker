#!/usr/bin/env python3
"""Download Strands Decider 2B weights from the public CDN and verify sha256.

Reads ``manifest.json`` (pinned sha256 + size for all 16 files), downloads each
file from the public weights CDN into ``weights/files/``, and verifies every
sha256 against the pin. Writes a checksum log (expected vs computed) to
``weights/checksums.json``.

Idempotent: a file already present with the right size and sha256 is not
re-downloaded. Exit status is 0 only if every file matches its pin.

Usage:  python3 download_weights.py
Then:   ./package_model.sh    (tars weights/files/ into model.tar.gz)
"""
import hashlib
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "manifest.json")
OUT_DIR = os.path.join(HERE, "files")
LOG = os.path.join(HERE, "checksums.json")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    with open(MANIFEST) as f:
        m = json.load(f)
    cdn = m["cdn"]
    model_prefix = m["model_prefix"]
    results = []
    ok = True
    for entry in m["files"]:
        rel = entry["path"]
        # A file may carry an explicit CDN source path (e.g. the base model lives
        # under a different prefix); otherwise it is <model_prefix>/<path>.
        src = entry.get("source") or f"{model_prefix}/{rel}"
        url = f"{cdn}/{src}"
        dest = os.path.join(OUT_DIR, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        need = True
        if os.path.exists(dest) and os.path.getsize(dest) == entry["size"]:
            if sha256_file(dest) == entry["sha256"]:
                need = False
        if need:
            print(f"downloading {rel} ({entry['size']} bytes) ...", flush=True)
            tmp = dest + ".part"
            with urllib.request.urlopen(url) as r, open(tmp, "wb") as out:
                while True:
                    buf = r.read(1024 * 1024)
                    if not buf:
                        break
                    out.write(buf)
            os.replace(tmp, dest)
        size = os.path.getsize(dest)
        digest = sha256_file(dest)
        match = (digest == entry["sha256"] and size == entry["size"])
        ok = ok and match
        results.append({
            "path": rel,
            "url": url,
            "expected_sha256": entry["sha256"],
            "computed_sha256": digest,
            "expected_size": entry["size"],
            "computed_size": size,
            "match": match,
        })
        print(f"  {'OK ' if match else 'BAD'} {rel}", flush=True)
    with open(LOG, "w") as f:
        json.dump({"all_match": ok, "files": results}, f, indent=2)
    print(f"\nall_match={ok}  log={LOG}")
    if not ok:
        print("ERROR: one or more files failed sha256 verification.", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
