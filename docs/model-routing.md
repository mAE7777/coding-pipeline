# Model routing: candidates and how a switch is measured

This page lives in the repository only; `install.py` never installs it and no step reads it at run time. It
lists, for every route in `skills/_shared/models.json`, today's setting and the candidate from plan section
7.2 (`docs/plan-craft-economy.md`), what must exist before the candidate can be tested, and the exact commands
of the five steps in plan 7.3. The commands spend real money and need the owner's machine (Codex, the macOS
sandbox, Playwright), so they run there, with the owner's approval of the spend. Nothing here is promoted
yet: every route runs today's setting.

## Rules that hold for every switch

- **Fable is never allowed.** `models.py` rejects any model ID that contains fable or mythos, in the table, the
  personal override, a shadow, or a `--model` flag, and `tests/static_checks.py` fails a publishable file that
  names one. Only full IDs from `allowed_models` are used (`claude-opus-5-5`, `claude-sonnet-5-5`,
  `claude-haiku-5-5`), never an alias that can move.
- **Only isolated runs and forked skills switch,** never a session midway: prompt caches are per model, so a
  mid-session switch re-sends the whole conversation uncached (plan 7.1 and 7.4).
- **Sonnet or Haiku only where an independent check stands downstream** (the judge opens every demo capture;
  the fidelity audit re-reads every extraction; the builder reads the lines an explorer cites). Effort before
  model: try `high` on Opus before trying Sonnet.
- **The retry escalates.** `gate_run.py`'s one retry of a checker that ended ERROR or INCONCLUSIVE runs on
  `escalate` (claude-opus-5-5 at xhigh). In a fixture run an escalated run counts as a failure, so the retry
  never rescues the candidate's score.
- **One route at a time, safest first** (plan 9, phase 3): the explorer and a forked `/scout map`; the
  claim-verifier; the re-read's effort; the understanding check's effort; a forked `/explain`; the judge's
  effort, with the capture check; the demo; extraction. Measure on the prompts that will ship: both sides of
  a comparison carry the same agent texts.
- **Promotion** is an `/evolve` change whose product change is the route's entry in `models.json` (and, for a
  builder-side route, the skill text that spawns it). A checker on another model can decide differently, so
  it is an owner kind (`rule-change`): `evolve.py record` takes it only with the owner's words proven in their
  transcript. A shadow summary saying "ready to promote" is evidence for that change, never the change.

## The table

Today, every checker route is `claude-opus-5-5` at effort `xhigh`. The table names the model instead of
`"default"`, so a change to Claude Code's default model, or to your own `model` setting, never changes what a
checker runs on. The code-verifier's review runs on Codex when Codex can serve (`gate_run.py --family auto`), on
the table's `codex` entry (`gpt-6-astra` at `xhigh`), which the personal override can also change. Builder-side
routes are `"model": "session"`: the session's model and effort. `python3 ~/.claude/skills/_shared/scripts/models.py list` shows what each route
resolves to on this machine, the personal override and any shadow included.

| Route | Candidate | Why |
|---|---|---|
| builder session; `/handoff`, `/inbox`, `/next` | no change | load-bearing, and a midway switch drops the cache |
| `code-verifier.review` | claude-opus-5-5 `xhigh` (Claude family only) | the headline failure lives here; pins today's served model by full ID |
| `code-verifier.reverify` | claude-opus-5-5 `high` | named findings and a small delta |
| `code-verifier.demo` | claude-sonnet-5-5 `high` | runs listed steps and saves captures; the judge opens every capture |
| `loyal-evaluator` | no change; optional experiment at claude-opus-5-5 `high` | the subtlest judgment in the gate |
| `gate-judge` | claude-opus-5-5 `high`, tested together with the demo switch | works only from evidence it is handed |
| `cold-reader.documents` | no change | finding ambiguity is the job |
| `cold-reader.reread` | claude-opus-5-5 `high` | settles earlier findings and reads changed text only |
| `cold-reader.understanding` | claude-opus-5-5 `high` | a law-3 joint, so it stays on Opus; the input is small |
| `cold-reader.extract` | claude-sonnet-5-5 `high` | high volume; quotes checked by script; every portion audited on Opus |
| `cold-reader.fidelity` | no change | the safety net for extraction |
| `cold-reader.refidelity` | claude-opus-5-5 `high` | re-audits what the first audit flagged |
| `claim-verifier` | claude-sonnet-5-5 `high` | fetch, find the quote, compare |
| `change-reviewer` | no change | rare; decides what the pipeline becomes |
| `explorer` | claude-sonnet-5-5 `medium` | returns pointers; the builder reads the cited lines |
| `scout-map` | a forked skill on claude-sonnet-5-5 `medium` | self-contained read-and-report work, kept out of the long session |
| `explain` | a forked skill on claude-sonnet-5-5 `high` | reads the record and evidence and writes for an audience |
| `delegate` | claude-sonnet-5-5 `high`, only when the owner asks | fully specified work; the builder reviews the diff |
| `architect-runner` | fixed by design: one claude-opus-5-5 `xhigh` and one claude-sonnet-5-5 `high` runner | the arena on one-way mechanism cards |
| `probe` | not a role to promote | fixture probes of a pipeline text run here |

