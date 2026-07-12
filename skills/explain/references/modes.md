# Explanation Modes Reference

Loaded by `/explain`. Four registers for the SAME build, each re-derived at a different altitude
(Diátaxis: commit to one register, never blur). Sources: Diátaxis, Google Technical Writing,
Amazon working-backwards / PR-FAQ, YC/NFX investor-update conventions, NN/g + plain-language +
Keep-a-Changelog.

The core rule: **do not summarize-then-reskin. Re-derive from the change through three transforms
— altitude, lead-with, omit-list.**

---

## MODE: engineer
**Cares about:** is the design sound and not over-engineered; does it do what was intended; what
contract/breaking surface do I now depend on; what could it break; is it actually verified; what's
left. **Altitude:** ground level (the machinery). Jargon is expected. **Lead with:** what changed
(imperative). **Omit:** business framing, metrics, benefit-selling.

Template:
1. **Summary** — one imperative line ("If applied, this will …").
2. **What changed** — Added / Changed / Removed / Fixed / Security, terse bullets.
3. **Why** — problem + motivation, 2-4 sentences.
4. **Design decisions & tradeoffs** — only if a real choice existed: context → decision →
   alternatives rejected → consequences (including the negative ones).
5. **Interfaces / contract changes** — signatures, APIs, schemas, config.
6. **Breaking changes** — only if present, loud.
7. **Risks / edge cases** — concurrency, blast radius.
8. **Verification** — what was run, the evidence, what it covers.
9. **Follow-ups** — honest about rough edges.

Lint: explains what and why, not line-by-line how; honest about residual rough edges.

## MODE: founder
**Cares about:** does it serve the customer and the problem; the user benefit (outcome not
output); scope/tradeoffs; risk; what's next and is it worth shipping. **Altitude:** the customer
outcome, not the engineering artifact. **Lead with:** the benefit headline + the decision needed.
**Omit:** code internals, architecture, vanity metrics. Plain narrative prose, not bullets-as-
thinking.

Template:
1. **Headline** — `[product] now lets [user] [benefit]`.
2. **In one paragraph** — who it's for, what they can now do, why it matters.
3. **The problem** — the customer pain, plain language, capped at the top 3-4.
4. **What we built & how it solves it** — overview, then map to each problem.
5. **What the user gets** — the outcome.
6. **Scope & tradeoffs** — what's in, what was cut, what it cost.
7. **Risk / biggest unknown.**
8. **What's next / decision needed** — recommended priority + the decision you're asking for.
9. **How success is measured.**

Lint: zero code internals; leads with benefit + decision; narrative prose.

## MODE: investor
**Cares about:** trajectory and credibility — growth, retention, burn/runway, execution.
"Investors invest in lines, not dots." **Altitude:** highest business altitude. **Lead with:**
metrics + TL;DR; surface the ask near the top. **Omit:** architecture, tickets, refactors, jargon.
A shipped feature counts only reframed as a metric movement or unblocked revenue.

Template:
```
TL;DR (2-3 sentences): state of the business + headline metric + the single biggest ask.
1. KEY METRICS — revenue/MRR (+MoM %, trailing-3-mo avg) · cash · burn · runway · core funnel
   metric (+growth) · retention/churn.
2. ASKS (near top) — 1 to 4, specific, forwardable (intros to a named profile, a hire, advice).
3. HIGHLIGHTS — each shipped thing tied to a metric or deal.
4. LOWLIGHTS — what missed/broke + what you're doing about it (never an all-good update).
5. LOOKING AHEAD — short qualitative narrative, last.
```
Lint: every shipped item reframed as business signal; at least one lowlight; an ask present;
brevity (they read the whole thing). If real metrics are unavailable, say so, do not invent them.

## MODE: user
**Cares about:** "what can I now do, and what's in it for me?" Nothing else. **Altitude:** highest
plain-language altitude, zero jargon. **Lead with:** the benefit, conclusion-first (79% scan, not
read). Show don't tell. **Omit:** feature names as headlines, architecture, every technical term.

Template (benefit-led changelog, ≤3 buckets):
```
One-line summary: the single most useful new thing, as a user capability.
✨ New — what you can now do
   • Benefit headline (≤8 words): "You can now [do X]"
     one plain line (~20 words, active voice, "you").  (optional) Try it → / GIF
⬆️ Improved — before→after in user terms.
🐛 Fixed — what you experienced before → what happens now (not the internal cause).
```
Lint: benefit-led headline (not a feature name); second person; no jargon (backend, token,
latency, schema, refactor); short sentences.

---

## The 4-way worked example (same change, four altitudes)
Change: *added passwordless login via email magic-link, replacing the password form.*
- **engineer:** "Replace password login with email magic-link. Added `POST /auth/magic-link` +
  `GET /auth/verify`, `magic_tokens` table (hashed, 15-min TTL, single-use). Removed password
  path. Risk: login now depends on email deliverability. Tests: issue/expiry/replay/rate-limit, all green."
- **founder:** "Login no longer needs a password — users enter their email and click a link.
  Removes our #1 support ticket (password resets) and a sign-in drop-off point. Tradeoff: sign-in
  now depends on email arriving promptly. Decision for you: email-only, or add a fallback?"
- **investor:** "Shipped passwordless login → login-success 86%→94%, password-reset tickets −40%,
  ~3 founder hrs/week freed. Lowlight: email is now a single point of failure for sign-in; adding
  a backup sending domain this week. Ask: intro to anyone who's run high-volume transactional email."
- **user:** "✨ Sign in without a password — enter your email, click the link we send, you're in.
  Nothing to remember. Try it →"

## Auto-pick + register-switch
Pick by the surface and the reader's decision: code/commit → engineer; "What's New" → user; an
email to the cap table → investor; a product-review memo → founder. If ambiguous, ask once. Then
apply the three transforms (altitude / lead-with / omit) and the per-mode lint. Never default to
engineer silently.
