#!/usr/bin/env bash
# Package the verified Strands Decider 2B weights into model.tar.gz for SageMaker.
#
# SageMaker extracts the tarball to /opt/ml/model, so the weight files must sit at
# the ARCHIVE ROOT (not inside a top-level folder). serve.py reads /opt/ml/model
# and /opt/ml/model/base.
#
# Run download_weights.py first so weights/files/ exists and every sha256 matches
# its pin; this script refuses to package unverified weights.
#
# Usage:  ./package_model.sh
# Output: model.tar.gz in this directory, and its sha256 printed.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FILES="$HERE/files"
LOG="$HERE/checksums.json"
OUT="$HERE/model.tar.gz"

if [[ ! -d "$FILES" ]]; then
  echo "ERROR: $FILES not found. Run 'python3 download_weights.py' first." >&2
  exit 1
fi

# Refuse to package if the checksum log is missing or any file failed its pin.
if [[ ! -f "$LOG" ]]; then
  echo "ERROR: $LOG not found. Run 'python3 download_weights.py' first." >&2
  exit 1
fi
if ! python3 -c "import json,sys; sys.exit(0 if json.load(open('$LOG')).get('all_match') else 1)"; then
  echo "ERROR: checksums.json reports all_match=false. Re-run download_weights.py." >&2
  exit 1
fi

echo "Packaging weights from $FILES (root-level, for /opt/ml/model) ..."
# -C into files/ so paths in the tar are relative to the model root.
tar -czf "$OUT" -C "$FILES" .

if command -v sha256sum >/dev/null 2>&1; then
  SHA="$(sha256sum "$OUT" | awk '{print $1}')"
else
  SHA="$(shasum -a 256 "$OUT" | awk '{print $1}')"
fi
SIZE="$(wc -c < "$OUT" | tr -d ' ')"
echo "Wrote $OUT"
echo "  size   : $SIZE bytes"
echo "  sha256 : $SHA"
echo
echo "Next: upload it to your S3 bucket, e.g."
echo "  aws s3 cp model.tar.gz s3://<your-bucket>/model/model.tar.gz --region <region>"
