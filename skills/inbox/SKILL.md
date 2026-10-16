---
name: inbox
description: "Keep and weigh what arrives mid-build: others' opinions, proposed changes, new ideas, feedback, review notes, and ideas the owner floats undecided. /inbox add <who>: <their words> records one verbatim; /inbox review [IN-nnn] weighs it against the intent and recommends; /inbox list shows the open items. Use for /inbox, 'someone suggested', 'add this idea', 'feedback from', 'what do you think of this proposal', and new ideas after the lock."
argument-hint: "[add <who>: <their words> | review [IN-nnn] | list]"
---

**Workflow choice, first.** Run `python3 ~/.claude/skills/_shared/scripts/project_policy.py status <project> --json`. OFF or no choice: do the requested work directly from the existing documents, code, and tests, with no formal step, record, or End chain. ON: the rules below apply; recheck the choice before each next step. Only the owner's explicit on or off, through /pipeline, changes it. Contract: `~/.claude/skills/_shared/references/project-control.md`.

# /inbox

The inbox is where input waits until it is decided, so nothing said about the project is lost in a chat and
nothing enters the build without being weighed. The failure it prevents runs both ways: a good idea
forgotten, and an idea quietly merged in, bending the intent without anyone deciding it.

Load-bearing rules (`inbox.py` refuses what breaks the first three):
- Nothing in the inbox is a decision, and nothing leaves it without one: `inbox.py resolve` needs a decision
  entry that quotes the item, gives the verdict, and names where each adopted part went; `inbox.py check`
  (also run by the gate) fails on any item that vanished.
- The proposer's words are kept verbatim (or, for a captured conversation, cited by turn). Your reading of
  them goes beside them, never in their place.
- Who decides: the builder may decide alone only a whole adoption that stays inside the current contract
  (an approach, a detail the intent leaves open), written `--proposed` and reported. Declining input in whole
  or in part, reshaping it, placing it in a milestone, and anything that changes the intent or a milestone
  contract are the owner's rulings, in their words. One owner message may rule on a batch.
- The owner's own instruction is a ruling, not an inbox item: apply it (`/plan amend` when it changes the
  intent). An idea the owner floats without deciding ("maybe we could ...") goes in, in their words.
- A proposal that reopens a settled decision says so, cites the earlier entry, and its weighing must show
  what changed since that ruling.

Scripts: `~/.claude/skills/_shared/scripts/`. The file is `docs/project/inbox.md` (created on the first add).

## add
`python3 inbox.py add <project> --from "<who>" --kind <opinion|change|idea|feedback|bug|question>
--via "<channel>" --text "<their words>"` (or `--source "SRC-<n> T<a>-T<b>"` for turns kept by `/capture`).
It prints the item's number. Several items from one message are separate items, each with its own words.
When input arrives mid-build, add it and keep building: the inbox is weighed at a stop, not in the middle of
a checkpoint, unless the item says the current work is wrong (a defect report on what is being built is
weighed at once).

## review [IN-nnn]
Every open item, oldest first, or the one named. For each:
1. **Read it whole** and say in one line what it asks and the need behind it; the need may be better
   served by another form than the one proposed.
2. **Place it against the record**: the intent (goal, done examples, must-not-lose items, mechanism cards,
   named non-goals), the milestones (which it touches; whether any is accepted), `decisions.md` (an earlier
   ruling on the same thing), `interfaces.md`, and the fix log. Name what it would change.
3. **Settle what it rests on.** A factual, technical, market, or feasibility premise goes through `/scout`
   (graded evidence; the claim verifier for a load-bearing claim). A recommendation never rests on an
   unverified premise without saying so.
4. **Weigh**: what it gives the person the product is for; conflicts with must-not-lose items and non-goals;
   the effect on the milestone being built (scope, evidence made stale, risk); the whole, its parts, and a
   reshaped version that serves the same need.
5. **Recommend** one verdict with what, how, and why, and the strongest alternative:
   ADOPT (all of it), ADOPT-PART (which parts in, which out, each with its reason), RESHAPE (the need is
   real, a different form serves it better; name the form), PLACE M<k> (into that milestone's scope with a
   done example), REJECT (the reason; a capability ruled out for good becomes a named non-goal), or ASK (a
   question only the proposer or owner can answer; the item stays open with `Status: asked: <question>`).
6. **Present** the recommendations to the owner in plain words, exceptions first, one line per item plus
   the reasoning they need, and take their rulings.
7. **Route** each decided part where it belongs:
   - the intent: `/plan amend` (re-freeze entry; milestones and evidence marked STALE);
   - a milestone's scope, done examples, or demo, or a new milestone: `milestones.md` (an accepted
     milestone gets `Superseded: D-<nnn>`);
   - inside the current contract: `state.md` Open, and `interfaces.md` when an interface changes;
   - a defect: `/fix` (fix log), or the current milestone's Open list;
   - a research question: a research note through `/scout`, and an unknown U-nn when it blocks.
8. **Record and clear**: `decisions.py add <project> --title "Inbox IN-<nnn>: <title>" --body "<these four
   lines>" --source-owner "<their words>"` (or `--proposed` for a whole in-contract adoption):

   ```
   Resolves: IN-<nnn> (from <who>, <date>, via <channel>)
   Item: "<the item's words, exactly as in the inbox>"
   Verdict: <ADOPT | ADOPT-PART | RESHAPE | PLACE M<k> | REJECT> · <in / out and why, one line>
   Routed: <file and anchor for each part, e.g. milestones.md M3 (M3.D4); intent.md RF-2>, or none
   ```

   then `inbox.py resolve <project> IN-<nnn> --decision <the D-<nnn> it printed>` and
   `inbox.py check <project>`.

## list
`inbox.py list <project>`: the open items with who sent them and their status.

## Finish
Report in plain words: each item and what happened to it, anything still open and what it waits for, and
what the decisions changed in the current milestone.

## End
`python3 ~/.claude/skills/_shared/scripts/project_status.py record <project> --skill inbox --arg IN-<nnn> --outcome "<one line>"`, then close the report with the Next line it prints (`project-control.md`, End).
