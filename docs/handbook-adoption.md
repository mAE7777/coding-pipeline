# Project adoption record

Version: 1.0 · Handbook: AI Engineering Handbook 1.0

Record date 2026-10-16. A read-only audit of this repository at commit `587f48c`, filled into the kit's
`templates/project-adoption.en.md`. It replaces the tables in section 5 of `docs/plan-craft-economy.md` (the
plan the owner locked on 2026-10-16) as the record of which handbook chapters apply and why. Plan sections are cited as
"plan 5.2". The template's rule holds throughout: "An empty field is not a passed requirement. Every
applicability decision needs a business or system-boundary rationale."

## Scope
Project and accountable owner: The coding pipeline in this repository: 15 skills, 6 checker agents, 5 hooks,
28 shared scripts, `gate.sh`, `install.py`, and the two settings patchers. In the handbook's words (Ch. 1) it is
"the engineering system in which agents build software"; the products it builds are a separate boundary.
Accountable owner: the repository owner, who alone makes the rulings in the constitution's "Human gates" list and
rules on any change to `/evolve`'s judge.

User task: The owner builds software with coding agents (Claude Code, and Codex alongside it). An idea, a
captured dossier, or an existing codebase becomes an intent locked in the owner's own words; milestones are
built in one sustained run, checked by isolated checkers with a computed verdict, and accepted by the owner after
watching the demo; `/deploy` ships with each irreversible action confirmed. `/evolve` improves the pipeline from
its own use. This record's task: map the handbook's requirements to the controls that exist, name the gaps, and
point each gap at a section of the approved plan.

Non-goals:
- Hosting or operating the products the pipeline builds. Their runtime controls belong to each product.
- The handbook's coordination machinery (task leases, fencing, an action ledger) as pipeline machinery: one
  writer per checkout and no business effects of its own (plan 5.3).
- The multi-team or service-fleet profile (Ch. 26). One owner, one machine.
- Release bundles for the pipeline beyond the install manifest (plan 5.3).
- Optimizing Codex (plan header), though `install.py check` must stay green for it.
- Changing any pipeline behavior. This record changes none.

Boundary between development agents and product agents:
- Development agents, the scope of this record: the builder session (Claude Code or Codex, running with the
  owner's own permissions and the pipeline's hooks); its subagents (none by default; a read-only explorer;
  parallel builders in at most two worktrees only when the owner asks; capped at 5 at once and depth 2 by the
  environment `settings_patch.py` writes); and the isolated checkers (`code-verifier`, `loyal-evaluator`,
  `gate-judge`, `cold-reader`, `claim-verifier`, `change-reviewer`) that `run_isolated.py` starts. `/polish`
  names four outside agents that are not in this repository.
- Product agents: any agent, model call, or external effect inside a product the pipeline builds. They are
  product behavior, specified in that product's intent (mechanism cards, must-not-lose items) and checked by the
  gate like any other behavior. The handbook's controls for them are in the conditional reference
  `skills/_shared/references/agent-product/` (plan 5.2).
- Where the two meet: checkers run the product only in copies that leave out the build record, `.evidence/`,
  and `.env` files other than example ones unless the project names them under "Gate env files"
  (`gate_copies.py`), under a network fence limited to localhost plus any "Gate network" hosts (a Codex-family
  checker also reaches HTTPS for its own model call). Ch. 1 warns: "A development agent's test account must not
  become the product's production identity by accident." The pipeline keeps the two apart by rule only:
  `/deploy` asks for scoped, expiring tokens and no ambient admin credentials, and the owner confirms every
  credentialed action.

Existing code, environments, data, and authority:
- Code: `skills/` (15 skills and `_shared`), `agents/`, `hooks/`, `skills/_shared/scripts/`, `install.py`,
  `settings_patch.py`, `codex_hooks_patch.py`; tests in `tests/` (27 `test_*.py` suites and `static_checks.py`,
  run by `bash tests/pipeline-selftest.sh`; checker fixtures in `tests/agent_fixtures.py`; headless scenarios in
  `tests/system_scenarios.py`). No CI configuration is in the repository.
- Environments: the owner's machine; the README requires macOS for the sandbox and copy-on-write clones. The
  installed copies live in `~/.claude` and, when Codex is installed, in Codex's package. This record was written in
  a Linux container, where the checker sandbox was not exercised.
- Data: each product's build record in that product's repository (`intent.md`, `milestones.md`,
  `interfaces.md`, `decisions.md`, `fix-log.md`, `inbox.md` committed; `brief.md`, `state.md`, `gate.md`,
  handoffs, reviews, research, sources, and `.evidence/` local-only); the `/evolve` ledger in
  `~/.claude/pipeline-evolution/`, outside the repository because it holds project details; the install manifest
  `~/.claude/.pipeline-install.json`; session transcripts, which `rulings.py` reads to prove the owner's words.
