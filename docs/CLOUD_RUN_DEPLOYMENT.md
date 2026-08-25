# Cloud Run deployment — Decision Threads

This is the minimum Google Cloud infrastructure path for the judge-facing Decision Recall winner slice.

## What runs in the container

The image contains:

- the built React + Motion + SVG Decision Threads frontend;
- the real Decision Recall Python package;
- a small runtime server at `decision_recall.product.cloudrun_server`;
- `GET /health` for public deployment proof;
- `GET /api/presentation`, which executes the deterministic golden loop at request time and returns the judge-facing presentation DTO.

Cloud Run reserves some URL paths ending in `z`, so the public health proof route is `/health`, not `/healthz`. The server keeps `/healthz` only as a harmless local alias if that request reaches the application.

The frontend now prefers the live runtime DTO:

```text
/api/presentation
```

If that request fails, the UI falls back explicitly to the deterministic build-time state:

```text
/demo-state.json
```

The UI must label those two states differently:

```text
Cloud Run · live engine

deterministic fallback
```

A fallback is never presented as a fresh live execution.

## Local container check

Docker is optional for the hackathon workflow. If Docker is installed, from the repository root:

```powershell
docker build -f Dockerfile.cloudrun -t decision-recall:local .
docker run --rm -p 8080:8080 decision-recall:local
```

Then check:

```powershell
Invoke-RestMethod http://localhost:8080/health
Invoke-RestMethod http://localhost:8080/api/presentation
```

Open:

```text
http://localhost:8080/
```

If Docker is not installed, use Cloud Build directly as described below.

## Google Cloud one-time setup

Use project:

```text
decision-recall-hackathon
```

Set the project and enable the minimum services:

```powershell
gcloud config set project decision-recall-hackathon
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```

Create the Docker repository once:

```powershell
gcloud artifacts repositories create decision-recall --repository-format=docker --location=us-central1 --description="Decision Recall hackathon images"
```

If it already exists, do not recreate it.

## Build and push

Use the committed Cloud Build config so the build is reproducible and does not depend on local Docker:

```powershell
gcloud builds submit --config cloudbuild.cloudrun.yaml .
```

The config builds `Dockerfile.cloudrun` and publishes:

```text
us-central1-docker.pkg.dev/decision-recall-hackathon/decision-recall/winner-slice:latest
```

Do not deploy if the Cloud Build status is not `SUCCESS`.

## Deploy

```powershell
gcloud run deploy decision-recall --image us-central1-docker.pkg.dev/decision-recall-hackathon/decision-recall/winner-slice:latest --region us-central1 --platform managed --allow-unauthenticated --port 8080
```

After deployment, obtain the service URL:

```powershell
$URL = gcloud run services describe decision-recall --region us-central1 --format='value(status.url)'
$URL
```

Verify the deployment and the real engine endpoint:

```powershell
Invoke-RestMethod "$URL/health"
Invoke-RestMethod "$URL/api/presentation"
Start-Process $URL
```

Expected health proof:

```text
status  = ok
service = decision-recall
runtime = cloud-run-live
```

Expected presentation proof includes the real golden-loop projection, including `D-104`, `R2`, current match states, `C1`, `insufficient_evidence`, and matching evaluation/replay hashes.

## Hosted UI truth rule

When the hosted UI successfully loads `/api/presentation`, the judge-facing badge may say:

```text
Cloud Run · live engine
```

If runtime loading fails and the build-time deterministic file is used, the badge must say:

```text
deterministic fallback
```

The fallback exists for demo resilience, not to simulate a live Cloud Run execution.

## Video proof target

The final recording should visibly prove that the hosted service is real without making infrastructure the hero:

1. briefly show the Cloud Run service/dashboard or the `.run.app` URL;
2. load the hosted winner slice and show the `Cloud Run · live engine` state;
3. perform the continuous judge-facing flow;
4. use the Why / Proof layer for engine/replay evidence rather than cluttering the main canvas;
5. separately demonstrate or reference the credentialed Gemini/Vertex evidence without making the hero dependent on a fresh probabilistic call.

Do not present deterministic replay/fallback as a fresh Gemini call. Gemini evidence, human declaration, policy authority, deterministic evaluation, and Cloud Run execution remain distinct claims.
