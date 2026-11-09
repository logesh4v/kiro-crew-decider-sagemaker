#!/usr/bin/env python3
"""Verify the Strands Decider 2B SageMaker endpoint with ONE signed call.

Sends the exact ``/v1/systemone`` JSON body Kiro Crew's ``sagemaker://`` decision
route sends (impl_sagemaker.py -> impl_systemone._to_wire): a ``state``, the
``model`` name, and a ``questions`` map. ContentType and Accept are
``application/json``. The request is SigV4-signed by boto3 from your own AWS
credentials -- no API key. For image/Box questions Kiro Crew adds the SageMaker
CustomAttributes ``TypeSafe-Danger-Zone-Images=true`` (the images themselves
travel inside the body as ``assets``); --with-image-attr sets that header.

Prints the endpoint's answer and exits 0 if the response parses as the expected
``{"answers": {...}}`` shape.

Usage:
  python3 verify.py --endpoint cb-speedrun-2-decider --region ap-south-1
  python3 verify.py --endpoint NAME --region R --profile myprofile
"""
import argparse
import json
import sys

import boto3


def build_body() -> dict:
    # Exactly the shape impl_systemone._to_wire() produces: a choice question with
    # a rubric per option. (Kiro Crew may send an option rubric as null; the
    # serving shim rewrites null -> "" before the model sees it.)
    return {
        "state": "A deploy is green in staging but one flaky test failed once. Ship to prod now, or hold for a clean run?",
        "model": "strands-decider-2b",
        "questions": {
            "ship_or_hold": {
                "type": "choice",
                "instructions": "Pick the safer action given the flaky test.",
                "criteria": {
                    "ship": "choose when the flake is unrelated and rollback is cheap",
                    "hold": "choose when the failure could mask a real regression",
                },
            }
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--endpoint", required=True, help="SageMaker endpoint name")
    ap.add_argument("--region", required=True)
    ap.add_argument("--profile", default=None, help="AWS profile (optional)")
    ap.add_argument("--with-image-attr", action="store_true",
                    help="send the TypeSafe-Danger-Zone-Images=true custom attribute")
    args = ap.parse_args()

    session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()
    client = session.client("sagemaker-runtime", region_name=args.region)

    body = json.dumps(build_body()).encode()
    kwargs = dict(
        EndpointName=args.endpoint,
        ContentType="application/json",
        Accept="application/json",
        Body=body,
    )
    if args.with_image_attr:
        kwargs["CustomAttributes"] = "TypeSafe-Danger-Zone-Images=true"

    resp = client.invoke_endpoint(**kwargs)
    raw = resp["Body"].read()
    try:
        parsed = json.loads(raw)
    except ValueError:
        print("FAIL: response was not JSON:\n" + raw.decode(errors="replace"), file=sys.stderr)
        return 1

    print(json.dumps(parsed, indent=2))
    answers = parsed.get("answers") if isinstance(parsed, dict) else None
    if not isinstance(answers, dict) or "ship_or_hold" not in answers:
        print("FAIL: expected an 'answers' map with 'ship_or_hold'.", file=sys.stderr)
        return 1
    print("\nPASS: endpoint answered the /v1/systemone body with a valid answers map.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