## What each candidate needs before it is tested

Fixture names are keys of `FIXTURES` in `tests/fixture_expectations.py`; each spec's `"serves"` field names
the route it measures. Items per run counts the planted defects an expectation checks one by one (its
verdict check aside, though a wrong verdict also counts as a problem in the pooled rule). Plan 7.3 asks for at
least 30 item-trials per side; the column gives the count at `--runs 5`.

| Route | Planted fixtures (items per run) | Item-trials at `--runs 5` | Clean controls | Still missing |
|---|---|---|---|---|
| `code-verifier.review` | code-verifier-planted (4), code-verifier-review-structure-planted (3), code-verifier-review-outside-excerpt (1) | 40, with the prefix list `code-verifier-review,code-verifier-planted,code-verifier-clean` (the new prefix alone gives 20) | code-verifier-clean, code-verifier-review-structure-clean | outside-excerpt depends on DIFF_BUDGET and the pack's priority order; its pack test fails if either changes |
| `code-verifier.reverify` | code-verifier-reverify-refix-fails (3), code-verifier-reverify-refix-breaks-other (4) | 35 | code-verifier-reverify-refix-works | |
| `code-verifier.demo` | code-verifier-demo-planted (2), code-verifier-demo-web-planted (2), code-verifier-demo-silent-step (2) | 30 | code-verifier-demo-clean, code-verifier-demo-web-clean | none; the web pair needs Playwright (below) |
| `gate-judge` | gate-judge-planted (3), gate-judge-story-demo (2), gate-judge-story-review (2) | 35 | gate-judge-clean | none: the capture-read check exists (`--require-read 'captures/*'`) |
| `loyal-evaluator` | loyal-evaluator-drift (3) | 15 | loyal-evaluator-true (escape-attempt is kind other) | two subtle-drift fixtures, only if the experiment runs |
| `cold-reader.documents` | cold-reader-ambiguous (2) | 10 | cold-reader-clear | no candidate |
| `cold-reader.reread` | cold-reader-reread-partial (4) | 20: short; `--runs 8` gives 32, or add a second planted re-read fixture | cold-reader-reread-clean | |
| `cold-reader.understanding` | cold-reader-understanding-planted (3), -shift-narrowed (1), -shift-mechanism (1), -shift-weakened (1) | 30 | cold-reader-understanding-clean, cold-reader-understanding-shift-clean | |
| `cold-reader.extract` | cold-reader-extract-planted (9) | 45 | cold-reader-extract-clean | |
| `cold-reader.fidelity` | cold-reader-fidelity-planted (4) | 20 | cold-reader-fidelity-clean | no candidate |
| `cold-reader.refidelity` | none: the fidelity fixtures render without `--previous`, so they serve `cold-reader.fidelity` | 0 | none | a planted and a clean re-audit fixture |
| `claim-verifier` | claim-verifier (3, live web), claim-verifier-misquote (5, saved sources) | 40 | claim-verifier-clean (saved sources) | real /scout runs fetch from the web (an empty `--dir auto`), so weigh the live-web fixture's result on its own before promoting; the saved-source fixtures measure quote comparison, not fetching |
| `change-reviewer` | change-reviewer-planted (3) | 15 | change-reviewer-clean | no candidate |
| `explorer`, `scout-map` | probe-explorer-recall (8) | 40 | none (a probe) | the forked `/scout map` skill itself |
| `explain` | probe-explain-grounding (4) | 20: short; `--runs 8` gives 32 | none (a probe) | the forked `/explain` skill itself |
| `delegate` | none | 0 | none | a rename scenario (plan 7.2) |

