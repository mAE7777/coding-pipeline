# Native UI Validation Protocol (iOS / Android simulator)

Visual, geometric, accessibility and behavioural verification for a **native mobile** UI milestone.
Load when verifying a milestone with native UI; the code-verifier uses these procedures to ground UI
behaviour in a real rendered screen on a simulator or device.

Sibling of `ui-ux-validation-protocol.md`, which covers the web through the browser script and does not
apply here. Where a rule is identical in both, it is stated once, there.

Every simulator run (a UI test suite, a build, a demo step) goes through the machine-wide lock,
`python3 <heavy.py> run -- <command>`, so one simulator runs on the machine at a time.

**Why this file exists.** A native build shipped with its first screen rendering a 92×32 control at
roughly 340×300, occupying a third of the display, while **24 UI tests passed**. Nothing in the suite
asked how big anything was, and the screenshot evidence had been captured piece by piece during the
build and never retaken. Both gaps are closed below.

---

## 1. Geometry: the check behaviour tests structurally cannot make

A behavioural assertion (`exists`, `isHittable`, `label == …`) is satisfied by a control of any size,
in any position, at any degree of overlap. Layout defects are therefore invisible to a green suite.

**Rule: every control the design system assigns a fixed size gets a frame assertion.**

```swift
let control = app.buttons["ES"].frame.union(app.buttons["EN"].frame)
XCTAssertLessThanOrEqual(control.width, 92 + 2, "drifted: \(control.width)")
XCTAssertLessThanOrEqual(control.height, 32 + 2)
XCTAssertGreaterThan(control.width, 30, "collapsed")
```

> **These bounds hold at DEFAULT Dynamic Type only.** At accessibility sizes the control is supposed
> to grow, so a containment bound and the growth assertion in §2 are **mutually unsatisfiable in one
> test**: 92 × 1.3 already exceeds 92 + 2. Put them in two tests with two separate launches. The
> reference implementation does exactly this
> (`testLanguageControlRendersAtItsTokenSizeNotWhateverIsOffered` vs
> `testLanguageControlGrowsWithDynamicTypeInsteadOfTruncating`); a single test trying to hold both
> can never pass, and the natural "fix" is to weaken one of them, which loses the check.

Three things that make these assertions actually hold:

- **Assert containment, not equality.** XCUITest reports an element's **text** frame, not its styled
  container, so an exact-equality assertion fails on a correct build. Bound it instead: not larger
  than the token box, not collapsed to nothing.
- **Add a proportional guard for anything that must stay chrome.** `control.height / screen.height
  < 0.08` catches "this became a hero" in a way an absolute number does not.
- **Assert position when the design states it.** If the spec says a strip sits in the bottom third,
  `XCTAssertGreaterThan(strip.frame.minY, screen.height * 0.6)`.

**Overlap and safe area.** Assert that elements which must not collide do not:
`XCTAssertFalse(a.frame.intersects(b.frame))`, and that interactive content clears the status-bar
region at rest. Note that scrolled content passing under the status bar is normal iOS behaviour;
judge the *scrolled* state deliberately rather than assuming either way.

---

## 2. Dynamic Type: a comparative assertion, not a smoke test

"It launched at AX3" is not a check. A control pinned with a hard `.frame(width:height:)` passes it
while its label truncates to an ellipsis.

**Rule: launch twice and require growth.**

```swift
let small = launch([]);                                        let w1 = control(in: small).width
let big   = launch(["--ui-test-dynamic-type=accessibility3"]); let w2 = control(in: big).width
XCTAssertGreaterThan(w2, w1 * 1.3, "did not scale; the label will truncate")
```

Also assert at accessibility sizes: every control still `isHittable`; nothing overflows
`screen.maxX`; rows that stack instead of overflowing actually stacked. A three-fragment row
(`label · value · action`) laid out as a flat `HStack` is the classic failure: fine at default size,
three unaligned baselines at AX3.

**Launch arguments are the mechanism.** An app that reads `ProcessInfo.processInfo.arguments` in its
`init()` can be put into any state deterministically. If the app under test has no such hooks, that
is itself a finding: untestable states are where defects live.

---

## 3. Evidence freshness: per BUILD, not per milestone

