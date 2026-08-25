# Cloud Run deployment — Decision Threads

This is the minimum Google Cloud infrastructure path for the judge-facing Decision Recall winner slice.

## What runs in the container

The image contains:

- the built React + Motion + SVG Decision Threads frontend;
- the real Decision Recall Python package;
- a small runtime server at `decision_recall.product.cloudrun_server`;
- `GET /healthz` for deployment proof;
- `GET /api/presentation` which executes the deterministic golden loop at request time and returns the same read model used by the winner slice.

The frontend currently still ships the deterministic build-time `demo-state.json` for the stable hero path. The runtime API is added now so Cloud Run proves the real engine is present and executable inside the hosted service. Binding the interactive hero directly to this endpoint is the next live-integration step, not a change to frozen semantics.

## Local container check

From the repository root:

```powershell
docker build -f Dockerfile.cloudrun -t decision-recall:local .
docker run --rm -p 8080:8080 decision-recall:local
```

Then check:

```powershell
Invoke-RestMethod http://localhost:8080/healthz
Invoke-RestMethod http://localhost:8080/api/presentation
```

Open:

```text
http://localhost:8080/
```

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

Create a Docker repository once. `us-central1` is a practical default for Cloud Run; change the region consistently if needed.

```powershell
gcloud artifacts repositories create decision-recall \
  --repository-format=docker \
  --location=us-central1 \
  --description="Decision Recall hackathon images"
```

PowerShell can also run that as one line if line continuation is inconvenient.

## Build and push

```powershell
gcloud builds submit \
  --tag us-central1-docker.pkg.dev/decision-recall-hackathon/decision-recall/winner-slice:latest \
  --file Dockerfile.cloudrun .
```

If the installed `gcloud builds submit` version does not accept `--file`, temporarily copy/rename `Dockerfile.cloudrun` to `Dockerfile` locally for the build only; do not delete or reset tracked work.

## Deploy

```powershell
gcloud run deploy decision-recall \
  --image us-central1-docker.pkg.dev/decision-recall-hackathon/decision-recall/winner-slice:latest \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --port 8080
```

After deployment, save the returned `.run.app` URL.

Verify both the UI and engine endpoint:

```powershell
$URL = gcloud run services describe decision-recall --region us-central1 --format='value(status.url)'
Invoke-RestMethod "$URL/healthz"
Invoke-RestMethod "$URL/api/presentation"
Start-Process $URL
```

## Video proof target

The final recording should visibly prove that the hosted service is real without making infrastructure the hero:

1. briefly show the Cloud Run service/dashboard or the `.run.app` URL;
2. load the hosted winner slice;
3. perform the continuous judge-facing flow;
4. use the Why / Proof layer for engine/replay evidence rather than cluttering the main canvas.

Do not present a build-time replay as a fresh Gemini call. The deterministic hero and the live Gemini/Vertex evidence remain separate claims until the live path is explicitly bound and labeled.
