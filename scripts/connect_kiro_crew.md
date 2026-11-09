# Point Kiro Crew at your SageMaker endpoint

Kiro Crew's decision engine can route decisions to any System One server,
including a SageMaker endpoint, with a `sagemaker://` URL. The request is
SigV4-signed with **your own AWS credentials** (boto3). No API key is read or
sent, and only `sagemaker:InvokeEndpoint` is called, always to
`runtime.sagemaker.<region>.amazonaws.com`.

**Verified on Kiro Crew 0.12.0 (2026-11-09).** Following the order below, the
gateway sent four live `tool.risk` decisions to the endpoint and got answers
(2180 to 8933 ms, `error: null`, model `strands-decider-2b`), and CloudWatch
recorded exactly four invocations in that minute.

## Why the order matters

Consent binds to the endpoint string **the dashboard card displays** when you
turn Decisions on. The consent PUT has to echo that string, or the server answers
`409` and writes nothing. A Settings tab you opened *before* changing the config
still shows the old URL (the Jev default), so consenting from it binds to Jev, and
your `sagemaker://` setting is never called. On the author's first run the gateway
decision failed with `error: "provider"` in 2 ms and CloudWatch showed zero
invocations for exactly this reason.

Consent pins only the on/off switch and the endpoint string. Changing
`timeout_ms` afterwards keeps it; changing the endpoint name, region or profile
withdraws it.

## 1. Record your current settings (so you can restore them)

```bash
kirocrew config get decisions.provider.endpoint
kirocrew config get decisions.provider.model
kirocrew config get decisions.provider.timeout_ms
```

Defaults: `https://api.typesafe.ai/v1/systemone`, `jev-latest`, `1000`.

## 2. Set endpoint, model and timeout FIRST

```bash
kirocrew config set decisions.provider.endpoint "sagemaker://cb-speedrun-2-decider?region=ap-south-1"
kirocrew config set decisions.provider.model "strands-decider-2b"
kirocrew config set decisions.provider.timeout_ms 10000
```

The default `timeout_ms` of 1000 is shorter than any call to this endpoint. The
verified run used 20000, but each decision point clamps its wait to its own cap
(10 s at most, see step 5), so 10000 behaves the same.

The endpoint string is exactly `sagemaker://<endpoint-name>?region=<region>`,
optionally with `&profile=<aws-profile>`; the parser accepts nothing else. The
stack's `KiroCrewEndpointSetting` output prints it.

Check consent is still off: `~/.kiro/crew/decisions_consent.json` should show
`"enabled": false` (or not exist).

## 3. Hard-reload the dashboard, check the URL, then grant consent

1. Hard-reload the dashboard (Cmd+Shift+R) so the Settings tab re-reads the config.
2. Open **Settings > Developer > Decisions** and check the panel reads
   **"Sent to sagemaker://cb-speedrun-2-decider?region=ap-south-1"**. If it still
   names `api.typesafe.ai`, reload again; do not turn anything on yet.
3. Turn on the main **Decisions** switch, then the point you want, for example
   **Risky tool-call notes** (`tool.risk`).
4. Confirm `~/.kiro/crew/decisions_consent.json` now has `"enabled": true` and
   `"endpoint": "sagemaker://..."`.

## 4. Verify: decision log next to CloudWatch

Run a turn that calls a tool, then read the newest lines:

```bash
tail -n 5 ~/.kiro/crew/decisions/decisions-$(date -u +%Y%m%d).jsonl
```

An answered decision has `latency_ms` in the thousands, `error: null`, a
`provider_model` of `strands-decider-2b` and filled `answers`. Then check the same
UTC minute in CloudWatch (`AWS/SageMaker`, `Invocations` and `ModelLatency`,
`EndpointName=<name>`, `VariantName=v1`). The invocation count should equal the
answered lines, and the summed `ModelLatency` should sit just under the summed
`latency_ms` (the gap is network). `error: "provider"` with `latency_ms` near 2
means consent is bound to another URL: go back to step 3.

## 5. Which decisions fit this endpoint

Each decision point waits a fixed maximum, whatever `timeout_ms` says
(Kiro Crew 0.12.0, `kiro_crew/decisions/points/`):

| Point | Wait cap | Measured on ml.m5.2xlarge | Verdict |
|---|---|---|---|
| `tool.risk` (Risky tool-call notes) | 10 s | 2.2 to 8.9 s (228 to 986 input tokens), 4 of 4 answered | works |
| `skills.select` (Automatic skill choice) | 10 s | ~32 s model time for 39 skill candidates, 2 of 2 timed out | too slow on CPU |
| `compaction.keep` | 10 s | not measured | untested |
| `memory.recall` | 7 s | not measured | untested |
| `message.steer`, `model.route`, `nudge.wake` | `timeout_ms` only | not measured | untested |

Turn on `tool.risk`-style points, keep skill choice on Jev or the local model, or
use a faster instance. GPU endpoint quota was 0 on the author's account, so a GPU
instance is untested.

## 6. Restore your settings

Turn every Decisions switch off in the dashboard first, then:

```bash
kirocrew config set decisions.provider.endpoint "https://api.typesafe.ai/v1/systemone"
kirocrew config set decisions.provider.model "jev-latest"
kirocrew config set decisions.provider.timeout_ms 1000
```

A `config set` is picked up by the running gateway; do not stop or restart it to
switch endpoints.