The web demo fixtures (code-verifier-demo-web-planted and -clean) need Playwright for python3 on the machine
(`pip install playwright; python3 -m playwright install chromium`). Without it each of their runs is recorded
as missed, without calling a model, so a demo comparison on such a machine fails instead of passing on the
command-line fixtures alone.

Fixture runs (`tests/agent_fixtures.py`) take each route's model and effort from `models.json` unless `--model`
or `--effort` is given, and never run a shadow. A direct run also reads the personal override's routes; the
benches of `evolve.py` ignore it (`PIPELINE_MODELS_IGNORE_OVERRIDE=1`), so set that variable for a direct
comparison too.

## How a switch is tested: the five steps of plan 7.3

Run from the repository checkout that `install.py` recorded (or set `$PIPELINE_REPO`), on the `/evolve`
branch of the change (`evolve/chg-<nnnn>`), whose product change is the route's entry in `models.json`.
`<base>` is the branch's base commit, `<branch>` the branch, `<prefix>` the fixture prefix of the route
(comma-separated prefixes are allowed): `code-verifier-demo`, `gate-judge`, `cold-reader-understanding`,
`cold-reader-reread`, `cold-reader-extract`, `claim-verifier`, `code-verifier-planted,code-verifier-clean`.

**1. Plumbing.** The table resolves, the runner passes the flags, and nothing names a forbidden model:

```
python3 tests/test_models.py
python3 skills/_shared/scripts/models.py check
python3 skills/_shared/scripts/models.py resolve <route>
```

**2. Pooled fixture comparison.** Both sides measured alike, five runs per fixture, with the branch's `tests/`
as the instrument on both sides:

```
python3 skills/_shared/scripts/evolve.py bench <base> --suites "repro:route:fixtures:<prefix>" --runs 5 --instrument <branch>
python3 skills/_shared/scripts/evolve.py bench <branch> --suites "repro:route:fixtures:<prefix>" --runs 5
python3 skills/_shared/scripts/evolve.py compare <base> <branch> --suites "repro:route:fixtures:<prefix>"
```

The reproduction holds when, over the fixtures the prefix matches, the head's problems summed over every run
of every planted fixture are no more than the base's, every clean fixture passes every run at head, the cost
per run at head is at most 0.8 of the base's, and at least one planted and one clean fixture match. A run that
gave no verdict of its own (no summary, no verdict block, or escalated) missed everything. compare answers
INCOMPARABLE, and judges nothing, when a suite was measured on one side only, when no pair of measurements
shares an environment (the served models are left out of the match because the diff touches `models.json`;
the output says "model routing changed" with each route before and after), when the sides ran a different
number of runs, when a side's measurements hold no raw usage (`bench --again` on both sides), or when a
fixture has no kind or a run no problem count. Under `--runs 5`, a route short of 30 item-trials (above) is
benched with `--runs 8` on both sides instead.

The `code-verifier.review` candidate pins by its full ID the model the default serves today (each summary's
`served_model` shows it), so it is not cheaper and the route rule's cost cut cannot hold. It is measured as an
ordinary suite, `fixtures:code-verifier-planted,code-verifier-clean` (WORSE when a fixture passes a smaller
share of its runs or costs a quarter more), and made as a change the owner orders directly.

**3. Cost.** Step 2 already requires 20 percent less per run over the route's fixtures. For each fixture's own
cost, or for a change made to spend less that is not a routing change, use `repro:cost:fixtures:<prefix>`
(each fixture at least a fifth cheaper per run and passing at least as often); it is a separate suite, so its
fixtures run again. For real rounds, per milestone, round, and checker role, in units and dollars:

```
python3 ~/.claude/skills/_shared/scripts/spend.py report <project> --milestone M<k>
```

**4. Shadow on real work** (checker routes only). In `~/.claude/.pipeline-models.json`, beside any `routes`:

```json
{"shadow": {"<route>": {"model": "claude-sonnet-5-5", "effort": "high"}}}
```

