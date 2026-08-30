# VWS-0.6 — Narrative Simplification

Status: **ACTIVE COMPREHENSION GATE**

VWS-0.5 is formally **FAILED** as a judge-facing comprehension prototype. The failure does not reopen M1/M2/M2.1/PC1/PC2 semantics. It means the presentation exposed engine vocabulary before viewers had a usable mental model.

Observed failure signals:
- zero-context viewers did not understand who/what Apex and Beacon were;
- `reaction capacity`, `decision dependency`, `historical role`, `current match`, and `safe reuse` created avoidable cognitive load;
- the UI mixed storyboard navigation with product actions;
- the THEN/NOW table looked like an internal audit surface rather than a causal story;
- architecture labels appeared before the core mechanism was understood;
- English proficiency contaminated the first test, but translation did not recover comprehension, confirming a narrative problem beyond language alone.

## 1. Frozen semantic constraints

VWS-0.6 is presentation-only.

It must preserve these facts and boundaries:
- Apex delivery performance was materially unstable at t0.
- Beacon took roughly 10 weeks to reactivate at t0.
- Decision D-104 kept access to both suppliers for six months.
- Apex instability had an established historical role at t0.
- Beacon's historical role is **not established** before the structured human YES.
- The human declaration, not Gemini, establishes the Beacon historical role.
- Six weeks later Apex reaches 98.7% on-time delivery over 30 days.
- Historical role and current-world match are separate dimensions.
- The final evaluation result is `insufficient_evidence` with limiting requirement C1.
- No keep/drop recommendation is invented.

Do not assert supplier hierarchy (`primary`, `backup`) unless it becomes explicit canonical state. Main-surface copy may say only that the company relies on two suppliers.

## 2. Single viewer mental model

The prototype must communicate one chain only:

1. A decision was made.
2. One important reason was missing from the records.
3. Decision Recall noticed the gap while a person could still answer.
4. The person's answer became part of the historical record.
5. The world changed later.
6. The historical record did not get rewritten by the new world state.
7. When reuse was attempted, one required relation had never been established.
8. Decision Recall stopped exactly there instead of inventing certainty.

Gemini, provenance, authorization IDs, replay hashes, C1, and ontology vocabulary stay out of the main comprehension story.

## 3. Five-state narrative contract

### State 1 — SITUATION

Headline:

> A company relies on two suppliers.

Show two simple supplier facts:
- **Apex** — deliveries have been unstable.
- **Beacon** — takes about 10 weeks to restart.

Then reveal the decision:

> **Decision: keep access to both suppliers for 6 months.**

Do not show historical-role terminology yet.

### State 2 — MISSING KNOWLEDGE

Headline:

> **Decision Recall found something the records can't tell us.**

Question:

> **Was keeping Beacon available an important reason for this decision?**

Primary action: **Yes**.

Secondary structured answers may exist but must be visually subordinate. No separate `Next` action competes with the answer.

Before the human answer, the UI must show neither an implicit YES nor an implicit NO.

### State 3 — CAPTURED

After structured YES:

> **Captured at decision time**

> Keeping Beacon available was part of the original reasoning.

The visual transition should communicate `? → established record` without exposing implementation labels.

### State 4 — SIX WEEKS LATER

Show the new world evidence first:

> **Apex improves to 98.7% on-time delivery.**

Then show two visually distinct layers.

#### What mattered then
- Apex instability — recorded as part of the original reasoning.
- Keeping Beacon available — recorded as part of the original reasoning.

#### What matches now
- Apex instability — **no longer matches**.
- Beacon restart delay — **still matches** current conditions.

Required explanatory line:

> **The world changed. The historical record didn't.**

Never render `Beacon mattered → still matches` as one continuous status. Historical role and current-world match are different objects.

### State 5 — REUSE BOUNDARY

Introduce the attempted action before the stop:

> **A similar decision comes up again.**

> **Can we reuse the old decision?**

Visual boundary:

`Beacon mattered ───── ? ───── Reuse`

Human-language missing relation:

> **Was that reason enough by itself?**

Hero:

# I CAN'T ESTABLISH THAT

Status:

**REUSE STATUS · INSUFFICIENT EVIDENCE**

Supporting copy:

> **We know Beacon mattered to the original decision.**
>
> **We never established whether that reason was enough on its own.**

Canonical `C1 / sufficient_alone(R2)` remains proof/debug detail only.

## 4. Visual direction for the prototype

VWS-0.6 is still a cheap comprehension prototype, not production UI.

Use a simplified **Temporal Threads** visual grammar:
- dots represent established points in the record;
- lines represent continuity through time;
- a broken/current-state line represents a condition that no longer matches;
- a question-mark gap represents a relation that was never established;
- the UI never draws the missing edge after the epistemic boundary.

The visual system should be lighter in cognitive load than VWS-0.5:
- fewer boxes and badges;
- larger semantic typography;
- stronger contrast;
- one primary action per state;
- no architecture pills in the main flow;
- no table for THEN/NOW;
- no generic Previous/Next wizard behavior in the intended flow.

No React, Motion, Rive, Three.js, Spline, Cloud Run, or presentation adapter work is part of this checkpoint.

## 5. Bilingual test contract

The same prototype must support **ES | EN** from one semantic source so the two copies cannot drift.

### Gate 1 — concept comprehension
Use Spanish with viewers who do not have an English-language barrier.

Pass if at least **4/5** can reconstruct in substance:
- there was a decision;
- something important was missing from the records;
- the person supplied that missing knowledge;
- the answer became part of the historical record;
- later conditions changed without rewriting that record;
- reuse stopped because sufficiency had never been established.

### Gate 2 — final-language comprehension
After Gate 1 passes, test the same story in English with five English-capable viewers.

Pass if at least **4/5** reconstruct the same mental model without needing project-specific vocabulary.

Diagnostic only, not a formal gate:

> What is different here from ChatGPT using documents?

We want spontaneous recognition that the product captures human-only missing knowledge and later knows the exact boundary of what was never established.

## 6. After VWS-0.6 passes

Freeze narrative meaning and proceed to VWS-1A:
- presentation DTO/read model over frozen backend outputs;
- final visual-language contract;
- Temporal Threads implementation choice;
- then VWS-1B real React/Motion/SVG winner slice;
- backend-bound state transitions and UI↔engine truth tests;
- Cloud Run deployment early after the real vertical exists;
- proof/replay drawer;
- second comprehension + memorability test;
- controlled baseline only within supported claim scope.

## Reopen rule

VWS-0.6 may change wording, visual hierarchy, or navigation only in response to comprehension evidence. It must not reopen frozen semantics or introduce presentation facts not supported by canonical state.
