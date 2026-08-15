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
