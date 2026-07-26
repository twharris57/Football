# Web & UI Guidelines

Applies to any web project regardless of framework (React, Blazor, Vue, etc.).

## Input Controls

### Optional inputs need explicit clear buttons

When a field is optional, users need a reliable way to remove an entered value. Do not
rely on browser-native "none" states (unreliable on mobile, especially iOS Safari date
and time pickers) or placeholder text that disappears on input.

Provide an explicit `×` (clear) button. When a date and a dependent time field are
paired, one button clears both — no separate time-only clear needed.

**The clear button is the last element in its container row.** Conditionally rendering a
button mid-row shifts sibling elements when a value appears or disappears, which is
disorienting and can trigger horizontal scroll on narrow viewports.

## Constraints and Validation

**Enforce model constraints at every UI entry point** — not just at the save/submit path.
If the data model has a hard limit, guard it at:
- The toggle or mode selector that would violate it
- The selection list or add affordance that would exceed it
- The final save path

A gap in any entry point is a UX defect even when the underlying data is ultimately safe.

## Abbreviations and Domain Terminology

**Explain domain abbreviations on first use.** Write the full term with the abbreviation
in parentheses: "As Needed (PRN)", "Three times daily (TID)". In space-constrained
contexts, abbreviations are acceptable only when accompanied by a tooltip (`title`
attribute or equivalent) containing the full phrase.

The primary audience of any UI may include non-experts. Abbreviations without explanation
are a UX defect, not a style preference.

## Edit Forms and Destructive Actions

**Prefer placing delete inside the edit form** — consolidates create/edit/delete into one
affordance rather than splitting delete to the list row.

Escape condition: a row-level delete is acceptable when the edit form is a sub-panel that
replaces the list while open. In that layout, the form and the list row are never
simultaneously visible, so the race condition (deleting while the item's form is open)
cannot occur. Apply scrutiny — ask whether the condition the rule protects against
actually exists in the specific layout before overriding.

## Filtering and Summary Counts

**Filter counts must derive from the filtered collection, not the unfiltered one.**
When a view displays "X of Y complete", Y must reflect the currently filtered set.
Compute the filter first, then derive both the visible list and the summary counts from
the same result. A count that doesn't match the visible items breaks user trust.

## Accessibility

- Minimum WCAG 2.1 AA compliance.
- Touch targets: 44×44 px minimum (WCAG 2.5.5).
- High contrast text — verify with a contrast checker, don't eyeball it.
- All interactive elements keyboard accessible.
- Aria labels on icon-only buttons and form fields without visible labels.
- Never lose data silently — all destructive actions require confirmation.
