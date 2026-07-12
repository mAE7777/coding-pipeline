# Interrogation Reference — turning any input into precise, confirmed intent

Loaded by `/plan` at Stage 2. This is the machinery for asking FEW but RIGHT questions, grounding
every rule in an example, and never assuming anything material. Sources: spec-kit, BMAD,
Mavin (EARS), North/Cucumber (Gherkin), Wynne/Adzic (Example Mapping), Fitzpatrick (Mom Test),
OWASP/WCAG/UI-Stack/8-Fallacies/ISO-25010.

## The four-move loop (the economy)
1. **Capture the real why first** (Mom Test). 2. **Ground every candidate rule in a concrete
example** (the act of grounding is the gap detector). 3. **Triage gaps into questions, never
guess** (RED-card). 4. **Confirm by playing back an example + an EARS statement**, not a
paraphrase. You ask few questions because examples + project-type filtering do the work; you ask
the right ones because the taxonomies below surface what actually matters.

---

## A. Mom Test posture (get truthful intent, don't lead)
Ask about their life and the past, not your idea and the future. Never ask the user to bless your
interpretation.

| Avoid (fishes for a yes) | Ask instead |
|---|---|
| "So you want X, Y, Z, right?" | "Walk me through how you do this today." |
| "Would it be useful if it did X?" | "Last time you hit this, what did you do? Where did it break?" |
| "Do you think this is a good idea?" | "Why do you bother? What are you trying to get done?" |
| "It should probably handle Y too" (fluff) | "When did you last need Y? What happened?" |

Enthusiastic agreement with no specifics is a zombie answer. Keep digging until you have concrete
behavior.

## B. The 11-category ambiguity scan (spec-kit)
Mark each Clear / Partial / Missing. Question only the Partial/Missing ones that materially matter.
1. **Functional scope & behavior** — core goals & success criteria; explicit out-of-scope; roles/personas.
2. **Domain & data model** — entities, attributes, relationships; identity/uniqueness; lifecycle/state; volume/scale.
3. **Interaction & UX flow** — critical journeys; error/empty/loading states; accessibility/localization.
4. **Non-functional** — performance targets; scalability; reliability/availability; observability; security/privacy; compliance.
5. **Integration & external deps** — services/APIs and failure modes; import/export formats; protocol/versioning.
6. **Edge cases & failure handling** — negative scenarios; rate limiting; conflict resolution.
7. **Constraints & tradeoffs** — technical constraints; explicit tradeoffs / rejected alternatives.
8. **Terminology** — canonical glossary terms; avoided synonyms.
9. **Completion signals** — acceptance-criteria testability; measurable definition of done.
10. **Placeholders** — TODO/unresolved decisions; vague adjectives ("robust", "intuitive") lacking quantification.
11. **Persona/audience** — who uses it, at what skill level, on what surface.

## C. The 12-dimension hidden-details checklist (filter to the project type)
A CLI skips i18n/accessibility/concurrency; a multi-user web app needs most. **Highest-yield (ask
first, almost always missed, almost always cause incidents): B states, E concurrency, K
integration failures, D data lifecycle.**

- **A. Auth/permissions** — who's allowed; authn vs authz; least-privilege default; can a user act on another's resource by changing an id (IDOR); admin/impersonation paths.
- **B. States** — empty (first run / all deleted / no results), loading (spinner/skeleton/timeout), error (message, retry, unsaved-work preserved?), partial, ideal-with-max-content.
- **C. Validation** — valid ranges/formats; required vs optional; client/server/both (server is truth); behavior on invalid; boundary inputs (empty, zero, negative, max length, unicode/emoji, whitespace, duplicates).
- **D. Data lifecycle & retention** — who owns it; how long kept; soft vs hard delete; audit trail; which fields are PII, encryption, who can see them.
- **E. Concurrency & conflicts** — two edits at once (last-write-wins / merge / prompt); optimistic (version/etag) vs pessimistic; idempotency (retry after timeout → duplicate charge?); races in counters/balances/inventory/uniqueness.
- **F. Performance & scale** — expected & peak load; acceptable p95/p99; largest input/list/file; pagination; expensive ops (N+1); caching; what breaks first at 10x.
- **G. Security** — trust boundary; injection/SSRF/deserialization; secrets out of code/logs; secure defaults (CORS, buckets, debug endpoints, default creds); deps scanned; rate-limit/lockout on auth.
- **H. Privacy & compliance** — regimes (GDPR/CCPA/HIPAA/SOC2/PCI); export & right-to-erasure (does delete satisfy it); consent/legal basis; retention limit; residency; sub-processors.
- **I. Accessibility (WCAG POUR)** — text alternatives, captions, AA contrast; keyboard-only, visible/ordered focus; clear labels/errors; screen-reader/semantics.
- **J. i18n/l10n** — languages/locales; no hardcoded strings, text-expansion room; date/time/tz/number/currency per locale; RTL/non-Latin; names/addresses/phone across regions.
- **K. Integrations & failure modes (8 Fallacies)** — external service slow/down/erroring: timeout, retry-with-backoff, circuit breaker; idempotent/safe to retry; graceful degradation; rate limits, quotas, token expiry, version changes. Run the 8-fallacies pass on every remote call.
- **L. Observability (3 pillars)** — what's logged (correlation ids, no secrets/PII); what metrics signal health + alert thresholds; can you trace one request end-to-end; will you know it's broken before the user tells you.

