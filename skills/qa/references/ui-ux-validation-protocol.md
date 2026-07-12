# UI/UX Validation Protocol

Visual, accessibility, behavioral, and responsive testing via Playwright MCP tools. Load when verifying a slice that has UI; the code-verifier uses these procedures to ground UI behavior in real rendered screens. "Phase" below means the slice under test.

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

For EACH page/route introduced or modified in the target phase, at EACH viewport:

1. `browser_navigate` to the page URL
2. `browser_resize` to the viewport dimensions
3. `browser_snapshot` to capture the accessibility tree (primary verification)
4. `browser_take_screenshot` with descriptive filename for evidence

### What to Verify at Each Viewport

**Mobile (375px):**
- No horizontal scrollbar (content fits within viewport width)
- Touch targets are at least 44x44px
- Text is readable without zooming (minimum 16px body text)
- Navigation is accessible (hamburger menu works if applicable)
- Images and media scale down without overflow
- Forms are usable — inputs are full-width or appropriately sized

**Tablet (768px):**
- Layout adjusts from mobile (if responsive breakpoint exists)
- Sidebar and main content balanced (if applicable)
- Grid layouts have appropriate column count
- No awkward spacing between elements

**Desktop (1280px):**
- Full layout displayed as designed
- Appropriate max-width constraints (content doesn't stretch infinitely)
- Hover states work on interactive elements
- Multi-column layouts render correctly

**Wide (1920px):**
- Content centered or appropriately constrained (no 1920px-wide paragraphs)
- No visual stretching or distortion
- Sidebar widths reasonable
- Background/decorative elements fill space gracefully

### Visual Consistency Checks

Compare against conventions from key-learnings:
- Color palette matches established conventions
- Typography matches established fonts and sizes
- Spacing matches established patterns (padding, margin, gap)
- Component styling matches established component library patterns

---

## Section 2: Accessibility Audit Protocol

### Accessibility Tree Verification

Use `browser_snapshot` to capture the full accessibility tree. Verify:

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

### Keyboard Navigation Audit

Simulate keyboard-only navigation:

1. `browser_press_key` with "Tab" repeatedly to navigate through all interactive elements
2. After each Tab, `browser_snapshot` to verify:
   - Focus is visible (focus indicator/outline present)
   - Focus order is logical (follows visual layout, not DOM order if different)
   - No focus traps (Tab always moves forward, Shift+Tab backward)
3. For modals/dialogs:
   - Focus trapped inside when open (Tab cycles within modal)
   - Escape key closes the modal
   - Focus returns to trigger element after close
4. For dropdown menus:
   - Arrow keys navigate options
   - Enter/Space selects
   - Escape closes

### Color Contrast Checks

Use `browser_evaluate` to check contrast ratios:

```javascript
// Example: Check computed styles for text contrast
() => {
  const elements = document.querySelectorAll('p, span, a, button, label, h1, h2, h3, h4, h5, h6');
  const results = [];
  elements.forEach(el => {
    const styles = window.getComputedStyle(el);
    results.push({
      text: el.textContent?.substring(0, 30),
      color: styles.color,
      backgroundColor: styles.backgroundColor,
      fontSize: styles.fontSize
    });
  });
  return results;
}
```

WCAG AA Requirements:
- Normal text (< 18pt / < 14pt bold): 4.5:1 contrast ratio
- Large text (>= 18pt / >= 14pt bold): 3:1 contrast ratio
- UI components and graphical objects: 3:1 contrast ratio

### Focus Indicator Verification

Verify focus indicators meet WCAG requirements:
- Focus indicator is visible on all interactive elements
- Focus indicator has sufficient contrast (3:1 against adjacent colors)
- Focus indicator is not solely color-based (outline, border, or underline visible)

---

## Section 3: Behavioral Testing Protocol

### User Journey Simulation

For each user journey from the test plan:

1. Start at the entry point: `browser_navigate` to the starting URL
2. For each step in the journey:
   - Execute the action: `browser_click`, `browser_type`, `browser_press_key`, or `browser_fill_form`
   - Wait for the expected result: `browser_snapshot` to verify UI state
   - If expected state not present, record as failure with evidence
3. After journey completes, verify final state

### Form Testing Protocol

For EVERY form in the target phase:

**Valid Submission:**
1. Fill all required fields with valid data via `browser_fill_form`
2. Submit the form
3. Verify success state (redirect, success message, data persisted)

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
2. Immediately submit again before the first submission completes
3. Verify no duplicate submissions or errors

### Interactive Element Testing

For every interactive element (buttons, links, toggles, tabs, accordions):

1. Click/activate the element
2. Verify the expected state change via `browser_snapshot`
3. Test rapid repeated interaction (double-click, rapid toggles)
4. Test interaction during loading states (if applicable)

---

## Section 4: Console and Network Monitoring

### Console Message Protocol

Before starting interactive tests:
1. `browser_console_messages` with level `"error"` — capture baseline errors

During each user journey:
1. After the journey completes, `browser_console_messages` with level `"warning"`
2. Compare against baseline — identify NEW errors and warnings

Classification:
- **P0**: Any console error during normal user flows
- **P1**: Console errors only during edge case testing
- **P2**: Console warnings (deprecation, non-critical)
- **P3**: Informational console messages

### Network Request Protocol

During each user journey:
1. `browser_network_requests` with `includeStatic: false`
2. Flag:
   - **Failed requests** (4xx, 5xx status): P0 if during happy path, P1 otherwise
   - **Requests to unexpected domains**: P0 (potential data leak)
   - **Sensitive data in URLs**: P0 (passwords, tokens in query strings)
   - **Excessive requests**: P2 (more than expected for the action)
   - **Missing HTTPS**: P1 for any non-localhost request over HTTP

---

## Section 5: Screenshot Evidence Protocol

### Naming Convention

```
qa-{phase}-{test-id}-{viewport}-{description}.png
```

Examples:
- `qa-01-E03-375-homepage-mobile-layout.png`
- `qa-01-B07-1280-form-validation-error.png`
- `qa-01-C01-768-user-journey-step3-tablet.png`

### When to Capture Screenshots

- **Every visual finding**: Layout issue, overflow, misalignment
- **Every viewport check**: One screenshot per page per viewport
- **Every failure**: The state at the moment of failure
- **Before and after interactions**: Show state change for behavioral tests
- **Accessibility issues**: Focus indicators, contrast problems

### Screenshot Storage

Store screenshots alongside the qa report:

```
qa-reports/
├── qa-report-phase-01.md
└── screenshots/
    ├── qa-01-E01-375-homepage-mobile.png
    ├── qa-01-E01-768-homepage-tablet.png
    └── ...
```

Use relative paths in the qa report to reference screenshots.
