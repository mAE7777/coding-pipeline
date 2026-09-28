# Interface baseline

The floor under every user interface, whatever its style: nothing on screen is there without a reason,
nothing looks abstract or cluttered at first sight, and nothing the user should not have to know is shown
to them. The final look can be minimal, rich, or anything a project's design intent names; this baseline
holds under all of them. The builder meets it before the freeze; the gate's reviewer checks it (the clarity
pass at the end).

## The one boundary: hidden from the user, never hidden from the record

Keeping internals off the screen never means swallowing them. Internal detail the user does not need
(identifiers, hashes, timings, protocols, addresses and ports, versions, internal state names) goes to logs
and diagnostics, where the owner and the developer can see it. And every failure with a consequence for the
user is shown obviously: at the place it happened, in plain words, saying what happened and what to do next,
never styled so it could pass for success or be missed as a faint note. Partial results say they are
partial. There is no silent degradation, no silent fallback, and no dropped failure; a fallback exists only
as a designed, labeled behavior the user can see.

## Principles

1. **Every element answers one question:** does the user need it right now to decide or to act? Needed:
   keep it. Needed now and then: tuck it away (a "⋯" menu, a settings drawer, shown on click). Not needed:
   remove it. Repeating something else: merge it.
2. **Show results, not mechanics.** The screen says what happened; how it happened goes to the logs, and
   surfaces only when something goes wrong and the user needs it to act.
3. **Quiet on success, clear on failure.** When all is well, no explanatory text. When something fails, the
   boundary above: obvious, plain, at the spot, once, with the next step.
4. **Organize the way the user thinks,** not the way the data is stored: one entry per thing the user
   recognizes, variants (versions, models, sizes) in a dropdown, groups in a fixed, meaningful order.
5. **One primary action per screen:** the only filled button; everything else is a text button. A whole row
   selects when clicked; rarely used actions go into "⋯".
6. **Moving is not deleting.** Management goes to settings, rare actions to "⋯"; a function is removed only
   when the main flow already covers it, and when unsure, the owner is asked. An action that deletes or
   cannot be undone asks first, saying plainly what will be lost.
7. **Words:** short and plain, in the product's languages; no internal code names, abbreviations, or
   technical terms; a number appears only when the user acts on it ("3 left today").
8. **Show only what belongs here:** nothing the user cannot use or that is managed elsewhere. An empty state
   is clean: no empty title bars or dividers, one quiet line saying what to do.
9. **One look across the product:** the same colors, type sizes, buttons, and grouping on every page. Few
   colors; red is reserved for problems.

## The minimal style (the default for tools, panels, and dashboards)

Used when the project's design intent names no other style. A product with its own look names it in its
design intent (high-stakes design through /taste-design or /atelier); the principles above still hold.

- Layout: a narrow sidebar (about 240 px) of things to choose, grouped under small gray group names; the
  work area on the right with the current item's name, its choices (dropdowns), and a "⋯" on top, content in
  the middle, input at the bottom. On narrow screens the sidebar stacks on top.
- List row: a 7 px status dot (green: works; gray: offline or off; red: a problem) and the name; a problem
  adds one plain line under it saying what is wrong and what to do.
- Conversation: the user's words right-aligned in a light gray rounded bubble; replies left-aligned without
  a box; actions such as copy appear on hover; a status line only while unfinished or when something failed.
- Input: Enter sends, Shift+Enter adds a line, and Enter during IME composition never sends. Attachments are a
  gray text button; chosen files are small removable tags.
- Settings drawer: slides in from the right over a translucent dark layer; closes on the outside or Close;
  one small heading per section; a section with nothing in it is not shown; a small red dot on "Settings"
  when something inside needs attention.
- Colors, all as variables; appearance follows the owner's standing default (dark unless the project says
  otherwise, or the system setting when the project says so):
  - light: background #fafaf9, panel #ffffff, text #1b1b1b, secondary text #8b8b8b, lines #ebebea, hover
    #f2f2f1, green #2f9e5e, amber #b7791f, red #d0382f;
  - dark: background #131313, panel #191919, text #ececec, secondary text #8a8a8a, lines #262626, hover
    #202020, green #4cc27e, amber #e0a54a, red #ff6b61.
- Type: the system font (-apple-system, PingFang SC); body 14 px with line height 1.6; small text 12 px
  gray; headings bold, not larger.
- Buttons: text buttons without border or fill, gray, darker with a light fill on hover; the primary button
  dark and filled with light text; disabled ones faded.
- Inputs and dropdowns: 1 px light border, 8 px radius; focus darkens the border, never the browser's blue
  ring.

## The clarity pass (the builder before the freeze; the reviewer in the gate)

1. Open it in a real browser and look, with screenshots: empty, with content, and with each menu and drawer
   open, at the viewports the validation protocol names.
2. Put every element through principle 1; list repeated words, text that repeats on every row, explanations
   that stay on screen when all is well, and colors beyond the few the look defines.
3. Look for display errors: a literal null, undefined, NaN, or [object Object]; empty title bars; misaligned
   headings; clicks that do nothing (after the data has loaded).
4. Make each failure happen that the product can meet (offline, signed out, a quota spent, a timeout,
   mismatched content, an unknown outcome, a feature that cannot be used right now) and confirm it is shown
   obviously, in plain words, with the next step, and that its detail reached the log.
5. Check the browser console for errors.
6. Report what was removed, tucked away, and merged, and ask about anything that might be a function the
   owner wants; never delete it on your own.

In the gate, the reviewer reports clarity-pass findings with class `clarity` (internal detail on screen is
usually medium, clutter low), except these, which are defects of their own class: a failure hidden, missed as
a faint note, or dressed as success, or its detail missing from the log (`silent-degradation`); a display
error or a click that does nothing (`correctness`); a secret or credential on screen (`security`).
