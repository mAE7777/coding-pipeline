---
name: integrate
description: "Final whole-product check before shipping: confirm every slice is wired together, the full user journey works end-to-end, no load-bearing behavior is a stub, and the whole build still matches the frozen intent. Use this skill when the user says /integrate, 'wire it all together', 'does the whole thing work', 'final check before deploy', or after the last slice. With vertical slices integration is continuous, so this is a thin final pass, not a big rebuild."
argument-hint: (no arguments)
---

# integrate — Final Assembly Check (thin)

> EXECUTABLE WORKFLOW. Vertical slices integrate as you go, so this is a light final pass: prove
> the WHOLE thing works and still matches intent, and catch anything left as a stub.

## Workflow

### Stage 1 — Whole-journey trace
From the real entry point, exercise the complete user journey end-to-end (not slice by slice).
Show evidence for the load-bearing behavior across the full product.

### Stage 2 — Stub / orphan sweep
Find anything left disconnected: stubs, placeholder or demo data standing in for real behavior,
slices that work alone but aren't reachable from the entry point, TODOs on a load-bearing path.
List them.

### Stage 3 — Whole-intent fidelity + converge + analyze
Run `/loyal check` against the FULL `intent-anchor.md` (the whole definition-of-done, not just the
last slice), to catch cross-slice drift the per-slice passes missed. Run the whole-product
**converge** check: classify every EARS criterion in the anchor against the assembled product as
`missing / partial / contradicts / unrequested`. Run a quick **analyze** consistency pass across
`intent-anchor.md` / `contracts.md` / `slices.md` (terminology drift, an entity in contracts
absent from the intent, a slice with no anchor criterion, a criterion with no slice).

### Stage 4 — Resolve, don't defer
Fix what's broken (or route to `/dev` or `/fix`). Nothing load-bearing ships as a stub. Re-verify
with evidence.

### Stage 5 — Full Definition of Done
The product is shippable only when every EARS criterion HOLDS with evidence AND the global DoD
holds across the whole product: independent review, tests passing, build/CI green, security gate
clean, accessibility/performance where applicable, docs/changelog updated, no known critical
defect. Report it as a checklist; an unmet item blocks `/deploy`.

### Success: the full journey works with evidence, no load-bearing stub, whole-intent fidelity holds, converge clean, DoD met.
### Failure: a load-bearing behavior is a stub, the journey breaks, a converge gap is open, or a DoD item is unmet. Resolve before `/deploy`.

## Ecosystem
- **Reads**: `slices.md`, `intent-anchor.md`, the entry point.
- **Runs**: `/loyal` (full intent) and `/qa` (full journey) as needed.
- **Hands to**: `/deploy`.
