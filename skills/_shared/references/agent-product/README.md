# Agent-product baseline

Controls for a product that itself runs agents or causes external effects, taken from the AI Engineering
Handbook 1.0 (chapter numbers in parentheses) and compressed to checklists. The quoted lines are the
handbook's own words. This file is about the product being built, never about the pipeline's own checks.

## When it applies

Read it at `/plan` intake, before mechanism cards and must-not-lose items are written, when the intent says:

- the product runs a model that chooses actions or calls tools (one agent, agent-as-tool, several agents, or a
  model-driven background worker), or
- the product causes an effect outside its own data: payments or refunds, email or other messages, bookings,
  publishing, account changes (permissions, deletion, plan or identity changes), or writes to a system it does
  not own.

When neither holds, it does not apply. When it is unclear, that is an intake question, because the answer
changes the mechanism cards. "Payments, email, bookings, and publication need a business action ledger, not
retries alone" (10).

## The controls

**1. Stable intent and an action ledger with UNKNOWN** (10, 2)
- Create an `intent_id` at the authorized business entry point; keep it through delegation, retries, and
  reconciliation. Scope uniqueness by tenant, operation kind, and intent.
- Store a canonical payload hash; reject reuse of one intent with a different amount, target, or recipient.
- "Identical parameters do not establish one operation; different task IDs do not establish different
  operations." A real repeat purchase gets a new intent.
- States: PREPARED, DISPATCHING, SUCCEEDED, FAILED_FINAL, UNKNOWN, COMPENSATING / COMPENSATED. Record request
  ID, idempotency key, payload hash, approval reference, start time, last reconciliation check, receipt, error
  category. "A boolean success field is insufficient."
- One local transaction validates preconditions, reserves, writes the intent, and writes an outbox event; a
  separate dispatcher sends. "An outbox does not make a database update and external charge atomic."
- Compensation is a new operation with its own intent, not a rollback.

**2. Idempotency and reconciliation before any retry** (10, 14, 28)
- After a timeout, when it is unclear where it failed, "assume the effect may have happened". Query by the
  original key or request ID; check webhooks and external records.
- Retry the original intent only when the provider guarantees it is safe and the key is still retained.
  Otherwise a human reconciliation queue; keep reservations; "do not invent success or failure".
- "A new idempotency key creates a new operation rather than resolving uncertainty."
- Email, browser clicks, and legacy APIs may have no idempotency: retrying UNKNOWN there accepts duplicates,
  and the business chooses that explicitly.
- Retry at the layer that understands the failure, with a deadline, an attempt cap, and backoff. A permission
  denial stops; a schema error is corrected, not resent.

**3. Approval bound to the exact payload, revision, and expiry** (20, 28)
- Show the action, target, recipient, amount and currency, data scope, outbound content, point of
  irreversibility, current revision, and expiry.
- Bind approval to the canonical payload hash, task or plan revision, resource preconditions, policy revision,
  approver, expiry, and consumption rules. Recheck before execution; a changed field needs a new approval.
- Approval is not execution authority: tools still enforce the invariants.
- If the input changes while approval is pending: invalidate, freeze submission, propose again, and "never edit
  historical approval to fit a changed action".

**4. Leases with fencing generations checked at the write** (7, 9)
- A lease has an owner, an expiry, and an increasing generation. A worker that lost its lease stops submitting;
  its output becomes a candidate.
- "Validate fencing and perform the protected mutation in the same atomic boundary." Checking time before
  sending is not enough. Never reset a generation on release or recreation.
- A task's attempt generation is not a resource's fencing generation.
- An external API that ignores fencing: "a lock cannot establish duplicate-free execution"; use control 1.
- "A heartbeat proves that a process can still contact the control plane", not progress.

**5. Revisions and compare-and-swap** (9, 6)
- Return a revision with every authoritative read; update only `WHERE revision = expected`; zero rows is a
  conflict. "Do not retry by overwriting unconditionally": reread and recompute.
- "Row correctness is not system correctness": a cross-row rule (write skew) needs an aggregate lock or
  serializable isolation, and a retry of the whole transaction. No irreversible call inside a retryable
  transaction.
- Prefer narrow domain operations to whole-object replacement.

**6. Task, attempt, and intent identities kept apart** (7)
- `task_id` (logical work), `run_id`, `attempt_id` (one attempt), `intent_id` (one business operation). "A retry
  creates a new attempt but normally retains the original intent."
- "A queue is a wake-up mechanism, not proof of ownership": claim atomically from a durable ledger.
- A late result cannot revive a terminal task, and is checked against the current plan revision.

**7. Budgets reserved atomically** (14, 4)
- "Atomically reserve capacity before an expensive operation, then settle actual usage and release the
  remainder." A prompt saying "$10 remains" lets every child spend it.
- Child creation cannot bypass a parent's limit. Use integer money units.
- Before releasing a lost worker's reservation, check whether its spending is still in flight.
- Degrade by doing less, never by weakening authorization, invariants, deduplication, or approval. "Budget
  exhaustion is not evidence that no issues remain."

