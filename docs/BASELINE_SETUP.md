# Baseline provider setup

The real adapter uses Google Cloud Agent Platform through the official
`google-genai` SDK and Application Default Credentials (ADC). It does not read
API keys and does not use Express Mode.

Fixed provider target:

- project: `decision-recall-hackathon`
- location: `global`
- model: `gemini-3.7-flash`
- API version: `v1`
- SDK: `google-genai==2.14.0`

## Local authentication

Install the Google Cloud CLI, sign in to the intended account, and create local
ADC credentials:

```powershell
gcloud auth application-default login
gcloud auth application-default set-quota-project decision-recall-hackathon
gcloud config set project decision-recall-hackathon
```

The account must have access to the project, billing must be enabled, and the
required Vertex AI / Agent Platform API must be enabled. Do not create or place
service-account key files or API keys in this repository.

## Explicit sanity call

The command below makes exactly one requested call: B0, `dev-001`, repetition
`1`, using `gemini-3.7-flash`.

```powershell
python -m dr_baselines.sanity --execute
```

Running the module without `--execute` refuses to call the provider. Imports and
tests never construct a provider client or make a network request.

## Explicit structured-output sanity call

The separate command below makes exactly one B0, `dev-001`, repetition `1`
call using the unchanged B0 prompt and Gemini native JSON structured output:

```powershell
python -m dr_baselines.structured_sanity --output-dir structured-sanity-output --execute
```

The output directory must not already exist. The command writes one `run.json`
RunRecord and refuses to construct the provider adapter without `--execute`.
This technical check is not an experimental run or result.

## Fixed baseline pilot

The pilot command is fixed to `dev-005`, `dev-002`, and `dev-006`; B0, B1, and
B2; and one repetition, for exactly nine calls. It refuses to start without
explicit opt-in and requires a new output directory:

```powershell
python -m dr_baselines.pilot --output-dir pilot-output --execute
```

The directory must not already exist. It receives append-only `runs.jsonl` and
`evaluations.jsonl` files plus a deterministic `summary.json`. Invalid responses
and isolated provider errors are retained and never retried. Authentication or
other systemic client-configuration failures abort the remaining matrix.

## Frozen DEV baseline experiment

After the runner implementation is committed and approved, prepare a new output
directory without making provider calls:

```powershell
python -m dr_baselines.dev_experiment --output-dir dev-baseline-output-v4 --prepare
```

Audit the frozen `execution_plan.json` and `experiment_manifest.json`, then use
the same directory for the explicit 72-call execution:

```powershell
python -m dr_baselines.dev_experiment --output-dir dev-baseline-output-v4 --execute
```

Execution refuses changed plan bytes, changed manifest design fields, a changed
Git commit, tracked source modifications, existing run artifacts, non-DEV IDs,
or any output path containing a sealed-holdout component. Untracked historical
output directories do not affect the tracked-source cleanliness check.

The `dev-baselines-v0.4` transport policy uses the public `google-genai`
`HttpOptions` API with `timeout=120000` milliseconds and
`HttpRetryOptions(attempts=1)`. The latter counts the original request and
therefore disables SDK retries. A scientific slot is one frozen matrix position;
a delivery attempt is one infrastructure attempt to obtain that slot's single
model response. The harness permits at most four delivery attempts only for the
frozen pre-response transient classes, with deterministic 5/10/20-second
backoff and no jitter. This schedule is a precommitted harness policy, not a
provider guarantee.

The first model response permanently closes its scientific slot. Incorrect or
invalid model responses are never retried. Exhausted or nonretryable delivery
failures create one terminal failed-slot record, receive no evaluation or gap
filling, and do not stop the remaining matrix; any such slot makes the result
ineligible for official-result status. Delivery evidence is appended to
`delivery_attempts.jsonl`.

An operator interruption writes an append-only lifecycle event and an aborted,
non-official `summary.json`;
the interrupted directory cannot be resumed or reused.

The fixed, sequential 10-second delay remains between terminal scientific
slots, with no delay before slot one or after slot 72, and no jitter,
adaptation, or concurrency.
