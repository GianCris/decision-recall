# Decision Recall — Devpost Draft

## Project title

Decision Recall

## One-line pitch

**Memory is not authority. Decision Recall separates what was established then, what still applies now, and whether there is enough authority to reuse a decision.**

## Inspiration / problem

Agents can retrieve a past decision and still get its meaning wrong. Available records may show what was known without establishing what actually influenced the decision, what still applies after the world changes, or whether the surviving rationale is sufficient for reuse. Manually reconstructing those boundaries is slow and invites confident but unsupported conclusions.

## What it does

Decision Recall separates recorded evidence, authorized historical rationale, current applicability, and reuse sufficiency. Gemini interprets supplied human-readable decision records into bounded candidates. A deterministic core grounds those candidates and controls authority. When a required historical relation is missing, the system asks one exact human clarification, verifies the response binding server-side, and changes structured authorized state. Later evidence is reevaluated without rewriting history. If reuse sufficiency was never established, the system stops instead of inventing it.

## How it works

The deployed D-104 demonstration follows a supplier-resilience decision:

1. Original records contain Apex instability and Beacon's roughly ten-week restart delay.
2. A separately credentialed Gemini 3.7 Flash release path produces bounded interpretation candidates.
3. Beacon's factual delay is known, but whether it materially influenced D-104 is not established.
4. Decision Recall identifies that unresolved required relation and issues the exact clarification.
5. Cloud Run reconstructs the issued capture and verifies the session, gap, question, and response binding.
6. Verified human authority establishes the historical influence relation.
7. Supplied, simulated T1 evidence shows Apex no longer matches while Beacon still does.
8. The server reevaluates current applicability while preserving historical authority.
9. Reuse sufficiency was never established, so D-104 returns `INSUFFICIENT_EVIDENCE` and stops.

## Gemini and Google Cloud

**Gemini 3.7 Flash**, integrated through the **Google GenAI SDK**, maps supplied evidence into bounded candidate interpretation in a credentialed, release-proven path. Gemini does not grant authority and is not invoked by the live YES or T1 interactions.

**Google Cloud Run** serves the React application and hosts the Capture Gate and deterministic runtime. Live `POST /api/capture` verifies the human declaration against server-reconstructed issued state. Live `POST /api/reevaluate` validates supplied later-world evidence and returns the server-derived reuse result. **Google Cloud Build** and **Artifact Registry** provide the deployment path.

## What is innovative

**Gemini interprets. Decision Recall authorizes.**

Retrieval or memory makes prior evidence available. Decision Recall additionally models what that evidence is authorized to establish, when it was established, what still applies, and what remains unknown. It makes three distinctions explicit:

- interpretation ≠ authority;
- historical authority ≠ current applicability; and
- current applicability ≠ reuse sufficiency.

The result is not merely a warning around an LLM. Verified feedback mutates structured authorized state, later evidence changes evaluation without rewriting historical authority, and unestablished reuse sufficiency produces an explicit STOP rather than an invented completion.

## Collaborative Partner fit

Decision Recall leads the workflow until human authority is genuinely required. It processes supplied evidence, selects the unresolved required relation, asks the clarification, captures a server-bound declaration, mutates structured decision state, adapts evaluation to later evidence, and refuses to manufacture the next missing relation. Human feedback changes future evaluation rather than merely adding chat text.

## Demo walkthrough

Open the public demo, inspect D-104, and watch the release-proven Gemini interpretation remain separate from live authority. Answer the exact clarification. Cloud Run verifies the capture and establishes the historical relation. Supply the simulated T1 change, observe Apex stop matching while Beacon continues to match, then attempt reuse. The server returns `INSUFFICIENT_EVIDENCE` because reuse sufficiency was never established.

## Challenges

The hardest problem was preventing plausible information from silently becoming authority. We separated probabilistic interpretation from deterministic admission, kept the browser outside the authority boundary, bound human capture to the exact issued question, and kept historically established authority separate from later applicability.

## Accomplishments

- Public Cloud Run demonstration with live capture and live temporal reevaluation.
- Credentialed Gemini release evidence without implying a live model call in the hero path.
- Server-bound structured state mutation rather than conversational-only feedback.
- Tested deterministic replay, temporal evidence policy, and a deployed insufficient-evidence STOP.
- Validated frontend build and regression suites: 16 frontend tests, 41 focused backend tests, and 382 passing Python tests with 12 skipped.

## What we learned

Memory and retrieval answer what evidence is available. They do not, by themselves, answer what that evidence was authorized to establish. Human feedback is most useful when it changes explicit structured state, and temporal systems must preserve the difference between historical rationale, current applicability, and reuse sufficiency.

## What's next

The product direction is authority infrastructure for agent memory: durable event storage, multi-tenant identity, authenticated external evidence ingestion, semantic corroboration, richer policy profiles, and integrations with enterprise agent platforms. These are future directions, not capabilities claimed by the deployed demonstration.

## Scope / limitations

The deployed system demonstrates one end-to-end D-104 profile with in-memory temporal state. T1 uses supplied simulated later-world records; there is no autonomous monitoring or restart-persistent multi-user memory. Gemini evidence is release-proven separately from live capture and reevaluation. The focused credentialed checks are not a general robustness benchmark, and structural admission cannot guarantee that every semantically plausible model interpretation is correct.

## Links

- **Public demo:** https://decision-recall-296984548706.us-central1.run.app
- **Repository:** https://github.com/GianCris/decision-recall
- **One-glance architecture:** https://github.com/GianCris/decision-recall/blob/agent/decision-recall-core-v0.1/docs/architecture/decision-recall-architecture-judge.svg
- **Detailed architecture:** https://github.com/GianCris/decision-recall/blob/agent/decision-recall-core-v0.1/docs/architecture/decision-recall-architecture.svg

## Credentialed Gemini release evidence

Nine credentialed executions covered three predefined D-104 cases: normal, paraphrase, and document prompt injection, with three executions per case. All matched the frozen semantic oracle by semantic key, kind, source identity, and exact quote hash. This is a focused release check, not a general robustness benchmark. Gemini did not discover or authorize the missing Beacon historical-influence relation.

## Generalization boundary

The deployment is one D-104 supplier-resilience profile. Reusable mechanisms include grounding, semantic resolution, profile binding, gap selection, structured capture, authority policy, temporal reevaluation, and strict replay. DR-Bench separately contains 12 development and 4 design-holdout scenarios; it is research lineage, not 16 end-to-end Decision Recall validations.
