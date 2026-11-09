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

## 2. Point Kiro Crew at your endpoint — and raise the timeout — BEFORE consent

Order matters. **Consent binds to whatever endpoint string is set at the moment
you grant it in the dashboard.** If you grant consent while the endpoint is still
the Jev default, the running gateway keeps calling Jev and ignores a later
`config set`. So set the endpoint (and the timeout) *first*, then grant consent.

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
# A real CPU call takes ~2.9 s; the default decision timeout is 1000 ms, so raise it
# or every decision times out and falls back to Jev:
kirocrew config set decisions.provider.timeout_ms 5000
```

Changing the endpoint name, region or profile **withdraws consent** for the old
one — Kiro Crew treats each distinct endpoint string as a separate opt-in.

## 3. Turn Decisions on, THEN grant consent in the dashboard

```bash
kirocrew config set decisions.enabled true
```

All five Jev decision switches are off by default. Now open the **Decisions
consent card in the dashboard and grant consent** — with the `sagemaker://` URL
already set in step 2, consent binds to *that* URL. A `kirocrew config set` alone
**cannot** grant consent; the dashboard card is the only thing that does, and the
running gateway's consent keystone wins over config. On a timeout or failure Kiro
Crew falls back gracefully; scheduled jobs and sub-agents are never routed
through it.

## 4. Trigger a decision, then check the decision log

Do something that makes Kiro Crew decide (e.g. ask it to route a task, or run a
flow that uses acceptance evaluation). Then read the newest decision-log line:

```bash
tail -n 5 ~/.kiro/crew/decisions/decisions-$(date -u +%Y%m%d).jsonl
```

A decision that actually reached your endpoint shows **`latency_ms` in the
thousands** (a real SageMaker call measures ~2900 ms) and **no `error` field**. If
you instead see `error: "provider"` with `latency_ms: 2`, consent is still bound
to the Jev default — re-check step 2/3 order. You can cross-check with CloudWatch
(`AWS/SageMaker` → `Invocations`, `EndpointName=<name>`): a routed decision adds a
data point; a 2 ms failure adds none.

> **Not yet verified by the author.** On the author's run the endpoint itself was
> proven by 37 direct signed `InvokeEndpoint` calls, but the *gateway-routed*
> decision had not yet landed on the endpoint (consent had bound to the Jev URL).
> The steps above are the fix to try; confirm the thousands-ms, no-error log line
> yourself.

## 5. Restore your original settings

Put back the three values you recorded in step 1:

```bash
kirocrew config set decisions.enabled "<original>"
kirocrew config set decisions.provider.endpoint "<original>"   # e.g. https://api.typesafe.ai/v1/systemone
kirocrew config set decisions.provider.model "<original>"      # e.g. jev-latest
```

Do **not** run `kirocrew stop/restart/gateway` just to switch the endpoint — a
`config set` is picked up without restarting the running gateway.