**8. Injection defense never replaces tool-side authorization** (19, 15, 12)
- "Authority is an intersection": the user's rights, delegation, workload permission, task scope, and current
  policy. A child gets no more than its parent may delegate.
- Marking untrusted text, fewer tools, output limits, detectors, and a second model reduce risk; "None replaces
  deterministic authorization." Unknown or failed review must not become permission.
- Guard every side-effect path (functions, MCP, browser, shell, downloads, built-in tools). MCP annotations are
  hints; discovering a tool does not authorize it. Check token audience, scope, and expiry.

**9. Result packages and handoff acknowledgement** (11, 20)
- A result returns: question addressed, input versions, artifact references and hashes, verified conclusions,
  unverified assumptions, acceptance items met, receipts, unfinished work, blockers, resource use, next action.
  The recipient never promotes an inference to a fact.
- A handoff is proposed, accepted with a durable acknowledgement and task ID, executed without duplicate
  delegated writes, returned with evidence, and closed by a named publisher. "A prompt saying that work has
  been handed over is not a completed handoff."
- Messages carry an ID, schema version, correlation and causation, and expiry; receipt is deduplicated durably
  and acknowledged only after commit.
- Draft, submitted, accepted by the provider, and received are different states; show only what evidence
  supports.

## From a control to a mechanism card and a must-not-lose item

Each control that applies becomes a mechanism card in `intent.md` (Purpose, Observable guarantee, Rejected
imitation, Discriminating probe), written in plain product language as the template requires, and at least one
must-not-lose item with a `check:`. The gate then owes a row for each: `gate_report.py` never computes
ACCEPT-READY while a must-not-lose item, or a card the milestone names, has no intent-diff row. The check
asserts "the number of external business effects and the remaining local balance, not merely a function's
return value" (10).

Example card (control 2):

    ### One refund per request
    Purpose: a customer who asks once is refunded once, however the request is handled.
    Observable guarantee: the provider shows one refund and the refunded total never exceeds what was paid,
      even when a reply is lost; the customer sees "checking with the payment provider", never "failed".
    Rejected imitation: retry on timeout. It refunds twice when the first request went through.
    Discriminating probe: the provider accepts the request and its reply is dropped. The real mechanism ends
      with one refund, reconciled to success; the imitation ends with two.

Its must-not-lose item: `- L-0n A refund request never produces a second refund · check: the lost-reply probe
in the provider's test mode counts provider refunds (1) and the order's refunded total`.

| Control | Rejected imitation | Probe for the check |
|---|---|---|
| 1 Intent ledger | a sent flag, or deduplicating by identical arguments | two entry points request one refund at once: one effect; a new intent for a real repeat still runs |
| 2 Reconcile first | retry on timeout; a fresh key per retry | success with the reply lost: one effect, state ends reconciled |
| 3 Bound approval | a stored "approved: yes" | approve 10, submit 100; change the plan revision: both refused |
| 4 Fencing | checking the lease locally before writing | A loses its lease, B writes, A writes late: storage refuses A |
| 5 Revisions | last writer wins, whole-object replace | two agents change different items of one record: neither change lost |
| 6 Identities | deduplicating by task ID | a late result after cancel or replan: refused |
| 7 Reservations | telling each child what remains | twenty children reserve at once: total never exceeds the budget |
| 8 Tool-side authority | a prompt rule, or a filter that allows unless it says VIOLATION | page text asks for a transfer the user may not make: the tool refuses; empty filter output: denied |
| 9 Result package | the child says "done" | a generated draft never shows as sent; each item carries its own evidence |

## Reference code

`reference/coordination.py` shows each mechanism; `reference/test_coordination.py` holds its 36 tests. Origin,
hashes, and limits are in `reference/SOURCE.md`.

| Control | Where | Tests |
|---|---|---|
| 1, 2 | `Store.prepare_action`, `Store.begin_dispatch` (UNKNOWN before sending), `Store.record_success`, `digest` | 16 to 19, 23, 31, 32, 35 |
| 3 | `Store.begin_dispatch` (payload hash, expiry, plan) | 20 to 22 |
| 4 | `Store.claim`, `renew`, `acquire_resource`, `write_resource`, `release_resource` | 1 to 4, 9, 10, 12, 13 |
| 5 | `Store.write_resource` (expected revision, outbox in one transaction) | 11, 14, 15 |
| 6 | `Store.complete` (expected plan), `cancel`, `replan` | 2, 5 to 7 |
| 7 | `Store.reserve`, `Store.settle` | 26 to 29, 36 |
| 9 (receipt) | `Store.consume_increment` (inbox) | 25 |

It is a single-host teaching program: caller identity, approvals, and plan are trusted inputs; `inspect` is
never an agent tool; `complete` assumes acceptance was checked elsewhere. A product ports the behavior tests
to its own storage and provider sandboxes (29): "Do not remove failing tests to accommodate the adapter."

Status in this repository: `install.py` installs this folder with the other shared references; no skill
points here yet.
