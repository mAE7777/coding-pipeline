# Campaign mode

Loaded by `/dev` when the owner authorizes a run of several milestones ("build M1 through M3") without
waiting for acceptance between them. The authorization is a decision entry in the owner's own words
(proven with `rulings.py record`) and the `## Campaign` line in `state.md` (`M1-M3 · D-<nnn>`).

What changes:
- `/dev` and the gate chain: after a milestone's gate comes back ACCEPT-READY, the next milestone starts;
  after CHANGES, the fix loop runs and the gate runs again; a finding still blocking after two fix rounds goes
  to the owner (BLOCKED), since repeating the same fix a third time is not a new method. BLOCKED and
  INCONCLUSIVE after its re-run still stop the campaign with a Blockers row.
- Acceptance is batched at the end, exception first: every milestone's gate summary, what failed and was
  fixed, what was skipped, what needs a ruling, and how to see each demo.
- The handoff note is refreshed at every stop by the continuity hook, so any fresh session, in either tool,
  can take over mid-campaign.
- The named stops still apply: a stand-in, a material intent fork, a contract change, an irreversible or
  credentialed action, a blocker only the owner can clear.

The standing instruction below is quoted from Anthropic's "Prompting Claude Opus 5.5" guide and applies for
the whole campaign:

> A standing instruction from the user, the person you are working for. It is about how your turns end. A
> message with no tool call in it ends your turn, and the work stops there until you are asked to continue.
> The user has seen you end turns in four ways while work they asked for was still owed, and does not want
> any of them. One: a long summary of what was done that closes by announcing the next step and has no tool
> call, so the next thing never starts. Two: an offer to carry on with something unless the user would
> prefer otherwise, which stops to wait for an answer the user was not going to give. Three: a list of
> decisions for the user when, by your own account, none of them blocks the rest of the work. Four:
> deciding that this is a good place to report, because the turn has been long or a milestone is done.
> Status notes are welcome, and so are your recommendations on open decisions, but put them in the same
> message as your next tool call and carry on with whatever does not depend on the user's answer. If you
> notice yourself inviting the user to redirect you or offering to wait, delete it and do the next thing.
> The stops the user does want are the ones where nothing can move without them, or where the thing
> blocking you is deliberately protected from you. This does not override the need for confirmation on
> risky or destructive actions.
