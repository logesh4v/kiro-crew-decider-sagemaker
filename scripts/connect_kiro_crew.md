# Point Kiro Crew at your SageMaker endpoint

Kiro Crew's decision engine ("Jev Decisions") can route decisions to any
System One server, including a SageMaker endpoint, with a `sagemaker://` URL. The
request is SigV4-signed with **your own AWS credentials** (boto3) — no API key is
read or sent — and only `sagemaker:InvokeEndpoint` is called, always to
`runtime.sagemaker.<region>.amazonaws.com`.

## 1. Record your current settings first (so you can restore them)

```bash
kirocrew config get decisions.enabled
kirocrew config get decisions.provider.endpoint
kirocrew config get decisions.provider.model
```

Write the three values down. The default endpoint is the hosted Jev service
(`https://api.typesafe.ai/v1/systemone`, model `jev-latest`); pointing at your own
endpoint replaces it only while you have it set.

## 2. Point Kiro Crew at your endpoint

The endpoint string is exactly (from the stack's `KiroCrewEndpointSetting` output):

```
sagemaker://<endpoint-name>?region=<region>
```

Optionally add `&profile=<aws-profile>` to use a named profile instead of the
default credential chain. The parser is strict — only `region` and `profile` are
accepted.

```bash
kirocrew config set decisions.provider.endpoint "sagemaker://cb-speedrun-2-decider?region=ap-south-1"
kirocrew config set decisions.provider.model "strands-decider-2b"
```

Changing the endpoint name, region or profile **withdraws consent** for the old
one — Kiro Crew treats each distinct endpoint string as a separate opt-in.

## 3. Turn Decisions on

```bash
kirocrew config set decisions.enabled true
```

All five Jev decision switches are off by default. Enabling `decisions.enabled`
lets Kiro Crew route the decisions you have turned on (model routing, acceptance
evaluation, etc.) through the endpoint. On a timeout or failure Kiro Crew falls
back gracefully; scheduled jobs and sub-agents are never routed through it.

## 4. Trigger a few decisions, then read the decision log

Do something that makes Kiro Crew decide (e.g. ask it to route a task, or run a
flow that uses acceptance evaluation). Then read the decision log — Kiro Crew
records each decision (which endpoint answered, latency, outcome) to its gateway
log:

```bash
# tail the gateway log and look for the decision lines naming your endpoint:
tail -n 200 ~/.kiro/crew/logs/gateway.log | grep -i -E "decision|sagemaker|systemone"
```

(If your install logs elsewhere, use the Decisions view in the dashboard, or
`kirocrew logs` for the gateway stream.) You should see the decision routed to
`cb-speedrun-2-decider`, not to `api.typesafe.ai`.

## 5. Restore your original settings

Put back the three values you recorded in step 1:

```bash
kirocrew config set decisions.enabled "<original>"
kirocrew config set decisions.provider.endpoint "<original>"   # e.g. https://api.typesafe.ai/v1/systemone
kirocrew config set decisions.provider.model "<original>"      # e.g. jev-latest
```

Do **not** run `kirocrew stop/restart/gateway` just to switch the endpoint — a
`config set` is picked up without restarting the running gateway.
