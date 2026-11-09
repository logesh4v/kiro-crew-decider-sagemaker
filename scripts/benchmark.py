#!/usr/bin/env python3
"""Benchmark the Strands Decider 2B SageMaker endpoint.

Fires N sequential InvokeEndpoint calls with the same /v1/systemone body verify.py
uses, measures client-observed round-trip latency per call, and reports
p50/p90/p99 plus the cold-start split: the FIRST call (cold) is reported
separately from the warm steady-state (calls 2..N), because the first request to
a freshly-placed instance pays model-load/JIT cost the rest do not.

Latency here is wall-clock round trip from this host, so it includes network RTT
to the region -- run it from the same region you deploy in for representative
numbers, and treat it as an upper bound on server compute time.

Usage:
  python3 benchmark.py --endpoint cb-speedrun-2-decider --region ap-south-1 -n 30
"""
import argparse
import json
import statistics
import sys
import time

import boto3

BODY = {
    "state": "Ship the flaky deploy to prod now, or hold for a clean run?",
    "model": "strands-decider-2b",
    "questions": {
        "ship_or_hold": {
            "type": "choice",
            "instructions": "Pick the safer action.",
            "criteria": {"ship": "flake unrelated, rollback cheap", "hold": "could mask a regression"},
        }
    },
}


def pct(values, p):
    """Nearest-rank percentile on a sorted copy (no interpolation)."""
    if not values:
        return float("nan")
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * len(s) + 0.5)) - 1))
    return s[k]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--region", required=True)
    ap.add_argument("--profile", default=None)
    ap.add_argument("-n", "--num", type=int, default=30, help="total invocations (>=2)")
    args = ap.parse_args()
    if args.num < 2:
        print("ERROR: -n must be >= 2 (need at least one cold + one warm).", file=sys.stderr)
        return 2

    session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()
    client = session.client("sagemaker-runtime", region_name=args.region)
    payload = json.dumps(BODY).encode()
    payload_bytes = len(payload)

    latencies_ms = []
    errors = 0
    for i in range(args.num):
        t0 = time.perf_counter()
        try:
            resp = client.invoke_endpoint(
                EndpointName=args.endpoint,
                ContentType="application/json",
                Accept="application/json",
                Body=payload,
            )
            resp["Body"].read()
        except Exception as e:  # noqa: BLE001 - report and keep going
            errors += 1
            print(f"  call {i+1}: ERROR {e}", file=sys.stderr)
            continue
        dt = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(dt)
        tag = "cold" if i == 0 else "warm"
        print(f"  call {i+1:>3} [{tag}] {dt:8.1f} ms")

    if not latencies_ms:
        print("No successful calls.", file=sys.stderr)
        return 1

    cold = latencies_ms[0]
    warm = latencies_ms[1:] if len(latencies_ms) > 1 else []

    print("\n=== results ===")
    print(f"endpoint      : {args.endpoint} ({args.region})")
    print(f"payload       : {payload_bytes} bytes")
    print(f"calls ok/err  : {len(latencies_ms)}/{errors}")
    print(f"cold (1st)    : {cold:.1f} ms")
    if warm:
        print(f"warm count    : {len(warm)}")
        print(f"warm p50      : {pct(warm, 50):.1f} ms")
        print(f"warm p90      : {pct(warm, 90):.1f} ms")
        print(f"warm p99      : {pct(warm, 99):.1f} ms")
        print(f"warm mean     : {statistics.mean(warm):.1f} ms")
        print(f"warm min/max  : {min(warm):.1f} / {max(warm):.1f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
