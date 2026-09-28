# UI/UX Validation Protocol

Visual, accessibility, behavioral, and responsive testing with the gate's browser script. Load when verifying a milestone that has UI; the code-verifier uses these procedures to ground UI behavior in real rendered screens.

**The browser script.** Inside the gate, every browser step below is one call:

```
python3 <browse.py> --root <copy> <url> [--viewport WxH] [--load-state <file.json>] [steps...]
```

`<browse.py>` is the script's path and `<copy>` is the checker's copy of the project; both come with the checker's instructions. Steps run in the order given: `--wait <ms>`, `--wait-for <selector>`, `--click <selector>`, `--fill <selector>=<text>`, `--press <key>`, `--select <selector>=<value>`, `--check <selector>`, `--goto <url>`, `--eval <js expression>`, `--screenshot <file.png>`, `--text <file.txt>`, `--html <file.html>`, `--snapshot <file.yml>` (the accessibility tree), and `--save-state <file.json>`. Five rules shape every procedure here:

- Each call starts a fresh headless browser. Anything that must carry across steps (focus, an open menu, a half-filled form) happens inside one call; a login carries between calls with `--save-state` and `--load-state`.
- Only localhost URLs and files inside the copy open. Every other request the page makes is aborted and listed as blocked.
- Each call prints one JSON line: blocked requests, console errors and warnings, page errors, eval results, and the files written. Output paths are relative to the copy. `--requests <file.json>` writes every request made so far with its status.
- `--fill` and `--select` split their argument at the first `=`, so the selector must not contain `=`; use an id or another selector without one.
- The script takes the machine-wide heavy-job lock itself, so one browser runs on the machine at a time. Start the product under the same lock, in the background: `python3 <heavy.py> serve -- <run command>`.

---

## Section 1: Visual Verification Protocol

### Viewport Definitions

| Name | Width | Height | Represents |
|------|-------|--------|------------|
| Mobile | 375 | 667 | iPhone SE / small phones |
| Tablet | 768 | 1024 | iPad / tablets |
| Desktop | 1280 | 720 | Standard laptop |
| Wide | 1920 | 1080 | Full HD monitor |

### Per-Viewport Test Procedure

For EACH page/route introduced or modified in the milestone, at EACH viewport, make one call (the viewport is fixed when the browser starts, so each viewport is its own call):

1. The page URL with `--viewport` set to the row's dimensions (`--viewport 375x667`, `--viewport 768x1024`, `--viewport 1280x720`, `--viewport 1920x1080`)
2. `--snapshot <file.yml>` to capture the accessibility tree (primary verification)
3. `--screenshot <file.png>` with a descriptive filename for evidence (the capture is full-page)
4. `--eval` for the measurable checks below; results come back in the JSON line

```
python3 <browse.py> --root <copy> http://localhost:3000/ --viewport 375x667 \
  --snapshot .evidence/gate/M1/r1/M1-D1-375-homepage.yml \
  --eval "document.documentElement.scrollWidth <= window.innerWidth" \
  --screenshot .evidence/gate/M1/r1/M1-D1-375-homepage.png
```

### What to Verify at Each Viewport

**Mobile (375px):**
- No horizontal scrollbar (content fits within viewport width; `document.documentElement.scrollWidth <= window.innerWidth` is true)
- Touch targets are at least 44x44px (measure with `getBoundingClientRect()` in an `--eval`)
- Text is readable without zooming (minimum 16px body text)
- Navigation is accessible (hamburger menu works if applicable: `--click` it, then `--snapshot`)
- Images and media scale down without overflow
- Forms are usable: inputs are full-width or appropriately sized

**Tablet (768px):**
- Layout adjusts from mobile (if responsive breakpoint exists)
- Sidebar and main content balanced (if applicable)
- Grid layouts have appropriate column count
- No awkward spacing between elements

