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