`python3 ~/.claude/skills/_shared/scripts/models.py check` validates it. Every run of that route then runs the
candidate after the main run, on the same pack, into `<evidence>/shadow/`; only the main run's result counts.
Run three real rounds of work that uses the route (gate rounds for the gate routes; `/plan` re-reads, `/dev`
understanding checks, and `/capture` extractions and re-audits for the cold-reader routes), then:

```
python3 ~/.claude/skills/_shared/scripts/shadow_diff.py summary
```

It says "ready to promote" only with at least 3 distinct real rounds compared, zero misses, and no failed
shadow run; fixture runs never count. Each round's `<evidence>/shadow/<stem>.shadow-diff.json` shows what
differed, and `shadow_diff.py compare <primary.result.md> <shadow.result.md> --role <role>` compares two
results again by hand. Whether today's setting was itself right about a miss is the owner's call. The
shadow's cost shows as "<role> (shadow)" in `spend.py report`. For a single run outside the override:
`run_isolated.py ... --shadow <model>:<effort>`; `--no-shadow` turns any shadow off. A code-verifier shadow
needs its own copy (`--shadow-dir`; `gate_run.py` makes it for the review, re-verify, and demo). No shadow
runs when the main run did not end OK, when the main run was Codex (so a review shadow needs a round where
Claude reviews), for a resumed run, for the loyal-evaluator (its later passes resume pass 1's session), or
while the project's phase is over its spend cap. Remove the shadow entry when the rounds are done.

**5. Ongoing.** Each `/evolve` change measures the fixtures it touches (`evolve.py touchmap <base> <branch>`
names them) with the served models stored. A full fixture run, monthly or after a Claude Code upgrade,
catches drift between changes: `python3 tests/agent_fixtures.py --runs 5`, its problem counts read against
the last run's (a run replaces `.evidence/fixtures/`, so keep a copy). A defect found after acceptance is
traced to the route that checked it (plan 10).

## Builder-side routes

The explorer, `scout-map`, and `explain` are measured by probe fixtures, which run on the `probe` route, so
`repro:route` cannot compare them. Run the probe once per setting and read each run's
`.evidence/fixtures/<name>/run-<n>/fixture-result.json` (`problem_count`, `dollars`, `served_models`); a run
replaces that folder, so copy it aside before the next setting:

```
python3 tests/agent_fixtures.py --only probe-explorer-recall --runs 5 --model claude-opus-5-5 --effort <the session's effort>
python3 tests/agent_fixtures.py --only probe-explorer-recall --runs 5 --model claude-sonnet-5-5 --effort medium
python3 tests/agent_fixtures.py --only probe-explain-grounding --runs 8 --model claude-sonnet-5-5 --effort high
```

The candidate passes when its problems over all runs are no more than today's and it costs less; the owner
weighs the numbers, then the change goes through `/evolve` like any other. No builder-side route moves to
Haiku: wide reading moves to Sonnet at most, and the main session reads the files the helper points to.

## The main session

The pipeline never switches the session's model or effort: a switch mid-session drops the prompt cache, and the
choice is yours (`/model`, `/effort`). This is the recommended setting per kind of work, not a rule any script
enforces:

| Work | Model and effort |
|---|---|
| `/plan`, `/plan adopt`, `/dev`, `/evolve`, a one-way architecture decision | Opus 5.5 at `xhigh` |
| `/fix`, `/deploy`, `/explain`, `/scout`, `/inbox`, `/capture`'s own session | Opus 5.5 at `xhigh`; `high` when the week's allowance is tight |
| `/next`, `/gate`, `/handoff`, `/pipeline` (scripts and checkers do the work) | whatever the session already runs |

Below Opus 5.5 at `high` is not recommended for work under the full pipeline: its projects are the ones where a
missed requirement costs more than the tokens saved. Start the next milestone in a fresh session instead of
lowering the effort: a long session re-reads its whole context on every turn.

## The fast reviewer (the fast pipeline's /gate-fast)

The fast pipeline (mAE7777/coding-pipeline-fast) has no routing table: `/gate-fast` names its reviewer's model in
its own text, and the default is **opus at xhigh** (fast plan 9.2). The `fast-reviewer-` fixtures measure that
reviewer's prompt (the blockquote in the fast repository's `skills/gate-fast/SKILL.md`, read from the checkout
at `FAST_REPO`, by default `../coding-pipeline-fast`; without it the fixtures are skipped) on four planted
fixtures (8 items a run: tally-defects' four, the import's dropped duplicate line, the refix's doubled archive
header, and two faked Done-when items) and three clean controls (tally-clean, structure-clean, refix-works).
Each run reviews a git copy of the fixture with the change uncommitted, as a fast project stands at
`/gate-fast`, inside the code-verifier sandbox. The probe answers two questions before fast plan 4.2's two
"measured" reviewer lines or a cheaper model ship: does sonnet catch as much as the opus default, and do the
two candidate lines (`tests/fixtures/agents/fast-reviewer/candidate-lines.md`) help.

