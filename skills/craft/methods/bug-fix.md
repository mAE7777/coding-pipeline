### Bug fix

**You own this task. Plan, review, verify.** Delegate investigation and the fix to subagents, stay in the lead. Brief each subagent per `../brief.md`, on its role's model in `_shared/models.json`.

Be scientific. Every shipped line traces to runtime evidence. Belt-and-suspenders that "might help" is a hypothesis, not a fix. It does not ship. When evidence refutes a hypothesis, revert what it motivated. The smallest change the evidence justifies ships, nothing more.

1. Reproduce it yourself on the matching surface via `playwright-cli` for web or the project's verification skill under `docs/project/verify/`, even when a debug or instrumentation protocol says to ask the user to reproduce. Ask the user only with a stated, specific reason the control surface cannot reach the target, and only after driving it as far as it goes. If it won't reproduce directly, synthesize the trigger, tighten conditions, or instrument until it fires. For a UI or timing bug, the exact discriminating symptom must appear twice through real UI interaction, with the state reset between the two attempts, and step 4 verifies the fix the same way.
2. Binary-search the cause. Form the candidate hypotheses, then rule them out until one survives. Seed them with `how` over the affected subsystem and the **why** skill for regression history. Each pass, take the split that cuts the most remaining problem space, get runtime evidence, eliminate. When program state is unclear, add instrumentation or logging and read it as the code runs. Don't guess. Drive a long or stubborn hunt with Claude Code's `/loop` command. Confirm the surviving *mechanism* with runtime evidence before the step-3 architect/interrogate fan-out.
3. Plan the fix. If it crosses a function boundary, `architect` first. Delegate implementation to a subagent on its role's model in `_shared/models.json` with a specific scope.
4. Verify on the same surface. The original repro now passes. "Inconclusive" or wrong-surface is not a pass. Flag it. Unit tests show branch behavior, not bug absence.
5. Stage the commits so the failing repro lands before the fix in git history. The reproduction becomes a regression test, always. Choose the narrowest executable check already used for that code path. Write the test first. It encodes intended behavior, not the current implementation. Run it before the fix and confirm it fails for the intended reason. If it passes or fails for an unrelated reason, correct the test or the reproduction before you edit the implementation. Keep it focused on the bug, and never change a test to match a wrong implementation.
   This is the canonical **sequence-verifiable-units** principle skill, the failing test first and the fix on top.
6. Hand back per the active skill (`/fix` logs the fix and names the next step). When the fix goes out as a pull request, run **Opening a PR**.

**Reply:** what was broken, root cause, fix, how you verified. Paste failing-then-passing repro output verbatim.
