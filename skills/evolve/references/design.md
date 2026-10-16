# Designing a pipeline change

Loaded by `/evolve run` at the Design step. The pipeline's form of pstack's correct (the fix hierarchy and the
rule table), reflect (when a text change is worth making), and eval (blinding a probe).

## Fix at the highest level that works
Assume the next session sees only the files it opened, copies the nearest example, and takes the shortest
path that works. Try these in order, and say in the change record why a higher level did not work:
1. **Structure.** One owner for each piece of state and one supported way to do each task; delete the old way
   an agent would copy.
2. **A script or hook refuses the bad state**, and its message names what to do instead (a `gate.sh` check, a
   lint, a guard hook, a runner check).
3. **A test of the behavior.** Fix or delete a test that still passes when the behavior it checks breaks.
4. **Skill or agent text, last**, only for a judgment call nothing can check.
The reproduction is the proof that the new check fails on the real past mistake.

## The rule table
`docs/rule-ledger.md` pairs every rule with what enforces it. A change that adds, moves, enforces, or drops a
rule changes its row in the same commit. A rule the ledger already holds, that nothing enforces, and that
failed again is a repeat: fix it at the highest level that works, in this change. A rule whose mistake can no
longer happen is proposed to the owner for removal; the owner decides every deletion.

## When a text change is worth making
Change skill, agent, or reference text only when the change is:
- **durable**: still true once paths, versions, and code shapes have moved;
- **specific**: a later session recognizes when it applies (no platitudes, no one-off facts);
- **decision-changing**: a session does something different because of it, not just reads more;
- **structural first**: if a script, lint, hook, or runtime check could enforce it, that is the change;
- **not already covered**: when the text already says it clearly, the problem is execution, not the text; when
  it is buried or easy to skip, reword or move it rather than add a second copy.

## Blinding a probe or fixture that measures model behavior
- Nothing the model under test sees (folder, file, slug, or prompt) says it is being measured: no eval,
  judge, experiment, rubric, score, benchmark, candidate, arena, planted, or fixture. Names are ones a user
  might pick.
- The prompt reads as an ordinary request: the goal, never what is measured.
- Nothing asks it to list the rules or files it applied; grade that from its output and its transcript, never
  from its own account.
- It is never told that other candidates exist.
- A judge may know it is judging, but sees outputs by neutral label, never by model name. Comparing two
  variants, one judge scores both sets in one pass, on one scale, blind to which set is which.
- Read every output yourself and compare it with the judge's verdict; a disagreement means a biased judge or
  an ambiguous rubric.
