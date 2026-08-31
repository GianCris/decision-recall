# Decision Recall

## Memory is not authority.

AI agents can remember what happened and still be wrong to reuse a decision.

Decision Recall is a **bounded multi-decision authority runtime**. It separates **what was established then**, **what still applies now**, and **whether enough authorized support exists to reuse the decision**. When a required relation is missing, it asks for that relation instead of inventing it.

> **Gemini interprets. Decision Recall authorizes.**

### [Launch the live Decision Recall demo on Google Cloud Run](https://decision-recall-296984548706.us-central1.run.app/)

**Public judge demo · no login required**

Start with the flagship **D-104** walkthrough, or open [Explore Decision Recall](https://decision-recall-296984548706.us-central1.run.app/#explore) to try **D-104 Supplier Resilience** and **D-205 Release Rollback Reuse** through one shared lifecycle. Both use registered, server-owned decision profiles and instances. Live capture and later-world reevaluation run on Cloud Run; neither the live **YES** nor T1 path calls Gemini.

## Why This Matters

Given the available decision records, Decision Recall separates known facts from authorized rationale, identifies the unresolved required relation under the assigned profile, requests the missing human authority, and reevaluates later evidence without rewriting history.

Without that authority structure, later decision reuse can require manually reconstructing:

- what was known;
- what actually influenced the decision;
- what was never established;
- what changed later; and
- whether the surviving rationale is sufficient for reuse.

## What Decision Recall Changes

Three boundaries that ordinary recall alone does not establish are kept separate:

- **Interpretation is not authority.** Gemini can propose what supplied evidence means; Decision Recall controls what it may establish.
- **Historical authority is not current applicability.** A reason may have influenced the original decision even after the world changes.
- **Current applicability is not reuse sufficiency.** A surviving reason may still be insufficient to authorize reuse.

## How the Shared Lifecycle Works

```text
REGISTERED DECISION + AVAILABLE RECORDS
       ↓
BOUNDED CANDIDATES → DETERMINISTIC GROUNDING / ADMISSION
       ↓
KNOWN FACT ≠ ESTABLISHED RATIONALE
       ↓
ONE REQUIRED HISTORICAL RELATION REMAINS UNRESOLVED
       ↓
EXACT CLARIFICATION → SERVER-BOUND HUMAN AUTHORITY
       ↓
HISTORICAL RELATION ESTABLISHED
       ↓
LATER-WORLD EVIDENCE CHANGES → APPLICABILITY REEVALUATED
       ↓
SERVER-DERIVED REUSE OUTCOME
```

In the **separately release-proven interpretation path**, Gemini maps human-readable D-104 decision records into bounded candidates. The **deployed Explorer** instead uses configured example candidates mechanically grounded to registered records; it is not a live Gemini execution path. Both use the deterministic Decision Recall authority machinery, not a model-generated authorization.

In the live path, Decision Recall reconstructs the issued state, identifies the exact unresolved required relation, and asks for the human authority it cannot infer. The server verifies the response binding to the issued decision, profile, session, gap, and exact question in the registered-case API before deterministic completion establishes the historical relation. Later-world inputs are **supplied example records**, not monitoring data.

### D-104 · Supplier Resilience

The recorded decision is to **keep Apex and Beacon active for six months**. Beacon's roughly 10-week reactivation time is known; whether it materially influenced that decision is missing. A server-bound, verified human YES establishes that historical relationship.

With supplied T1 observations of **Apex on-time rate 0.987 over 30 days** and **Beacon reactivation 70 days**, Apex's original instability no longer matches while Beacon's restart delay still does. **Historical authority remains established, while current applicability is reevaluated.**

The server returns **INSUFFICIENT EVIDENCE**, with **C1** as the limiting requirement: the surviving reason's reuse sufficiency was never established. This is not a recommendation to keep or drop a supplier. **What was never established stays unestablished.**

### D-205 · Release Rollback Reuse

The recorded decision is to **roll back Orion v42 to Orion v41**. The missing historical relationship is whether Orion v41 passing every restore attempt in a one-day recovery rehearsal materially influenced the rollback. The same shared lifecycle issues the exact clarification and verifies the human response binding.

| Supplied one-day observations | Server-derived result |
|---|---|
| Release error rate **0.06**; rollback restore success **0.80** | **REUSE NOT AUTHORIZED** — `REQUIRED_SURVIVING_SUPPORT_DOES_NOT_MATCH` |
| Keep error rate **0.06**; change only restore success to **1.00** | **REUSE AUTHORIZED**, after a new server reevaluation |

Editing the observation immediately makes the previous result stale; the browser does not infer a new outcome from the number. **Same lifecycle. Different decision. Different evidence. Different outcome.**

## More Than Retrieval or Memory

| Retrieval / memory | Decision Recall additionally models |
|---|---|
| Makes relevant prior evidence available | Canonical decision identity and source provenance |
| Recalls prior records or context | What the evidence is authorized to establish |
| Supplies evidence for a current task | Historical rationale versus current applicability |
| May expose missing context | Explicit missing relations and reuse sufficiency |
| — | Deterministic replay and an explicit epistemic STOP |

**RAG retrieves relevant evidence. Decision Recall additionally models what that evidence is authorized to establish, when that authority was established, what still applies, and what remains unknown.** Decision Recall complements retrieval; it does not claim to replace it.

## Collaborative Partner

Decision Recall leads until a relation requires human authority; verified feedback changes structured decision state rather than merely adding chat text.

- **Leads:** reconstructs available decision state, processes supplied evidence, identifies the exact unresolved required relation, and issues one precise clarification where human authority is required.
- **Captures human authority:** server-binds the declaration to the issued capture session, gap, and exact question.
- **Mutates structured authorized state:** verified feedback changes the historical relation from unresolved to established.
- **Adapts:** reevaluates supplied later evidence and changes the server-derived result without rewriting historical authority; missing reuse sufficiency still causes STOP.

The human supplies only the missing historical relationship, rather than reconstructing the entire decision manually. The system leads until it reaches a boundary it cannot legitimately cross alone.

## Google Stack

- **Google Agent Framework used: Google GenAI SDK** (`google-genai` 2.14.0).
- **Gemini 3.7 Flash** produces bounded candidate evidence in a credentialed, release-proven compiler path. It does not authorize state and is not called by the live **YES** interaction.
- **Google Cloud Run** serves the built React frontend assets and hosts the legacy Capture Gate, generic registered-case API, and deterministic Decision Recall runtime.
- **Google Cloud Build** builds the committed `Dockerfile.cloudrun` image.
- **Artifact Registry** stores the Cloud Build image at `us-central1-docker.pkg.dev/<PROJECT_ID>/decision-recall/winner-slice:latest`.
- **Python** implements the deterministic runtime and server; **JavaScript, React + Motion + SVG/CSS** provide the flagship and shared Explorer presentations. The browser projects server truth and does not compute authority.

## Judge-Facing Architecture

![Decision Recall judge-facing architecture](docs/architecture/decision-recall-architecture-judge.svg)

The diagram illustrates the D-104 authority boundaries; it is not an inventory of every registered decision. Its release-evidence lane and live Cloud Run lane are not one runtime request. Release-proven Gemini interpretation supplies bounded candidates to deterministic admission. Independently, the live Capture Gate reconstructs and verifies the issued human capture; neither Gemini nor the browser grants authority directly.

The final product uses one shared lifecycle and generic case API for D-104 and D-205, with server-owned profiles determining the requirements. Interpretation ≠ authority; historical authority ≠ current applicability; current applicability ≠ reuse sufficiency. Exact human clarification is server-bound, and supplied T1 observations remain separate from historical state.

[Inspect the detailed technical architecture](docs/architecture/decision-recall-architecture.svg).

## Evidence

### Live Cloud Run Proof of Action

The flagship's legacy endpoints demonstrate live capture and reevaluation:

```text
POST /api/capture
→ server reconstructs the authoritative issued preparation
→ verifies capture session + gap + question binding
→ permits deterministic completion only after verification
→ historical relation becomes established

POST /api/reevaluate
→ server validates supplied T1 evidence policy
→ reconstructs the established historical state
→ reevaluates current applicability
→ returns INSUFFICIENT_EVIDENCE because reuse sufficiency is missing
```

The browser returns a declaration; it does not write authoritative history. Cloud Run hosts the Capture Gate and deterministic runtime that enforce that boundary.

The Explorer uses `GET /api/cases` and the same three registered-case routes for either public decision: `GET /api/cases/{decision_id}/capture-preparation`, `POST /api/cases/{decision_id}/capture`, and `POST /api/cases/{decision_id}/reevaluate`. The server reconstructs registered state and returns the canonical outcome. Public validation covered D-104 insufficient evidence, D-205 denied at 0.80 and authorized at 1.00, stale-result suppression, and invalid-timestamp rejection followed by recovery.

### Credentialed Gemini Release Evidence

There are **9 credentialed executions across 3 predefined D-104 semantic cases**:

- normal ×3;
- paraphrase ×3; and
- document prompt injection ×3.

All matched the frozen semantic oracle: **semantic key + kind + source identity + exact quote hash**.

This is release evidence for three predefined cases, **not a general robustness benchmark**. Gemini produced bounded candidates for the Apex historical role and the Beacon restart-delay fact; it did not discover or authorize the missing Beacon historical-influence relation. Gemini is not called by the live **YES** action.

The raw credentialed artifact remains local and untracked. The committed [release manifest](artifacts/pc2-credentialed-release-evidence.json) preserves its SHA-256 identity, and the committed [judge-safe projection](apps/decision-threads/src/pc2-judge-safe-gemini-projection.json) exposes only the allowlisted evidence used by the flagship presentation. This release proof is separate from the Explorer's configured, mechanically grounded example candidates.

### Frozen Validation Evidence

- Validated **pre-promotion** full backend baseline: **433 total; 421 passed, 12 skipped, 0 failures/errors**.
- Frontend tests: **29 passed, 0 failures**.
- Official frontend production build: **PASS**.
- Deployed `/api/capture`: **PASS**.
- Deployed `/api/reevaluate`: **PASS**.
- Registered-case live smoke and desktop / 360px / 390px checks: **PASS**.
- All **15 D-104 baseline digests: PASS**.

D-104 complete result fingerprint:
`9d1c7bf5fb7accf6f1b2c4cd143c11324e31d15dda79dcf640f1b3e46d5db463`

D-104 evaluation and replay fingerprint (both):
`25ab192b3301cac929185081efc83da0fc744ae47832a3910f767567d0b4adf6`

Post-merge verification used LF source bytes and the existing offline research fixtures. One oversized-JSON HTTP test encountered a Windows socket abort (`ConnectionAbortedError / WinError 10053`). Without source changes, the targeted test subsequently passed, followed by **3/3 consecutive repeats** returning the expected HTTP 400/413 behavior. The 421-pass full-suite result above is the pre-promotion baseline, **not a claimed full post-merge rerun**.

### Production Freeze Reference

- Production revision: `decision-recall-c31-d949635`.
- Image digest: `sha256:c6fb281cdbf68c5da62080490013c5eefacb5a8b8a3fb4a69f557be6494244f6`.
- Validated candidate source: `d9496353ff2d0d3e7a486291d627e075ed905168`.
- Product-freeze merge on main: `09fe579bb2924e8e82700c1abbc4526017fb16f9`.
- Shared source tree: `127372c4fb30fd05ccc6d24c9f58718b429da26e`.

The deployed image was built from the validated candidate source tree. The product-freeze merge tree is content-identical to that candidate; the image was **not rebuilt from the merge commit**. These identities record the product freeze, independently of later documentation-only commits.

## Generalization Truth

| Level | What exists |
|---|---|
| **Deployed** | Two registered decision profiles, D-104 and D-205, operating through the same shared product lifecycle and generic registered-case API. |
| **Reusable mechanisms** | Server-owned profiles, candidate grounding, semantic resolution, profile binding, gap selection, structured capture, authority policy, temporal reevaluation, deterministic reuse outcomes, and strict replay. |
| **Research lineage** | DR-Bench contains 12 development scenarios and 4 design-holdout scenarios for separate mechanism research and evaluation. |

DR-Bench is a separate research/evaluation harness. It does **not** constitute 16 end-to-end Decision Recall deployments or validations.

The deployed examples demonstrate bounded registered decisions, not arbitrary ingestion or broad cross-domain superiority.

## Scope and Limitations

- The deployed product is bounded to registered decision profiles; D-104 and D-205 are its public examples, not arbitrary decisions or external-agent ingestion.
- The deployed demonstration uses in-memory temporal state; it does not claim restart-persistent Cloud decision memory.
- The Explorer uses configured, mechanically grounded example candidates, not a live Gemini execution for each interaction. Credentialed Gemini release evidence is separate from live capture and T1 reevaluation.
- T1 uses supplied demo later-world records, not autonomous source monitoring or an authenticated enterprise system.
- Structurally admitted Gemini candidates can still be semantically wrong; deterministic grounding and policy checks do not prove arbitrary model interpretations correct.
- Enterprise-scale performance, durable multi-user persistence, and broad cross-domain superiority are not claimed. Decision Recall is not a universal RAG replacement.

## Run Locally

Requirements:

- Python 3.11 or newer (`pyproject.toml` requires `>=3.11`)
- Node.js 24 and npm (matching the committed Cloud Run build image)

From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .

Set-Location apps/decision-threads
npm ci --no-audit --no-fund
npm run build
Set-Location ../..

python -m decision_recall.product.cloudrun_server
```

Open [http://localhost:8080](http://localhost:8080). Verify the server in another terminal:

```powershell
Invoke-RestMethod http://localhost:8080/health
Invoke-RestMethod http://localhost:8080/api/capture-preparation
Invoke-RestMethod http://localhost:8080/api/cases
```

The committed npm lockfile pins the frontend dependency graph. `npm run build` generates the deterministic fallback at `apps/decision-threads/public/demo-state.json`, then builds the frontend into `apps/decision-threads/dist`. The server defaults to port `8080` and serves that directory. Open [the local Explorer](http://localhost:8080/#explore) for either registered decision. No Gemini credential is required for the local flagship or Explorer: neither executes a live model call.

Docker provides the closest local equivalent to the deployed container:

```powershell
docker build -f Dockerfile.cloudrun -t decision-recall:local .
docker run --rm -p 8080:8080 decision-recall:local
```

## Deploy to Google Cloud

These commands map to `cloudbuild.cloudrun.yaml`, `Dockerfile.cloudrun`, and runtime port `8080`. They require your own Google Cloud credentials and a project with billing enabled.

```powershell
gcloud auth login
gcloud config set project <PROJECT_ID>
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

gcloud artifacts repositories create decision-recall `
  --repository-format=docker `
  --location=us-central1 `
  --description="Decision Recall images"

gcloud builds submit --config cloudbuild.cloudrun.yaml .

gcloud run deploy decision-recall `
  --image us-central1-docker.pkg.dev/<PROJECT_ID>/decision-recall/winner-slice:latest `
  --region us-central1 `
  --platform managed `
  --allow-unauthenticated `
  --port 8080
```

Verify the deployed service:

```powershell
$URL = gcloud run services describe decision-recall `
  --region us-central1 `
  --format='value(status.url)'

Invoke-RestMethod "$URL/health"
Invoke-RestMethod "$URL/api/capture-preparation"
```

The image destination is `us-central1-docker.pkg.dev/<PROJECT_ID>/decision-recall/winner-slice:latest`. See [`docs/CLOUD_RUN_DEPLOYMENT.md`](docs/CLOUD_RUN_DEPLOYMENT.md) for operational detail.

## Tests and Reproducibility

Run the deterministic Decision Recall tests:

```powershell
python -m unittest discover -s tests -p "test_decision_recall_*.py" -v
```

Run the frontend tests and production build:

```powershell
Set-Location apps/decision-threads
npm ci --no-audit --no-fund
node --test test/*.test.mjs
npm run build
```

The committed Python constraints, npm lockfile, Dockerfile, and Cloud Build configuration define the reproducible build path. Credentialed Gemini behavior is preserved as release evidence, not as a hidden live dependency of normal build or runtime.

The historical full repository suite is `python -m unittest discover -s tests -v` from the repository root. Unlike the product test command above, research tests also require existing untracked offline fixtures: `dev-baseline-output-v4`, `round-b-v02-screening-output`, `round-b-v02-infra-recovery-output-v3`, and `decision-premise-capture-v01-sanity-output-v2`. These are not distributed as clean-clone prerequisites for the product build/runtime; do not rerun Gemini merely to reproduce them. A clone without them cannot reproduce the full historical 433-test baseline.

Byte-hashed research protocols require LF checkout bytes. On Windows, prepare a separate verification checkout with `core.autocrlf=false` **before** materializing tracked files; changing the setting after checkout does not repair existing CRLF bytes. PostgreSQL parity tests require the database environment configured in the committed CI workflow; the cited local baseline includes 12 skips. No raw credentialed Gemini artifact is required by the normal product build or tests.

## Hackathon Build Scope

Repository history begins on August 15, 2026, within the recorded August 3–31, 2026 submission period. It shows DR-Bench first committed on August 15, the submitted Decision Recall deterministic core beginning August 23, and the engine-bound demonstration and Cloud Run runtime added August 24–25. No tracked project material or incorporated pre-existing code is identifiable before the submission period.

DR-Bench, mechanism experiments, and earlier prototypes are supporting research assets, not the current judge-facing submission. They were also introduced in this repository during the submission period. If material from outside this repository was incorporated and is not represented by this history, it must be disclosed separately; repository history cannot establish untracked provenance.

## Research History

These assets preserve the research path; they are not the deployed judge experience:

- **DR-Bench v0.1** is a mechanism-agnostic benchmark for Material Decision Dependence, selective reevaluation, and minimum-disruption recovery. Its frozen dataset contains 12 development and 4 design-holdout scenarios. See [`docs/SCHEMA.md`](docs/SCHEMA.md).
- **VWS-0.5** failed its comprehension gate and is preserved at `prototypes/vws-05/`.
- **VWS-0.6** tested a simplified bilingual narrative and is preserved at `prototypes/vws-06/`; it is not the current deployed demonstration.
- Round B, reference-decomposition, and premise-capture protocols remain under [`docs/`](docs/) as scientific audit history.
- Milestone and temporal-ledger design evidence remains in [`docs/temporal-authority-ledger.md`](docs/temporal-authority-ledger.md) and the deterministic test suite.

DR-Bench commands remain available for research use after installing the project:

```powershell
python -m dr_bench list
python -m dr_bench show dev-001 --phase discovery --condition implicit
python -m dr_bench show dev-001 --phase discovery --condition structured
python -m dr_bench show dev-001 --phase recovery
```