- Authority: owner-only rulings (the constitution's "Human gates"), proven against the transcript by
  `rulings.py`; checkers sandboxed by `run_isolated.py` (no user settings, plugins, MCP servers, or slash
  commands; a fixed tool list per role; reads fenced to the copy; writes in the copy and caches); the project's
  ON/OFF choice (`project_policy.py`, OFF unless explicitly ON); the machine-wide heavy-job lock; spend caps on
  capture and adoption that only the owner's proven words raise.

## Invariants and acceptance
Test commands run from the repository root. "Planned" names enforcement that is part of the approved plan and not
yet built.

| ID | Invariant / acceptance condition | Operations | Enforcement point | Test command / evidence | Owner |
|---|---|---|---|---|---|
| INV-01 | The builder never grades its own work: every gate and intent judgment runs as a separate headless process in a prepared copy, with a pack rendered by script from files. | `/gate` rounds, `/loyal` checks, cold reads, `/evolve` reviews | `skills/_shared/scripts/gate_run.py` `isolated()`; `run_isolated.py` `main()`, `settings()`, `claude_cmd()`; `gate_copies.py` `make()`, `build_copy()` | `python3 tests/test_run_isolated.py` (`test_bash_role_fence`, `test_read_only_roles_get_no_shell_or_exemption`, `test_builder_session_variables_never_reach_a_checker`); `python3 tests/test_gate_copies.py` (`test_review_copy_holds_the_product_not_the_builder_record`, `test_copy_is_independent_of_the_live_tree`); `python3 tests/test_gate_run.py` (`test_a_codex_builder_gets_its_review_from_claude`) | repository owner |
| INV-02 | The gate verdict is recomputed from the evidence. The judge's verdict is an input: a looser one is overruled and listed, a stricter one makes the round INCONCLUSIVE, and a finding still blocking in a second round makes it BLOCKED for the owner. | every gate round and intent check | `gate_report.py` `compute()`, `checker_rules()`, `update_ledger()` | `python3 tests/test_gate_report.py` (`test_the_checkers_own_results_outrank_a_lenient_judge`, `test_judge_stricter_than_its_findings`, `test_case_and_shape_do_not_let_a_failure_through`, `test_blocking_finding_then_same_finding_again`) | repository owner |
| INV-03 | An owner ruling counts only when its quoted words are a whole sentence, or the whole message, that the owner typed. Agent hand-backs, hook text, compaction summaries, and notifications that arrive in the user role never count. | intent lock, acceptance, stand-in consent, inbox rulings, spend cap raises, `/evolve` rule changes | `rulings.py` `cmd_record()`, `typed_messages()`, `quote_fits()`, `entry_proven()`, `cmd_check()` | `python3 tests/test_rulings.py` (`test_record_refuses_words_the_owner_did_not_type`, `test_agent_reports_and_notifications_are_not_the_owner`, `test_a_cut_quote_cannot_flip_the_meaning`, `test_a_subagent_rollout_holds_no_owner_words`) | repository owner |
| INV-04 | The locked intent changes only by a re-freeze that names a proven owner ruling; any edit to the locked text fails verification, and every gate round verifies it. | `/plan` lock, `/plan amend`, gate layer 1 | `intent_lock.py` `main()` (stamp, verify), `intent_hash()`, `ruling_ok()`; `gate_run.py` `layer1()` | `python3 tests/test_intent_lock.py` (`test_stamp_requires_a_proven_ruling`, `test_edit_after_lock_fails_verify`, `test_unproven_refreeze_fails`) | repository owner |
| INV-05 | An acceptance is a proven owner ruling that names the candidate fingerprint of the latest ACCEPT-READY round (a WARN when no such round is on the machine to compare); a contract change after acceptance needs a proven superseding ruling; a release ships only the accepted candidate. | `/gate accept`, `/deploy` | `milestone_lint.py` `check_acceptance()`, `latest_accept_ready()`; `fingerprint.py` `fingerprint()`; the release comparison is step 1 of `skills/deploy/SKILL.md` (a skill rule, not a script) | `python3 tests/test_milestone_lint.py` (`test_accepted_needs_a_proven_acceptance`, `test_acceptance_names_the_candidate_that_passed`, `test_contract_change_after_acceptance`) | repository owner |
| INV-06 | Tests are never weakened to get green: no deleted test, new skip or focus marker, raised timeout, or removed assertion without the owner's ruling. | `/dev`, `/fix`, every gate round | Today: prose in `skills/dev/SKILL.md` and `skills/fix/SKILL.md`; `gate.sh` check `focused-tests` FAILs on `.only(` in `*.test.*` and `*.spec.*` files. Planned: `gate.sh` check `test-tamper` against the milestone baseline, cleared only by a ruling `rulings.py` proves (plan 5.2, Ch. 6 row) | `focused-tests` has no dedicated test in `tests/`. Planned evidence (plan 9, Phase 5): "`test-tamper` catches a planted deleted assertion and passes a clean change" | repository owner |
| INV-07 | Nothing silent: every check prints PASS, FAIL, WARN, or SKIP with its reason; skipped and not-run checks and missing pack inputs become listed exceptions; a missing input is written NOT PROVIDED, never guessed. | gate rounds, the deterministic layer, every checker pack | `gate.sh` `report()`; `gate_report.py` `compute()`; `render_pack.py` `render()` | `python3 tests/test_gate_sh.py` (`test_check_run_names_every_skip`); `python3 tests/test_gate_report.py` (`test_malformed_or_missing_evidence_is_inconclusive_and_clears_the_tick`, `test_missing_reviewer_or_demo_result_is_inconclusive`, `test_family_switch_is_an_exception`); `python3 tests/test_render_pack.py` (`test_missing_input_is_named_not_guessed`) | repository owner |
| INV-08 | Checkers never see the builder's beliefs: packs come from files only; the blind copy carries no intent; the evaluator's first pass carries no intent phrase; a canary token planted in the real project makes a run that read it LEAK and the round INCONCLUSIVE. | every gate round and `/loyal` check | `render_pack.py` `render()` (ends with a source manifest and sha256 values); `gate_copies.py` `blind_strip()`, `scan_blind()`; `run_isolated.py` `pack_leaks()` and the canary check in `launch()`; `gate_run.py` `main()` plants the canary. Planned: D8 keeps the builder's verification skill and feature maps out of every pack (plan 3, 4.2) | `python3 tests/test_gate_copies.py` (`test_blind_copy_has_no_intent`, `test_leak_scan`, `test_every_document_format_leaves_the_blind_copy`); `python3 tests/test_run_isolated.py` (`test_pass_one_pack_leak_detected`); `python3 tests/test_render_pack.py` (`test_loyal_pass_one_holds_no_goal`); `python3 tests/test_gate_run.py` (`test_escape_to_the_real_project_is_a_leak`) | repository owner |
| INV-09 | One writer per checkout: the first session to edit is recorded as the writer in `state.md`, and a second agent in the same checkout is told so at session start. This is a recorded claim and a warning, not a lock. | every session in a managed project; `/handoff` | `continuity.py` `claim()`, `session_start()`, `other_agents()`; the rule in `skills/handoff/SKILL.md` | `python3 tests/test_continuity.py` (`test_claim_rewrites_writer_once_and_logs`, `test_codex_apply_patch_claims_the_writer_role`, `test_a_session_that_comes_back_takes_the_role_back`, `test_stop_by_a_non_writer_does_nothing`). The session-start warning has no dedicated test | repository owner |
| INV-10 | A handoff carries every active constraint, must-not-lose item, open item, and the live fingerprint; a packet that drops one fails. | `/handoff`, the continuity stop hook | `handoff_check.py` `main()`; `continuity.py` `write_packet()` | `python3 tests/test_handoff_and_fingerprint.py` (`test_dropped_constraint_fails`, `test_dropped_must_not_lose_fails`, `test_dropped_open_item_fails`, `test_stale_fingerprint_fails`) | repository owner |
| INV-11 | After a compaction, writes wait until the state files have been read again. | every compaction in a managed project | `hooks/snapshot-state.py` `main()`; `hooks/reload-gate.py` `arm()`, `track()`, `guard()` | `python3 tests/test_compaction_hooks.py` (`test_writes_blocked_until_all_required_read`, `test_shell_writes_blocked_and_shell_reads_allowed_while_armed`, `test_naming_a_file_without_printing_it_is_not_reading_it`) | repository owner |
| INV-12 | One heavy job (build, test suite, browser, simulator) runs at a time on the machine; a heavy command outside the wrapper is denied. | builder, subagents, checkers, Codex | `heavy.py` `cmd_run()`, `wait_for()`, `try_flock()`; `hooks/heavy-guard.py` `check_bash()`, `check_browser()` | `python3 tests/test_heavy.py` (`test_second_job_waits_then_busy`, `test_events_log_shows_no_overlap`, `test_forged_reentry_token_does_not_bypass`, `test_bounded_commands_denied_with_run_suggestion`) | repository owner |
| INV-13 | Capture and adoption stay within the owner's budget: an isolated run in a phase over its cap starts BLOCKED, and only the owner's proven words raise the cap. | `/capture`, `/plan adopt` | `spend.py` `status()`, `cmd_raise()`; the budget check in `run_isolated.py` `main()` | `python3 tests/test_spend.py` (`test_over_the_cap_stops_and_only_the_owner_raises_it`); `python3 tests/test_run_isolated.py` (`test_a_phase_over_its_budget_cap_starts_no_run`) | repository owner |
| INV-14 | A pipeline change is kept only when a judge fixed before the change says BETTER, the isolated change reviewer accepts it, and, for a capability or rule change, the owner's words are proven. A change to the judge is the owner's ruling. | `/evolve` | `evolve.py` `compare()`, `change_problems()`, `cmd_record()`, `review_covers()`; running the judge from the installed copy is a rule in `skills/evolve/SKILL.md` | `python3 tests/test_evolve.py` (`test_better_needs_every_reproduction_to_flip_and_nothing_worse`, `test_worse`, `test_a_worse_change_is_refused`, `test_an_owner_kind_needs_the_owners_words`) | repository owner |
| INV-15 | A project is unmanaged until explicitly turned ON; a missing, unreadable, or invalid choice is OFF; turning OFF stops in-flight formal runs. | every hook, runner, and skill | `project_policy.py` `read()`, `managed()`, `require()`, `set_mode()` | `python3 tests/test_project_policy.py` (`test_default_off_even_with_partial_adoption_and_old_lock`, `test_malformed_or_missing_policy_never_enables_management`, `test_inflight_isolated_checker_is_cancelled_without_result_or_descendant`) | repository owner |
| INV-16 | The installed files equal the repository's; a live edit under `~/.claude` stops an apply; every replaced file is backed up first; retired skills and agents are archived outside the load path. | `install.py apply`, `install.py check` | `install.py` `cmd_apply()`, `live_edits()`, `cmd_check()` | `python3 tests/test_install.py` (`test_check_catches_a_modified_install`, `test_a_live_edit_stops_apply_until_ported_or_overwritten`, `test_apply_installs_archives_and_keeps_the_owners_files`) | repository owner |
| INV-17 | Planned. A checker's model or effort changes only after that role passes all five tests of plan 7.3; a mismatch between requested and served model is reported; independence is never traded for tokens (D7, D8). | every isolated run | Planned: `models.py`, `skills/_shared/models.json`, `--model` in `run_isolated.py`, a role-to-agent static check (plan 7.1, 7.3, 8). Today each summary records the model the stream reports and the agent file's sha256, and every Claude-served checker runs on the CLI's default model at `xhigh` (plan 2.3) | Planned (plan 9, Phase 3): "each role passes 7.3" | repository owner |
| INV-18 | Planned. A local test-and-fix loop changes method instead of repeating: a failure that survives two fixes sharing one premise prints a notice, and `/next auto` stops when a step repeats without the record moving (Ch. 4). | `/dev`, `/fix`, `/next auto` | Today: `/fix` stops after three failed attempts with a Blockers row (prose). Planned: the failure-signature log in `heavy.py` and the stop in `project_status.py` (plan 6.0) | Planned (plan 9, Phase 1): hook and script unit tests; selftest green | repository owner |

## Adoption matrix
| Chapters | Applicable / not applicable and why | Current gap | Risk | Change task | Completion evidence |
|---|---|---|---|---|---|
| 01–04 Contract, requirements, architecture, runtime | Applicable. This record is the Ch. 1 artifact. Ch. 2's acceptance layers map to done examples, must-not-lose items, and the gate. Ch. 3: scripts decide (verdict, proofs, locks) and models propose. Ch. 4: named exits (the constitution's Statuses) and hard limits outside prose (the heavy lock and spend caps in scripts, subagent caps in the settings `settings_patch.py` writes). | No slot for an operating objective (latency, cost) in a milestone. No detection of a loop without progress beyond `/fix`'s three attempts. Checker models are not chosen on the pipeline's own workload. | Medium: wasted spend; acceptance quality unaffected. | Plan 5.2 (Operating objective line), 6.0 (loop breakers), 7 (role table). | Plan 9: Phase 1 done condition; Phase 3, each role passes 7.3. |
| 05–06 Topology and conflict atlas | Applicable. One builder plus independent checkers in separate processes; the code review prefers the other model family; parallel builders only when the owner asks. Atlas rows that apply: acceptance tampering, correlated judgment, permission leakage, file overwrite, partial success shown as completion, stale approval. Duplicate claims are covered by the round lock (row 07). Write skew, ABA, and split-brain coordinators do not arise with one writer on one host. | Acceptance tampering is guarded by prose and `focused-tests` only (INV-06). File overwrite is a warning (INV-09). | High for tampering: a weakened test can turn a round green. Low for overwrite. | Plan 5.2 `test-tamper`. | Plan 9, Phase 5 `test-tamper` fixture. |
| 07 Coordination controls: task ledger and claims | Partly applicable. A milestone is the task (status in `milestones.md`), a gate round `r<n>` is the attempt, the candidate fingerprint is the input version; one round per project through a PID round lock; the journal through `project_status.py record`. Task leases with fencing are not needed with one writer on one host (plan 5.3). | None required. | Low. | None. | `python3 tests/test_gate_run.py` (`test_a_stale_round_lock_is_removed_and_a_live_one_refuses`); `python3 tests/test_heavy.py`. |
| 08 Coordination controls: parallel coding | Applicable in its isolation parts. Checkers work only in copies (review, demo, blind); a server started from the real project blocks the round; each checker gets a private temp folder; secret `.env` files and evidence stay out of copies. Builders: one writer per checkout; parallel builders in worktrees only when asked. | No integrated-candidate test for parallel builders' combined branches; one writer is a warning. | Low while parallel builders are rare. | None planned. | `python3 tests/test_gate_copies.py` (`test_secrets_build_output_and_evidence_excluded`); `python3 tests/test_run_isolated.py` (`test_server_from_the_real_project_blocks`). |
| 09–10 Coordination controls: shared state, fencing, external effects | Not applicable as pipeline machinery (plan 5.3): one writer per checkout and no business effects of its own. The pipeline's own external actions are `/deploy`'s, each confirmed by the owner with its exact command. Applicable to products, conditionally: the agent-product reference. | The reference exists in the repository, but no skill loads it and `install.py` does not install it. The planned PR tooling (plan 11a) will be the pipeline's first repeated external writes. | High for products with payments or sends until the reference is wired; low for the pipeline today. | Plan 5.2 (Ch. 7 to 11, 15, 19, 20 row), plan 8 (`install.py`, `/plan` wiring), plan 11a (`pr_watch.py` fails closed on unknown states; `land-check`). | This change: the reference and its 36 tests, passing from a temporary copy (`reference/SOURCE.md`). Pending: `install.py check` covering the folder; `/plan` intake reading it. |
| 11 Coordination controls: messages and handoffs | Applicable. Packets are rewritten at every stop and checked (INV-10); a new session is told who worked last and what changed; `/handoff receive` restates and reconciles before acting; checker results are read from their last fenced JSON block, never from prose. | Subagent returns are free-form, with no minimum result package. The receiver's acknowledgement is prose. | Medium: a subagent's inference can be taken as fact. | Plan 5.2 (Ch. 11 row) and 11a: `code-craft/brief.md` from the kit's task-contract and handoff schemas. | Planned: the brief template, and `/dev`'s Subagents paragraph pointing to it. |
| 12 Coordination controls: facts, goals, decisions | Applicable. The constitution's authority order; append-only `decisions.md` with proven owner entries; the blind evaluator describes the product before seeing the goal, and the judge is not told why the builder made its choices (`agents/gate-judge.md`); `/scout` grades claims; `/inbox` keeps others' words until a decision quotes them. | Reports do not label observation, inference, and recommendation. The decision template lacks the kit's decision-record fields. | Medium-low. | Plan 5.2 (Ch. 12 row); 11a (decision fields for material decisions). | Existing: `python3 tests/test_inbox.py` (`test_an_item_removed_by_hand_is_a_failure`). Planned: the template change. |
| 13 Coordination controls: long-running work and cancellation | Applicable. `state.md` is the checkpoint (Done with evidence, Open, In flight, Blockers, Next); packets carry the live fingerprint; `/dev resume` reconciles with the tree; `/pipeline off` cancels in-flight formal runs. | No Eliminated approaches section, so a compaction can lead back into a dead end. | Medium: repeated work and spend. | Plan 5.2 (Ch. 13 and 16 row), 6.2 (re-entry digest). | Existing: `python3 tests/test_project_policy.py` (`test_running_gate_child_is_cancelled_after_switch_off`). Planned: template section and hook tests (Phase 1). |
| 14 Coordination controls: capacity and budgets | Applicable. Controls sit at the resource: the heavy lock, the browser lease, subagent caps, one gate round per project, capture and adoption caps; a checker that ends ERROR or INCONCLUSIVE is re-run once (`gate_run.py` `isolated()`). | Cost per accepted milestone is not reported; `spend.py` weights tokens by type, not by model (plan 2.3). | Medium: cost is invisible, and routing savings cannot be measured. | Plan 5.2 (Ch. 14 row), 6.1 (`spend.py report`, per-model weights). | Plan 9, Phase 0 baseline table. |
| 15 Tools and protocols | Applicable at the checker boundary: each role has a fixed tool list, no MCP servers, no slash commands, no user settings. Protocol detail (MCP, A2A) is not applicable to the pipeline (plan 5.3); products get it through the agent-product reference. | None for the pipeline. The builder's command output is not bounded. | Low. | Plan 6.2 (`heavy.py --tail`). | `python3 tests/test_run_isolated.py` (`test_min_tools_per_role`, `test_claude_command`). |
| 16 Context and compaction | Applicable. Law 6 (disk is truth); a snapshot before compaction and writes held until the state files are reread (INV-11); references and fingerprints in handoffs; checkers get a rendered pack, never the builder's conversation. | About 3,000 tokens of descriptions load in every session, also where the pipeline is OFF (plan 2.3, measured there). No re-entry digest. | Medium: cost. | Plan 6.2 (shorter descriptions, digest); 5.2 (Ch. 18 row budget). | Existing: `python3 tests/test_compaction_hooks.py`. Planned: always-loaded byte budget in `static_checks.py`. |
| 17 Retrieval, memory, data lifecycle | Partly applicable. `/capture` keeps sources verbatim in numbered units, never edited; a changed position marks the old unit superseded; the owner's words stay apart from an assistant's. Durable state is files: build records, evidence folders, the `/evolve` ledger. | No path that removes a withdrawn source's derived content (dossier points, research notes). Not in the plan. | Low for one owner on one machine; higher if a source holds a third party's personal data. | None; listed under open questions. | None. |
| 18 Skills and controlled improvement | Applicable. Skill names match their folders and SKILL.md files stay under 200 lines (`static_checks.py`); `/evolve` improves without self-authorizing (INV-14). | The always-loaded listing and its cost are untested; rules carry reasons but no failure and enforcement label (App. B). | Medium: prose grows unseen; untestable rules accumulate. | Plan 5.2 (Ch. 18 row), 6.2 (rule ledger), D5. | Planned: `static_checks.py` budgets; `docs/rule-ledger.md` with one row per rule. |
| 19 Security boundaries | Applicable at the pipeline's boundary. Checkers: OS sandbox with no unsandboxed fallback, fenced reads and writes, localhost network, canary, no settings or plugins; copies leave out secret `.env` files; `gate.sh` `secrets` FAILs; supplied material is data (`/plan` rule). | The builder session runs with the owner's own Claude Code or Codex permissions; the pipeline adds hooks but no sandbox for it. | Medium: a builder misled by injected text acts with the owner's permissions. | None for the builder in the plan; for products, control 8 of the agent-product reference. | `python3 tests/test_run_isolated.py` (`test_codex_profile_fences_reads`, `test_codex_profile_fences_writes_and_network`); `python3 tests/test_gate_sh.py` (`test_secret_is_a_fail`). |
| 20 Approval and interaction | Applicable. Approvals bind to an exact candidate: acceptance names the contract hash and fingerprint (INV-05); stand-in consents pair with a named non-goal or contract-blocked entry; `/deploy` confirms each irreversible action with its exact command; readiness keeps five facts apart, and "Submitted" is never reported as "launched". Voice, real-time, generated UI, and commerce protocols do not apply to the pipeline. | `/deploy` confirmations are a skill rule, not a recorded approval bound to a payload hash and expiry. | Medium: a confirmed action could drift from the command run. | Not in the plan; open question. PR landing gets `land-check` (plan 11a). | `python3 tests/test_rulings.py` (`test_consent_needs_owner_and_pairing`). |
| 21 Backend, data, frontend baselines | Applicable to products, through the checker protocols in `skills/gate/references/` and the deterministic layer. | The handbook's frequently missed integration cases are not in `regression-and-coverage-strategy.md`. | Medium: edge cases missed in review. | Plan 5.2 (Ch. 21 row). | Planned: the table in that reference. |
| 22 Day-to-day workflow | Applicable. `/dev` reads before writing and wires as it goes; `/fix` reproduces first, makes the smallest change, keeps a regression test, and stops after three attempts; the gate is the independent review; `/deploy` verifies live; built, accepted, and released stay separate states. | No prompt for property or differential tests on numeric or set-shaped invariants; tests-never-weakened is prose (INV-06). | Medium. | Plan 5.2 (Ch. 22 and 23 row; `test-tamper`). | Planned: milestone guide text; Phase 5 fixture. |
| 23 Evaluation | Applicable. Checkers run against planted-defect and clean fixtures, three times each; headless scenarios on toy projects; `/evolve` measures both sides in one environment with one instrument; the judge's output is checked by code. | Fixtures pass or fail as a whole, not per planted item; no pooled comparison; the only end-to-end gate scenario has one milestone (plan 2.3). | Medium: a prompt or routing change could lower catch rates unseen. | Plan 6.1, 7.3 (owner decision 3). | Plan 9, Phase 0 baseline; Phase 3 pooled comparisons. |
| 24 Observability and progress | Applicable. Each run keeps its pack and its sha256, the stream, the result, and a summary with token usage, the reported model, and the agent file's sha256 under `.evidence/`; `project_status.py` names the next step and who takes it (builder, owner, or wait); the owner summary leads with exceptions. | No requested-versus-served model check; no cost line per round or milestone. | Medium-low. | Plan 7.1 (mismatch reported), 6.1 (`spend.py report`, gate cost line). | Planned: Phase 0 and Phase 3 tests. |
| 25 Release and recovery | Partly applicable. The release is `install.py apply`: a manifest with each installed file's sha256 and the repository revision, backups of replaced files, archives of retired pieces, and `install.py check`. Ch. 25 release bundles for the pipeline are not adopted (plan 5.3). | Model configuration is not part of a release: Claude-served checkers run on the CLI's default model. | Medium: a Claude Code upgrade can change checker behavior with no install. | Plan 11a (manifest records the routing table's hash), 7 (`models.json`). | Existing: `python3 tests/test_install.py`. Planned: manifest field and check. |
| 26 Adoption | Applicable. The pipeline matches the small-team profile: one repository, versioned specifications, one execution agent with independent review, isolated workspaces, explicit records. | No adoption record or review date before this one. | Low. | This record (plan 11a). | This file; the review triggers below. |
| 27–30 Cases, runbooks, reference, glossary | Applicable as reference. Ch. 29's code ships in the agent-product reference; kit templates are used as plan 11a lists. Runbooks that fit the pipeline: looping agent or unexpected spending, and green tests with a broken product (the demo runs from an untouched copy; `/deploy` verifies live). The pipeline keeps its own glossary (`record-glossary.md`). | The payment, memory-leakage, and split-brain runbooks do not apply to the pipeline itself. | Low. | Plan 11a. | `skills/_shared/references/agent-product/reference/SOURCE.md` hashes; 36 tests pass from a temporary copy. |
| A–B Evidence and validation | Applicable. Appendix A's corrections are followed: no fixed thresholds as universal gates, approval is not a fail-safe, self-improvement produces candidates. Appendix B's rule hygiene ("Rules without a trigger, owner, or test should be removed, supported with evidence, or downgraded to an unverified hypothesis") is the method of the rule ledger. | Rule ledger not written; App. B exercises 3 and 5 not run against this repository. | Low. | Plan D5, 6.2. | Planned: `docs/rule-ledger.md`. |

## Release and recovery
Tested integrated commit: No CI configuration is in the repository. The integrated state is tested locally with
`bash tests/pipeline-selftest.sh` (every script and hook suite plus the static checks) and, on the owner's
machine, `python3 tests/agent_fixtures.py` and `python3 install.py check`. The install manifest records the
repository revision, marked `+local-changes` when the tree was dirty. This record was written against `587f48c`
and changes no pipeline code.

Compatible migration plan: Earlier record formats go through `/plan convert`; `record_check.py` classifies a
project before `/plan` routes it. `install.py apply` archives retired skills and agents outside the load path,
removes files the repository no longer has (keeping the owner's `brain.md`, `friction.log`, and `tests/`), and
stops on a live edit. Codex's copies are converted on a clone that replaces the package only after every
acceptance gate passes; a failed installer restores the last accepted package; an interrupted sync is finished or
undone at the next apply. After the update that introduced the ON/OFF choice, managed projects must turn ON
explicitly (README). An install while a gate round runs is not covered.

External-effect reconciliation plan: Not applicable to the pipeline's own operation, which has no business
effects (plan 5.3). Its external actions are `/deploy`'s: each irreversible or credentialed action is confirmed by
the owner in plain English with its exact command, the live artifact is verified afterwards, and a submitted
review or pull request is reported as submitted, never launched. The planned PR tooling will write to GitHub
through `gh`, fail closed on unknown states, and land only heads whose `land-check` matches the accepted
fingerprint (plan 11a); reconciling an interrupted land is an open question. For products, controls 1 and 2 of
the agent-product reference.

Cancellation and credential-revocation owner: The repository owner. `/pipeline off` stops in-flight formal runs
and their checkers (`python3 tests/test_project_policy.py`:
`test_inflight_isolated_checker_is_cancelled_without_result_or_descendant`); a stopped checker leaves no
private folder (`python3 tests/test_run_isolated.py`: `test_a_stopped_checker_leaves_no_private_folder`).
Checkers run without user settings, and a Codex checker gets a fresh `CODEX_HOME` that links only `auth.json`.
Deploy tokens are scoped and expiring by the `/deploy` rule; revoking them is the owner's.

RPO / RTO and drill evidence: No service-level RPO or RTO: the pipeline is a local tool, not a service. Recovering
the pipeline is a reinstall: check out a known commit and run `python3 install.py apply`. Every file an apply
replaced or removed is in `~/.claude/_backups/pipeline-install-<UTC time>/`; retired skills and agents are in
`~/.claude/_archived-skills/` and `~/.claude/_archived-agents/`. A product's committed record recovers with its
repository; its local-only files and the `/evolve` ledger have no pipeline backup. No restore drill has been run;
`tests/test_install.py` exercises apply, archive, and the Codex rollback paths in temporary homes.

Canary stop conditions: Not applicable as a release practice: an install applies to the whole machine at once,
with no staged exposure. (The gate's "canary" is a different control: a token that detects a checker reading the
real project.) The stops that exist come before a change ships: `/evolve` keeps a change only on BETTER, and
`install.py check` must pass. The plan adds shadow rounds for routed checker roles, promoted only when the
candidate missed nothing today's setting caught (plan 7.3, step 4).

## Open questions and exceptions
Exception scope, rationale, compensating controls, approver, and expiry:
- E-1. Tests never weakened (Ch. 6, 22) rests on prose plus `focused-tests` until `test-tamper` ships.
  Compensating: the gate's deterministic layer runs the project's test suite, and the code-verifier sees the diff
  since the milestone baseline. Approver: the owner, through the plan locked 2026-10-16. Expiry: plan Phase 5.
- E-2. One writer per checkout is a recorded claim and a warning, not a lock (Ch. 8). Compensating: parallel
  builders only in worktrees and only when the owner asks; handoff packets carry fingerprints. Approver: the owner
  (plan 5.3). Expiry: review when parallel builders become routine.
- E-3. Chapters 9 and 10 are not adopted as pipeline machinery (plan 5.3). Compensating: no business effects;
  each `/deploy` action confirmed by the owner. Approver: the owner (plan 5.3). Expiry: when the PR tooling ships,
  decide whether landing needs a recorded intent.
- E-4. Chapter 25 release bundles are not adopted for the pipeline (plan 5.3). Compensating: the install manifest
  (per-file sha256, revision) and each run's pack and agent-file hashes. Approver: the owner (plan 5.3). Expiry:
  when `models.json` lands, the manifest records its hash (plan 11a).

Open questions for the owner:
- Should a `/deploy` confirmation be recorded and bound to its exact command and an expiry, as Ch. 20 asks for
  approvals?
- How is a PR land interrupted halfway reconciled before the PR tooling ships?
- Should a withdrawn captured source remove its derived dossier points and notes (Ch. 17)?

Unverified assumptions:
- The checker sandbox holds as documented on the owner's macOS machine; it was not exercised in this container.
- The installed copies under `~/.claude` match the repository; `install.py check` was not run here.
- The measured figures quoted from the plan (always-loaded bytes, spend) are the plan's measurements, not
  re-measured for this record.
- An install while a gate round runs leaves the round consistent; nothing tests it.
- The handbook text quoted in the agent-product reference matches the 1.0 edition (evidence baseline
  2026-10-10); a later edition may change it.

Next review triggers:
- A plan phase completes (plan 9), especially Phase 5 (`test-tamper`) and Phase 3 (model routing).
- A checker's model, effort, or family changes, or Claude Code or Codex is upgraded.
- The PR tooling ships, so the pipeline writes to GitHub on its own (E-3).
- A checker's tools, sandbox, or network fence changes, or the pipeline runs on a platform other than macOS.
- A second person works in the repository, or parallel builders become routine (E-2).
- An `/evolve` incident traces to a chapter marked not applicable here.
- A new handbook edition, or an Appendix A correction that touches a control used here.
- Proposed calendar review: 2027-01-16, unless a trigger above comes first.
