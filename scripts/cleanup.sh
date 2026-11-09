#!/usr/bin/env bash
# Tear down EVERYTHING this project created, then verify each resource is gone.
#
# Idempotent: every step tolerates an already-absent resource, so re-running after
# a partial failure is safe. Order matters -- the endpoint is deleted first
# (stops billing immediately), then config/model, then the CloudFormation stack
# (which removes the bucket, ECR repo, CodeBuild project+role, exec role,
# invoke-only policy and Budget), then a final verify pass.
#
# Usage:
#   ./cleanup.sh [region] [project-name]
# Example:
#   ./cleanup.sh ap-south-1 cb-speedrun-2-decider
set -uo pipefail   # NOT -e: we want to continue past already-deleted resources

REGION="${1:-ap-south-1}"
PROJECT="${2:-cb-speedrun-2-decider}"
STACK="$PROJECT"
AWS=(aws --region "$REGION")

echo "==> Deleting SageMaker endpoint (stops billing first)"
"${AWS[@]}" sagemaker delete-endpoint --endpoint-name "$PROJECT" 2>/dev/null \
  && echo "    delete-endpoint requested" || echo "    endpoint already absent"

echo "==> Deleting endpoint-config and model"
"${AWS[@]}" sagemaker delete-endpoint-config --endpoint-config-name "${PROJECT}-cfg" 2>/dev/null \
  && echo "    endpoint-config deleted" || echo "    endpoint-config already absent"
"${AWS[@]}" sagemaker delete-model --model-name "$PROJECT" 2>/dev/null \
  && echo "    model deleted" || echo "    model already absent"

# The stack cannot delete a non-empty bucket or repo; empty them first.
BUCKET="${PROJECT}-$(aws sts get-caller-identity --query Account --output text 2>/dev/null)-${REGION}"
echo "==> Emptying S3 bucket $BUCKET (all versions)"
if "${AWS[@]}" s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  # delete all object versions and delete markers so DeletionPolicy:Delete succeeds
  "${AWS[@]}" s3 rm "s3://$BUCKET" --recursive 2>/dev/null || true
  VERS="$("${AWS[@]}" s3api list-object-versions --bucket "$BUCKET" \
    --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}, DeleteMarkers: DeleteMarkers[].{Key:Key,VersionId:VersionId}}' \
    --output json 2>/dev/null)"
  if [[ -n "$VERS" && "$VERS" != "null" ]]; then
    echo "$VERS" > /tmp/cleanup-versions.json
    python3 - "$BUCKET" "$REGION" <<'PY' || true
import json, subprocess, sys
bucket, region = sys.argv[1], sys.argv[2]
data = json.load(open("/tmp/cleanup-versions.json"))
items = (data.get("Objects") or []) + (data.get("DeleteMarkers") or [])
items = [i for i in items if i and i.get("Key")]
if items:
    payload = {"Objects": [{"Key": i["Key"], "VersionId": i["VersionId"]} for i in items], "Quiet": True}
    subprocess.run(["aws", "s3api", "delete-objects", "--region", region,
                    "--bucket", bucket, "--delete", json.dumps(payload)], check=False)
PY
  fi
else
  echo "    bucket already absent"
fi

echo "==> Deleting ECR images (so the repo can be removed by the stack)"
"${AWS[@]}" ecr list-images --repository-name "$PROJECT" --query 'imageIds' --output json 2>/dev/null \
  | { read -r ids; [[ -n "${ids:-}" && "$ids" != "[]" && "$ids" != "null" ]] \
      && "${AWS[@]}" ecr batch-delete-image --repository-name "$PROJECT" --image-ids "$ids" >/dev/null 2>&1 \
      && echo "    images deleted" || echo "    no images / repo absent"; }

echo "==> Deleting the CloudFormation stack (bucket, ECR, CodeBuild, roles, policy, budget)"
if "${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" >/dev/null 2>&1; then
  "${AWS[@]}" cloudformation delete-stack --stack-name "$STACK"
  echo "    waiting for stack deletion ..."
  "${AWS[@]}" cloudformation wait stack-delete-complete --stack-name "$STACK" \
    && echo "    stack deleted" || echo "    WARN: stack delete did not complete cleanly; check the console"
else
  echo "    stack already absent"
fi

echo
echo "==> Verify each resource is gone"
FAIL=0
check() { # desc, command that should FAIL (resource absent)
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "    STILL PRESENT: $desc"; FAIL=1
  else
    echo "    gone:          $desc"
  fi
}
check "endpoint"        "${AWS[@]}" sagemaker describe-endpoint --endpoint-name "$PROJECT"
check "endpoint-config" "${AWS[@]}" sagemaker describe-endpoint-config --endpoint-config-name "${PROJECT}-cfg"
check "model"           "${AWS[@]}" sagemaker describe-model --model-name "$PROJECT"
check "ECR repo"        "${AWS[@]}" ecr describe-repositories --repository-names "$PROJECT"
check "S3 bucket"       "${AWS[@]}" s3api head-bucket --bucket "$BUCKET"
check "CodeBuild"       "${AWS[@]}" codebuild batch-get-projects --names "${PROJECT}-build" --query 'projects[0].name'
check "stack"           "${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK"

if [[ "$FAIL" -eq 0 ]]; then
  echo
  echo "All resources verified gone. Teardown complete."
  exit 0
else
  echo
  echo "Some resources remain (see STILL PRESENT above). Re-run ./cleanup.sh." >&2
  exit 1
fi