**Desktop (1280px):**
- Full layout displayed as designed
- Appropriate max-width constraints (content doesn't stretch infinitely)
- Hover states work on interactive elements (`--hover <selector>` then `--screenshot`; also confirm nothing is reachable only by hovering)
- Multi-column layouts render correctly

**Wide (1920px):**
- Content centered or appropriately constrained (no 1920px-wide paragraphs)
- No visual stretching or distortion
- Sidebar widths reasonable
- Background/decorative elements fill space gracefully

### Visual Consistency Checks

Compare against the conventions recorded in `docs/project/decisions.md`:
- Color palette matches established conventions
- Typography matches established fonts and sizes
- Spacing matches established patterns (padding, margin, gap)
- Component styling matches established component library patterns

---

## Section 2: Accessibility Audit Protocol

### Accessibility Tree Verification

Use `--snapshot <file.yml>` to capture the full accessibility tree (roles, accessible names, heading levels, landmarks). Verify:

**Interactive Elements:**
- Every button has an accessible name (not empty, not just an icon)
- Every link has descriptive text (not "click here" or "read more" without context)
- Every form input has a label (via `<label>`, `aria-label`, or `aria-labelledby`)
- Every image has alt text (empty `alt=""` is acceptable for decorative images)

**Document Structure:**
- Heading hierarchy is logical: h1 → h2 → h3 (no skipping h2 to go to h3)
- Only one h1 per page
- Landmarks present: main, nav, footer (as appropriate)
- Lists use proper list markup (`<ul>`, `<ol>`, `<li>`)

**Dynamic Content:**
- Live regions (`aria-live`) for content that updates without page load
- Loading indicators announced to screen readers
- Error messages associated with their form fields (`aria-describedby`)
- Modal dialogs have proper role and focus management

Markup the snapshot does not show directly (`aria-live`, `aria-describedby`, list elements) is read with `--html <file.html>` or an `--eval` query such as `document.querySelectorAll('[aria-live]').length`.

If the project already bundles axe-core and the page exposes it, add an automated pass: `--eval "axe.run().then(r => r.violations.map(v => v.id + ': ' + v.nodes.length))"`. Otherwise, reason from the snapshot; the check does not add axe-core to the project.

### Keyboard Navigation Audit

Simulate keyboard-only navigation. Focus does not survive between calls, so each sequence below is one call:

1. `--press Tab` repeatedly to move through all interactive elements, and after each press record where focus landed: `--eval "document.activeElement.outerHTML.substring(0, 120)"`, plus `--screenshot` wherever the indicator must be seen
2. From that record, verify:
   - Focus is visible (focus indicator/outline present; `getComputedStyle(document.activeElement).outlineStyle` alongside the screenshot)
   - Focus order is logical (follows visual layout, not DOM order if different)
   - No focus traps (Tab always moves forward, `--press Shift+Tab` backward)
3. For modals/dialogs (opened with `--click` in the same call):
   - Focus trapped inside when open (Tab cycles within modal; `document.querySelector('[role=dialog]').contains(document.activeElement)` stays true)
   - `--press Escape` closes the modal
   - Focus returns to trigger element after close
4. For dropdown menus:
   - Arrow keys navigate options (`--press ArrowDown`, `--press ArrowUp`)
   - Enter/Space selects
   - Escape closes

### Color Contrast Checks

Use `--eval` to read computed styles; the result comes back in the JSON line:

```javascript
// Example: check computed styles for text contrast (passed as one --eval argument)
[...document.querySelectorAll('p, span, a, button, label, h1, h2, h3, h4, h5, h6')].map(el => {
  const styles = window.getComputedStyle(el);
  return {
    text: el.textContent?.substring(0, 30),
    color: styles.color,
    backgroundColor: styles.backgroundColor,
    fontSize: styles.fontSize
  };
})
```

WCAG AA Requirements:
- Normal text (< 18pt / < 14pt bold): 4.5:1 contrast ratio
- Large text (>= 18pt / >= 14pt bold): 3:1 contrast ratio
- UI components and graphical objects: 3:1 contrast ratio

### Focus Indicator Verification

Verify focus indicators meet WCAG requirements (from the keyboard audit's screenshots and evals):
- Focus indicator is visible on all interactive elements
- Focus indicator has sufficient contrast (3:1 against adjacent colors)
- Focus indicator is not solely color-based (outline, border, or underline visible)

---

## Section 3: Behavioral Testing Protocol

### User Journey Simulation

For each user journey the milestone describes (its done examples and its demo ending), make one call:

1. Start at the entry point: the call's URL is the starting URL
2. For each step in the journey:
   - Execute the action: `--click`, `--fill`, `--press`, `--select`, or `--check`
   - Wait for the expected result with `--wait-for <selector>`, then `--snapshot` to verify UI state
   - If expected state not present, record FAILS with evidence (the snapshot, a screenshot, and the JSON line; a `--wait-for` that times out ends the call with the error in that line)
3. After journey completes, verify final state

A journey behind a login: log in once and end that call with `--save-state <file.json>`, then start each later call with `--load-state <file.json>`.

### Form Testing Protocol

For EVERY form in the milestone:

**Valid Submission:**
1. Fill all required fields with valid data (one `--fill` per field)
2. Submit the form (`--click` the submit control)
3. Verify success state (redirect, success message, data persisted: reload with `--goto` or read the stored record)

**Empty Submission:**
1. Submit without filling any fields
2. Verify validation errors appear for required fields
3. Verify error messages are descriptive (not just "Required")

**Invalid Data:**
1. Fill fields with invalid data (bad email, too-short password, etc.)
2. Submit the form
3. Verify field-specific validation errors

**Maximum Length:**
1. Fill text fields to their maximum length
2. Verify content is not truncated unexpectedly
3. Test one character beyond max if applicable

**Special Characters:**
1. Input unicode, emoji, HTML tags, SQL fragments
2. Verify they're displayed correctly (escaped, not executed)
3. Verify they don't break the layout

**Double Submit:**
1. Submit the form
2. Immediately submit again before the first submission completes (two `--click` steps on the submit control with no wait between)
3. Verify no duplicate submissions or errors. If the second click times out because the control disabled itself, the JSON line reports the timeout: that is the guard working. Count the stored records either way.

### Interactive Element Testing

For every interactive element (buttons, links, toggles, tabs, accordions):

1. Click/activate the element (`--click`, `--press`, or `--check`)
2. Verify the expected state change via `--snapshot`
3. Test rapid repeated interaction (double-click, rapid toggles: repeated `--click` steps in one call)
4. Test interaction during loading states (if applicable)

---

## Section 4: Console and Network Monitoring

### Console Message Protocol

Every call's JSON line lists the console errors and uncaught page errors raised during that call.

Before starting interactive tests:
1. Load each page with no steps and record its errors: this is the baseline

During each user journey:
1. After the journey call, read its errors (and its warnings, below)
2. Compare against baseline: identify NEW errors and warnings

The JSON line carries both errors (`console_errors`, `page_errors`) and warnings (`console_warnings`), including those raised while the page first loads.

Classification:
- **P0**: Any console error during normal user flows
- **P1**: Console errors only during edge case testing
- **P2**: Console warnings (deprecation, non-critical)
- **P3**: Informational console messages

### Network Request Protocol

During each user journey, read two sources:
1. The JSON line's blocked requests: every request the page tried to send anywhere other than localhost or the copy (the script aborted each one)
2. The request log, written as the journey's last step with `--requests requests.json`: every request with its method, status (or `failed` with the error), and resource type.

Flag:
- **Failed requests** (4xx, 5xx status): P0 if during happy path, P1 otherwise
- **Requests to unexpected domains**: P0 (potential data leak). Every blocked request is one of these unless the milestone contract names that host; even an expected host was blocked, so the behavior that depends on it is NOT_RUN in the browser, never passed.
- **Sensitive data in URLs**: P0 (passwords, tokens in query strings; check blocked and listed URLs alike)
- **Excessive requests**: P2 (more than expected for the action)
- **Missing HTTPS**: P1 for any non-localhost request over HTTP (it appears in the blocked list with its scheme)

---

## Section 5: Screenshot Evidence Protocol

### Naming Convention

```
{milestone}-{check}-{viewport}-{description}.png
```

`{check}` is the done example, must-not-lose item, or finding the capture supports.

Examples:
- `M1-D1-375-homepage-mobile-layout.png` (done example M1.D1)
- `M1-F07-1280-form-validation-error.png` (finding F07)
- `M1-L01-768-saved-items-tablet.png` (must-not-lose item L-01)

Demo-run captures follow their own rule: `.demo-captures/<milestone>-<step>.<ext>` inside the demo copy (for example `M1-3.png`).

### When to Capture Screenshots

- **Every visual finding**: Layout issue, overflow, misalignment
- **Every viewport check**: One screenshot per page per viewport
- **Every failure**: The state at the moment of failure
- **Before and after interactions**: Show state change for behavioral tests
- **Accessibility issues**: Focus indicators, contrast problems

A capture must postdate the code it shows. One taken before the latest change is STALE: retake it, never cite it.

### Screenshot Storage

Store captures in the gate round's evidence directory:

```
.evidence/gate/M1/r1/
├── M1-D1-375-homepage-mobile.png
├── M1-D1-768-homepage-tablet.png
└── ...
```

The milestone's review, `docs/project/reviews/M<k>.md`, names this directory; reference captures by relative path.