## D. Example Mapping + the RED-card rule (the gap detector)
For each rule you think you heard, try to write ONE concrete example with real data.
- Can write it → intent confirmed for that rule. Record the example (it becomes the grounding
  example in the anchor and a qa acceptance test).
- Can't write it → a gap. **Do not debate or assume a default.** Capture it as a question
  ("turn an unknown unknown into a known unknown") and ask it. The pile of questions IS the
  "details that might matter" list.
- A rule that needs many examples is probably several rules (split). A story drowning in
  questions is not ready (keep asking).

## E. The structured-question format (recommend first, show progress)
Never dump an open question; every question leads with a recommendation and its reasoning.
**Harness with a native question tool** (Claude Code: `AskUserQuestion`): use it. Recommended
option first, labeled "(Recommended)"; a one-line description per option; batch up to 4 questions
in ONE call only when they are independent (no answer would change another question); "Other" is
provided automatically.
**Harness without one** (Codex CLI and similar): markdown fallback, one question per message:
```
**Recommended:** Option B — <1-2 sentence reasoning grounded in best practice / the stated goal>.

| Option | Description |
|--------|-------------|
| A | <option A> |
| B | <option B> |
| C | <option C> |
| Other | give your own (<=5 words) |

Reply with a letter, say "recommended", or give your own.
```
For short-answer questions, lead with `**Suggested:** <answer> — <reasoning>`.
**Show progress every round**: say how many material gaps remain and where ("2 material gaps
left: data lifecycle, auth"). Hiding the queue makes interrogation feel endless; the count costs
nothing. Stop when all material ambiguities are resolved or the user signals done. There is NO
fixed question cap for material gaps; the filtering and grounding are what keep the count low.

## F. What may be defaulted vs what must be asked
Default-and-record-as-`[ASSUMPTION]` (safe + obvious, low impact): error-message wording,
standard log levels, conventional folder layout, obvious library choices with no trade-off.
**Always ask (material, could change the result):** anything in the highest-yield clusters (B/E/K/
D), scope boundaries, auth model, money/irreversible actions, data you store about people,
anything where two reasonable interpretations diverge. When unsure whether something is material,
treat it as material and ask. Conservatism is the default.

## G. EARS — write the confirmed intent as testable statements
Each definition-of-done behavior is written in EARS so it is unambiguous and testable.
```
UBIQUITOUS:   The <system> shall <response>
EVENT-DRIVEN: When <trigger>, the <system> shall <response>
STATE-DRIVEN: While <state>, the <system> shall <response>
OPTIONAL:     Where <feature>, the <system> shall <response>
UNWANTED:     If <condition>, then the <system> shall <response>
COMPLEX:      While <state>, when <trigger>, the <system> shall <response>
```
Examples: "When the user submits an empty email, then the system shall show 'enter your email' and
not send a link." / "While no items exist, the system shall show the empty state with a 'create'
action." Validity (a built-in linter): zero-or-many preconditions, zero-or-one trigger, one system
name, one-or-many responses. `When` = event, `While`/`During` = state, `Where` = optional feature,
`If/Then` = unwanted behavior (its own syntax because unwanted paths are the #1 source of
omissions), `shall` = mandatory & testable. Pair each EARS statement with one Gherkin-style
grounding example (declarative: describe what, not which button) so the user confirms a concrete
case, not prose.

## H. Assumptions Index discipline
Every inference, default, and unconfirmed reading gets an `[ASSUMPTION]` line collected into one
Assumptions Index in the anchor. At the CONFIRM gate, the user signs off the whole index. An
assumption silently baked into prose instead of surfaced here is a process violation.

## I. Confirm, don't fish
At the CONFIRM gate, restate intent as the EARS statements + their grounding examples + the
Assumptions Index, and ask the user to confirm or correct each. A concrete example and a testable
statement can be precisely confirmed or corrected; a vague paraphrase invites a polite,
uninformative nod. Gate the build behind an INVEST / Definition-of-Ready check.