Four sides, 5 runs each (40 planted item-trials and 15 clean runs a side). A run replaces
`.evidence/fixtures/`, so copy it aside after each side; the effort stays xhigh on both models, so only the model
differs (without the flags the fixtures run on fast's default, opus at xhigh):

```
python3 tests/agent_fixtures.py --only fast-reviewer --runs 5 --model claude-opus-5-5 --effort xhigh
python3 tests/agent_fixtures.py --only fast-reviewer --runs 5 --model claude-sonnet-5-5 --effort xhigh
FAST_REVIEWER_EXTRA=tests/fixtures/agents/fast-reviewer/candidate-lines.md \
  python3 tests/agent_fixtures.py --only fast-reviewer --runs 5 --model claude-opus-5-5 --effort xhigh
FAST_REVIEWER_EXTRA=tests/fixtures/agents/fast-reviewer/candidate-lines.md \
  python3 tests/agent_fixtures.py --only fast-reviewer --runs 5 --model claude-sonnet-5-5 --effort xhigh
```

What to compare, side by side: the `pooled:` line each run prints (the problems over the planted item-trials,
which are the pooled misses; the clean runs that failed, each a false block or a last line that is not "Matches
the goal: yes"; the dollars), and in each run's `fixture-result.json` the `served_models` (a side served by
another model than it asked for does not count) and `fast_prompt` (the fast revision, whether its SKILL.md had
uncommitted edits, and the prompt's sha256, so both sides are known to carry the same text). Measure the
candidate lines once the fast repository's new `fast.py diff` prints its file table: before that, the pack
holds `git diff --stat` in its place and says so, which measures a different line.

What each outcome decides:
- **The model.** The reviewer stays on opus at xhigh. It moves to sonnet only when, on the prompt that ships,
  sonnet's pooled misses are no higher than opus's and no clean sonnet run fails; the dollars say what the move
  saves. The move is a change to fast's gate-fast text, the owner's decision with these numbers.
- **The two lines.** They ship (fast plan 4.2) only when, on the reviewer's model, the prompt with them misses no
  more than today's prompt and fails no clean run; the first line's purpose is the dollars (no second run of the
  suite), so a side that costs no less has not earned it. Otherwise they stay out, or ship marked unmeasured
  (fast plan section 1, the admission test).
- A close result (within two misses of 40) is noise at 5 runs: run both sides again at `--runs 10`.

## Prices, and what they are worth

`spend.py` prices each run by the model that served it, per million tokens, as of 2026-10-19 (the pricing page):

| Model | Input | Cache write | Cache read | Output |
|---|---|---|---|---|
| claude-opus-5-5 | 4.00 | 5.00 | 0.20 | 20.00 |
| claude-sonnet-5-5 | 2.00 | 2.50 | 0.10 | 10.00 |
| claude-haiku-5-5 | 0.10 | 0.125 | 0.01 | 0.50 |

Haiku costs $0.50 input and $2.50 output for prompts over 100K tokens; `spend.py` applies that rate to each
transcript call whose prompt is over 100K, and keeps the base rate for an isolated run's summed usage, whose
prompt sizes it does not know. A 1-hour cache write costs 2x input (a 5-minute one 1.25x) when the usage names
it (`cache_creation.ephemeral_1h_input_tokens`, or `cache_write_1h` in a run's summary). Cache reads cost 0.05x input on Opus and Sonnet alike, so
moving a cache-heavy role to Sonnet halves its cache-read cost, as it halves the other prices. These are list prices: the owner's plan limits may
not follow their ratios, so the dollars are estimates. The table lives in `spend.py` (`PRICES`), and
`evolve.py` computes cost when it compares, from stored raw usage, so a price change moves both sides alike.
