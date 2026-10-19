# Comment keep-list

Which comments stay in code, and how to judge the rest. Taken from pstack's Comment Sicko agent and its no-comments skill, without the persona. It is part of the review lens.

Scope: the files or diff the caller names. Otherwise the current diff against the base branch, default `main`, including the working tree.

## Comments that stay

Only these stay:

- Legal or license headers.
- Non-obvious behavior forced by an external dependency, platform, vendor, or protocol the project cannot reshape.
- `// prettier-ignore`.
- Lint suppressions whose rule is faulty, pedantic, or style-only.
- Doc comments that define a public API contract.
- Issue or RFC links that explain a constraint the code cannot express.

When it is unclear whether a keep applies, the comment goes. Everything else goes too: narration, banners, commented-out code, and justifications for workarounds.

## Surprises in the project's own code

A comment that explains a surprise in the project's own code goes. Flag the exact symbol `MUST KILL` for a rename, an extraction, a type, or a redesign that makes the behavior obvious without prose. Do not restore such a comment.

## Suppressions

`eslint-disable`, `@ts-ignore`, `@ts-expect-error`, and similar suppressions are suspect. Look up the rule. If it catches real bugs or protects correctness or safety, the suppression goes and the exact symbol it protects is flagged `MUST KILL`.

## Claimed constraints

`IMPORTANT`, `do not remove`, `too risky`, `fine for now`, and long justifications are a signal, not proof. Read the nearby code first. If the claim is not obvious there, trace the named symbol or call (`../explore/explorer-prompt.md`, `../explore/code-archaeology.md`). A keep survives only when it is about something the project cannot change and is proven true today on a live path. A long justification without that proof goes, and is never shortened into a smaller excuse.

A constraint comment such as `do not remove`, `do not change wording`, or `talk to X before changing`, about something the project can change, gets an offer: the cheapest in-scope type, runtime check, test, or lint that enforces it. Once that exists, the comment goes. Without it, the comment goes and the constraint is reported open.

## Report

Every flag names code inside the scope and is true. Invent nothing. The review deletes comments and names refactor targets. It never writes application code. Report the files touched, the deletion count, each `MUST KILL` flag with one line, and the skips.
