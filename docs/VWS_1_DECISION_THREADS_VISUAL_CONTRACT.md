# VWS-1 — Decision Threads Visual Contract

Status: ACTIVE WINNER-SLICE IMPLEMENTATION

VWS-0.5 failed because it exposed engine vocabulary. VWS-0.6 simplified the narrative but still behaved like a five-step storyboard. VWS-1 keeps the VWS-0.6 meaning and moves to one persistent temporal decision canvas bound to frozen engine output.

## Product goal

A judge should be able to watch the graph itself and infer the core product behavior:

`detect gap -> ask once -> capture human-only knowledge -> preserve history -> reevaluate current world -> stop at exact unsupported edge`

The visualization is not decoration. Every visual primitive has a semantic meaning.

## Decision Threads grammar

- **Node**: evidence, condition, decision, or reuse target.
- **Solid green thread**: an established/authorized relationship or currently supported path.
- **Muted historical thread**: preserved historical structure that is not being recomputed away by current evidence.
- **Broken/red thread**: a current-world match that no longer holds.
- **Dashed amber thread**: a required relationship that is not established.
- **Question node**: exact epistemic boundary.
- **Moving pulse**: Decision Recall traversing a justified path; it may never cross an unsupported edge.
- **Thread draw after human YES**: durable state mutation caused by the structured declaration.
- **THEN -> NOW rail**: history and current world are different dimensions.

## Required continuous interaction

1. The original decision and observable supplier facts exist in one persistent graph.
2. Apex's historical support is already established.
3. Beacon's historical-role edge terminates at a visible question boundary.
4. The single contextual human question appears at that gap.
5. YES completes the Beacon historical thread; no dead alternative controls are shown in the golden path.
6. Time advances without replacing the graph.
7. Apex current-world match changes; the historical edge remains visible.
8. Beacon's current-world condition is evaluated independently from its historical role.
9. A reuse target appears.
10. Traversal reaches the missing sufficiency relation.
11. The pulse stops at the question node and the unsupported segment is not drawn.
12. Hero: **I CAN'T ESTABLISH THAT** with the engine-derived `insufficient_evidence` boundary.

## Truth-binding rule

The UI must never decide epistemic truth.

`decision_recall.product.presentation.build_decision_threads_presentation()` projects the frozen `GoldenLoopResult` into a presentation DTO. The React shell consumes the exported DTO. The adapter performs no LLM call, no authority recomputation, and no temporal inference.

Human-readable labels and geometry may be presentation mappings, but these fields must come directly from the backend DTO:

- issued critical-gap question;
- R2 relation identity and knowledge state;
- current match states;
- safe reuse result;
- limiting requirements;
- exact limiting boundary;
- evaluation and replay hashes.

If the golden result shape is ambiguous, the adapter fails rather than inventing UI state.

## Stack

- React
- Motion for React
- SVG/CSS
- Vite

No Three.js/Rive unless a concrete comprehension advantage appears. No generic dashboard/sidebar/card-wall architecture.

## Local run

From `apps/decision-threads`:

```bash
npm install
npm run dev
```

`npm run dev` first executes the real deterministic winner loop and exports `public/demo-state.json`; Vite then serves the React experience.

## Exit gate

VWS-1 is ready for Cloud Run integration when:

- the graph remains one persistent visual object through the full loop;
- the human YES visibly mutates the graph;
- current-world changes do not erase historical state;
- the reuse traversal visibly stops before the missing edge;
- all semantic status shown in the hero is backend-derived;
- the full interaction can be performed comfortably inside the final demo time budget;
- the slice is visually memorable without relying on unrelated decorative effects.
