#!/usr/bin/env bash
# Deploy Strands Decider 2B to a SageMaker real-time endpoint.
#
# Two passes, so you never pay for an endpoint before the image and weights exist:
#   Pass 1 (foundation): S3 bucket, ECR repo, CodeBuild role+project, Budget,
#           invoke-only policy, SageMaker exec role.  CreateEndpoint=false.
#   Pass 2 (endpoint):   after the image is in ECR and model.tar.gz is in S3,
#           re-deploy with CreateEndpoint=true to create model+config+endpoint.
#
# Prereqs: awscli v2, docker (only for the local-build fallback), a built
# weights/model.tar.gz (see weights/README path), and credentials for the target
# account/region. Nothing here is destructive; cleanup.sh removes everything.
#
# Usage:
#   ./deploy.sh <budget-email> [region] [project-name] [instance-type]
# Example:
#   ./deploy.sh you@example.com ap-south-1 cb-speedrun-2-decider ml.m5.2xlarge
set -euo pipefail

EMAIL="${1:?usage: ./deploy.sh <budget-email> [region] [project] [instance-type]}"
REGION="${2:-ap-south-1}"
PROJECT="${3:-cb-speedrun-2-decider}"
INSTANCE="${4:-ml.m5.2xlarge}"
STACK="$PROJECT"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TEMPLATE="$ROOT/infra/template.yaml"

AWS=(aws --region "$REGION")

echo "==> Pass 1: foundation stack ($STACK) in $REGION"
"${AWS[@]}" cloudformation deploy \
  --stack-name "$STACK" \
  --template-file "$TEMPLATE" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ProjectName="$PROJECT" \
    InstanceType="$INSTANCE" \
    BudgetEmail="$EMAIL" \
    CreateEndpoint=false

BUCKET="$("${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text)"
REPO_URI="$("${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='RepositoryUri'].OutputValue" --output text)"
BUILD="$("${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='CodeBuildProject'].OutputValue" --output text)"
echo "    bucket=$BUCKET  repo=$REPO_URI  build=$BUILD"

echo "==> Upload serving source and model.tar.gz to S3"
# source.zip = the container build context (Dockerfile + serve.py + requirements).
TMP="$(mktemp -d)"
cp "$ROOT/container/Dockerfile" "$ROOT/container/serve.py" "$ROOT/container/requirements.txt" "$TMP/"
cp "$ROOT/container/buildspec.yml" "$TMP/" 2>/dev/null || cp "$HERE/buildspec.yml" "$TMP/" 2>/dev/null || true
( cd "$TMP" && zip -q -r source.zip . )
"${AWS[@]}" s3 cp "$TMP/source.zip" "s3://$BUCKET/source/source.zip"
rm -rf "$TMP"

if [[ ! -f "$ROOT/weights/model.tar.gz" ]]; then
  echo "ERROR: $ROOT/weights/model.tar.gz missing. Run weights/download_weights.py" >&2
  echo "       then weights/package_model.sh, and re-run this script." >&2
  exit 1
fi
"${AWS[@]}" s3 cp "$ROOT/weights/model.tar.gz" "s3://$BUCKET/model/model.tar.gz"

echo "==> Build the serving image via CodeBuild (-> ECR)"
BUILD_ID="$("${AWS[@]}" codebuild start-build --project-name "$BUILD" \
  --query build.id --output text)"
echo "    build id=$BUILD_ID  (waiting for SUCCEEDED ...)"
while true; do
  STATUS="$("${AWS[@]}" codebuild batch-get-builds --ids "$BUILD_ID" \
    --query 'builds[0].buildStatus' --output text)"
  [[ "$STATUS" == "IN_PROGRESS" ]] || break
  sleep 15
done
echo "    build status=$STATUS"
[[ "$STATUS" == "SUCCEEDED" ]] || { echo "ERROR: build did not succeed" >&2; exit 1; }

echo "==> Pass 2: create the SageMaker model + endpoint (billing starts here)"
"${AWS[@]}" cloudformation deploy \
  --stack-name "$STACK" \
  --template-file "$TEMPLATE" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ProjectName="$PROJECT" \
    InstanceType="$INSTANCE" \
    BudgetEmail="$EMAIL" \
    CreateEndpoint=true \
    ImageUri="$REPO_URI:v1" \
    ModelDataS3Key=model/model.tar.gz

echo "==> Waiting for endpoint InService ..."
"${AWS[@]}" sagemaker wait endpoint-in-service --endpoint-name "$PROJECT"
echo "Endpoint $PROJECT is InService in $REGION."
echo "Verify it:   python3 scripts/verify.py --endpoint $PROJECT --region $REGION"
echo "Connect Kiro Crew: see scripts/connect_kiro_crew.md"