Captures taken earlier in a milestone and never retaken describe a build that no longer exists. In the
motivating case, **every source file was newer than every screenshot**, and the first screen had been
broken for days behind a folder of green-looking evidence.

**Rule: no image in the evidence directory may predate the newest source file.** A capture must
postdate the code it shows.

`gate.sh` checks this at every gate (its `evidence-fresh` check). By hand, as two separate commands:

```bash
ls -t <evidence>
find <src> -name '*.swift' -newer <evidence>/<the last file ls listed, the oldest capture>
```

Any file the second command prints is newer than the oldest capture: the evidence is STALE.

A screenshot older than the code it depicts is not evidence; it is STALE. Re-capture the full set at
the milestone gate, from the candidate build, and look at it.

---

## 4. Verifying a screen whose text comes from a model

Native apps increasingly render on-device model output (Foundation Models, Core ML). Such a behaviour
cannot be verified by asserting its words, and the code-verifier's normal "reproduce a real trace"
standard does not apply to it.

**The rule lives in the code-verifier's own instructions** (its model-backed output check): verify the
**contract**, the **guard**, and the **unavailable path**, never the words; a `HOLDS` needs all three.
It is stated there and not restated here, because that is the copy that decides whether a milestone
passes; a second wording would drift from it.

What this protocol adds is the native specifics: stub the model at the service seam (the app's
`--ui-test-*` launch arguments are the mechanism), and screenshot each degraded state so "renders the
honest state" is judged by looking, not asserted.

**The strongest single test**: with the model stubbed unavailable, the entire pre-existing suite
passes unchanged. That proves the model-backed layer is additive and the deterministic path is intact.

Live-model runs need eligible hardware and may not work in the simulator at all. Quarantine them in
a separate scheme and **name the exclusion out loud** (report it NOT_RUN with the reason): an untested
path that looks tested is worse than an admitted gap.

---

## 4b. Flaky-under-load is a defect, not a re-run

A UI test that **passes in isolation and fails in the full suite** is the most dangerous state a
suite can be in: it is not a failure anyone must fix, so the habit it trains is *re-run until green*,
and that habit is exactly how a real regression gets waved through.

**The usual cause is timeout budgets, not the product.** A long journey test runs materially slower
when the whole suite is contending for one simulator. Real instance: a whole-product journey test
took **67s isolated and 104s under load (+55%)**, and **74 of its 88 wait points had timeouts of
≤3 seconds** (one was 1 second). Any of those can miss on the slow run.

**The fix is free, which is why the tight budget was never worth it.** `waitForExistence` returns
the instant the element appears, so a generous timeout costs nothing on the happy path and only
extends the wall clock when something is genuinely broken. Set it generously (15s) for every
"wait for it to appear".

**The one exception**: a wait inside `XCTAssertFalse(...)` is asserting that something does NOT
appear, so a bigger timeout makes the suite slower for no gain. Check for those before any blanket
raise; if there are none, the raise is safe.

**Diagnosis order** when a test fails in the suite but not alone: (1) time it both ways (a large
gap says load, not logic); (2) count wait points under ~5s; (3) only after those come back clean
should you suspect the product.

---

## 5. Method discipline

**A negative grep is a hypothesis, not a finding.** A type reached only through a wrapper looks
absent when you grep the feature layer for it. In one audit this produced three false findings in a
row. Confirm by running, rendering, or reading the call chain before reporting anything as missing.

**Judge the rendered screen, not the code that should produce it.** Screenshot every state you
assert on and look at it. The tear that "worked" because its end state looked right had, in fact,
never visually happened: caught only by pausing mid-animation.

**Capture motion as frames.** A single screenshot cannot show whether an animation reads as intended.
For any scored motion, capture per-beat frames; a claim about motion with no motion evidence is
reported NOT_RUN (no motion evidence), never guessed.

---

## 6. Screenshot naming and storage

Same convention as the web protocol (`ui-ux-validation-protocol.md` §5):
`{milestone}-{check}-{state}-{description}.png`, stored in the gate round's evidence directory
`.evidence/gate/M<k>/r<n>/`, referenced by relative path. Demo-run captures follow the demo rule
instead: `.demo-captures/<milestone>-<step>.<ext>` inside the demo copy. The one difference on native:
add the device and the Dynamic Type size to the state segment (`iphone17pro-ax3`), because both change
layout materially.
