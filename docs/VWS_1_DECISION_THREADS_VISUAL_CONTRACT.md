# VWS-1 Decision Threads — Temporal Observatory Visual Contract

## Status

- Decision Threads: **visual metaphor frozen** unless a concrete semantic or judge-comprehension blocker appears.
- Temporal Observatory: **approved primary art direction**.
- This contract governs the judge-facing winner slice only. It does not reopen M1/M2/M2.1/PC1/PC2 semantics.

## Product truth

The visual layer is a projection of the frozen engine. It must never compute or invent authority, epistemic state, current-world match, reuse result, limiting requirement, or boundary.

Authoritative flow:

```text
Frozen engine
  -> Presentation DTO
  -> Decision Threads visual state
  -> React + Motion + SVG/CSS
```

## Visual metaphor

A decision is shown as a persistent temporal graph.

- **Instrument node** = source/world condition, recorded decision, current evaluation signal, or reuse destination.
- **Solid historical thread** = established/authorized historical relation.
- **Muted historical thread** = history remains established after time advances.
- **Dotted current trace** = current-world evaluation. It is intentionally not rendered with the same grammar as historical authority.
- **Red current trace** = current mismatch.
- **Amber missing trace** = required relation not established.
- **?** = exact epistemic boundary.
- **Pulse** = one event-driven justified traversal. Pulses must never loop continuously as decoration.
- **Unsupported segment not rendered** = the system has no authority to continue.

## Spatial rule

The application is one persistent observatory, not five slides and not three north-star panels. Apex, Beacon and D-104 preserve spatial continuity while state changes around them.

The canvas owns most of the attention. Explanatory copy is contextual support, not the primary narrator.

Three semantic planes must remain perceptible:

```text
OBSERVED WORLD
DECISION MEMORY
CURRENT WORLD
```

These are semantic layers, not generic dashboard columns.

## Motion grammar

Motion must encode product meaning.

### Detect

1. A justified traversal leaves observed evidence.
2. Apex reaches the recorded decision.
3. Beacon traversal reaches the missing historical edge.
4. Pulse stops at `?`.
5. Motion quiets.
6. The contextual human question appears at that gap.

### Ask -> mutate durable state

1. Human answers YES.
2. `?` resolves.
3. The historical edge draws into the persistent graph.
4. Exactly one pulse traverses the newly established edge.
5. The graph remains changed for later phases.

This mutation must be visually obvious because it is central to the Collaborative Partner story: the agent is not merely reading; the durable decision state changes from human feedback.

### Then -> now

1. Time advances without replacing the historical graph.
2. Historical edges become quieter but remain present.
3. Current evidence appears through a different dotted evaluation grammar.
4. Apex current instability mismatches.
5. Beacon restart-delay current evidence matches.

Historical role and current-world match must never look like the same relation type.

### Reuse stop — signature moment

1. A reuse traversal begins only over justified state.
2. It reaches the required sufficiency relation.
3. The pulse stops at `?`.
4. The unsupported edge remains physically undrawn / only indicated as unavailable.
5. Hold a short visual silence before explanation.
6. Only then reveal `I CAN'T ESTABLISH THAT`.

The desired reaction is: **"I saw the reasoning physically stop at the exact relation it was not authorized to invent."**

## Hero copy

The mechanism leads; text explains after the mechanism.

Preferred final explanation:

```text
I CAN'T ESTABLISH THAT

Beacon mattered to the original decision.
What was never established: was that reason sufficient on its own?
```

Use engine-derived `insufficient_evidence` as status language. Do not claim an external block/action the engine does not model.

## Proof UI

Hashes, engine-bound metadata, C1 identifiers, Gemini/compiler details and replay evidence belong in a secondary `Why / Proof` layer. They must not compete with the hero canvas.

## Prohibited visual shortcuts

Do not add:

- generic SaaS sidebars or card walls;
- constant decorative particles/pulses;
- random glassmorphism;
- neural-network imagery unrelated to actual semantics;
- 3D/Rive purely for spectacle;
- dead controls;
- a literal three-panel reproduction of the north-star concept art.

Every important effect must answer: **what property of Decision Recall does this teach the judge?**

## Visual Pass 2 acceptance targets

1. Canvas dominates attention.
2. Apex/Beacon/D-104 persist spatially across the full golden loop.
3. Human YES visibly mutates durable state.
4. Historical and current evaluation grammars are unmistakably different.
5. Pulses are event-driven only.
6. Final boundary is visually understood before the hero copy appears.
7. Debug/proof information is demoted from the hero.
8. No overflow or camera-visible unfinished chrome.

## Local run

From `apps/decision-threads`:

```bash
npm install
npm run dev
```

`npm run dev` first executes the real deterministic winner loop and exports `public/demo-state.json`; Vite then serves the React experience.
