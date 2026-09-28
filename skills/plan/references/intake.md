# Intake: turning any input into precise intent the owner can lock

Loaded by `/plan` during intake. The craft of asking few but right questions, grounding every rule in an
example, and assuming nothing material. Sources: spec-kit, BMAD, Wynne and Adzic (Example Mapping),
Fitzpatrick (The Mom Test), OWASP, WCAG, the eight fallacies of distributed computing, ISO 25010.

## The loop
1. Capture the real why first. 2. Ground every candidate rule in a concrete example; the act of grounding
is the gap detector. 3. Turn each gap into a question, never a guess. 4. Confirm by playing back the
example and the statement, not a paraphrase. Few questions, because examples and project-type filtering
do the work; the right ones, because the lists below surface what matters.

## A. Ask about their life, not your idea
| Avoid (fishes for a yes) | Ask instead |
|---|---|
| "So you want X, Y, Z, right?" | "Walk me through how you do this today." |
| "Would it be useful if it did X?" | "Last time you hit this, what did you do? Where did it break?" |
| "Do you think this is a good idea?" | "Why do you bother? What are you trying to get done?" |
| "It should probably handle Y too" | "When did you last need Y? What happened?" |
Enthusiasm with no specifics is not an answer; keep going until you have concrete behavior.

## B. The ambiguity scan
Mark each Clear, Partial, or Missing; ask only about the Partial or Missing ones that matter.
1. Scope and behavior: goals, success, explicit out-of-scope, roles.
2. Domain and data: entities, identity, lifecycle, volume.
3. Interaction: the critical journeys; error, empty, and loading states; accessibility; languages.
4. Non-functional: performance, reliability, observability, security, privacy, compliance.
5. Integrations: services and their failure modes, formats, versions.
6. Edge cases: negative paths, rate limits, conflicts.
7. Constraints and trade-offs, with the rejected alternatives.
8. Terms: one word per concept, synonyms to avoid.
9. Completion: each done example testable, a measurable definition of done.
10. Vague words ("robust", "fast", "intuitive") that need a number or an example.
11. Who: skill level, surface, situation.

## C. The details that cause incidents (filter to the project type)
A CLI skips languages and concurrency; a multi-user web app needs most. Ask first about states,
concurrency, integration failure, and data lifecycle: they are almost always missed.
- Authorization: who may do what; can changing an ID reach someone else's data.
- States: empty (first run, all deleted, no results), loading, error (message, retry, unsaved work kept),
  partial, and the fullest realistic content.
- Validation: ranges, formats, required fields; server-side as the truth; boundary inputs (empty, zero,
  negative, maximum length, emoji, whitespace, duplicates).
- Data lifecycle: ownership, retention, soft or hard delete, audit, which fields are personal and who sees
  them.
- Concurrency: two edits at once (last write wins, merge, or ask); retries and idempotency; races in
  counters, balances, stock, uniqueness.
- Performance: normal and peak load, acceptable latency, largest input, what breaks first at ten times.
- Security: trust boundaries, injection, secrets out of code and logs, safe defaults, rate limits on auth.
- Privacy: regimes that apply, export and erasure, consent, residency.
- Accessibility: text alternatives, contrast, keyboard use, focus order, labels, screen readers.
- Languages: which ones, no hard-coded strings, dates, numbers, currency, names across regions.
- Integrations: timeouts, retries with backoff, idempotency, degradation that is designed and visible,
  quotas, token expiry, version changes.
- Observability: what is logged (no secrets), which signals say it is healthy, knowing before a user says.

## D. Example mapping: the gap detector
For each rule you think you heard, write one concrete example with real data.
- You can write it: the rule is confirmed; the example becomes a done example.
- You cannot: it is a gap. Do not debate or default; ask.
- A rule that needs many examples is several rules. A goal drowning in questions is not ready.

## E. How to ask
Lead every question with a recommendation and its reason. With a question tool (Claude Code:
AskUserQuestion) put the recommended option first, labeled "(Recommended)", one line per option; batch up
to four questions only when no answer changes another. Without one (Codex and similar), one question per
message:

    **Recommended:** B, because <one or two sentences from the goal or best practice>.
    | Option | Description |
    |---|---|
    | A | ... |
    | B | ... |
    | Other | your own words |

Show the count every round ("two material gaps left: data lifecycle, authorization"). Stop when every
material gap is closed or the owner says done; there is no fixed cap for material gaps.

## F. Default or ask
Default and record as an assumption (A-nn) when safe, obvious, and low impact: message wording, log
levels, conventional layout, a library choice with no trade-off. Always ask about: states, concurrency,
integration failure, data lifecycle, scope boundaries, the authorization model, money or irreversible
actions, data about people, and anything two careful readers would build differently. When unsure
whether it is material, it is.

## G. Writing done examples
One testable statement plus one concrete example with real data:
`- I-D3 When a second phone deletes an item, the first shows it gone within five seconds. Example: B deletes
"milk" → A's list no longer shows "milk"`. Unwanted paths get their own examples ("If the network drops,
..."), because they are the most common omission. Where precision helps, the conditional forms (when,
while, if, where) of structured requirement writing are fine, but the example is what the owner confirms.

## H. Assumptions
Every inference, default, and unconfirmed reading is an A-nn line in `intent.md`; the owner signs the list
at the lock. An assumption buried in prose instead of listed there is a defect.

## I. Confirm, do not fish
At the lock, play back the done examples with their examples, the mechanism cards, the must-not-lose items,
and the assumptions, and ask the owner to confirm or correct each. A concrete case can be corrected; a vague
paraphrase invites a polite nod.
