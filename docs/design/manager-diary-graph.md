# Diary Manager graph and task-state colours

Date: 11 November 2026.

Status: Implemented DFUT-019 in version **0.12.1**.
This design record describes the intended behaviour. See the
[Manager graph guide](../../Diary/MANAGER_GRAPH.md) for delivered controls,
CSS properties and host integration. Refresh uses a full page reload and fits
the graph; colour mode and zoom/pan are retained only within the current page.

## Purpose and entry point

Extend the existing template navigator to show the **actual tasks in a selected
diary**, including their current completion, due dates, blocking and ownership state.
Managers should be able to see where work is stuck and open the affected task
without examining a long task list.

Add **Graph** to the package-owned presentation selector on the existing manager
page: List / Day / Week / Month / Graph. The host keeps its current manager URL,
wrapper, permitted-diary policy and task-navigation hooks. No graph-specific host
view or URL is required. Remember Graph using the existing per-user/session manager
presentation preference. Personal mode does not acquire a graph or manager access.

The template graph continues to describe reusable rules. The manager graph shows
a particular diary copy, including diary-only additions and recorded completion.
Opening a manager graph must never instantiate or modify a template or diary.

## Shared task-state presentation

Use the same server-computed status and palette in the graph, manager list, and
Day/Week/Month task cards. The current list/calendar status rules remain authoritative.
Colour is a presentation of those rules, not another status calculation.

| Condition | Proposed graph/calendar styling | Visible wording |
| --- | --- | --- |
| Completed | Pale green background, dark green border and check mark. | Completed |
| Open and late, including blocked late tasks | Red border/shadow, pale red background. | Late, plus Blocked when applicable. Due-today tasks also say Due today. |
| Open, blocked, not itself late, with a late direct predecessor | Amber border/shadow and dashed outline. | Blocked · late prerequisite |
| Open and blocked | Dashed outline and neutral/pale amber background. | Blocked |
| Open and ready | Neutral background with the normal host accent. | Ready |

Evaluate conditions in the order above. Completion takes precedence over current
lateness; do not turn a completed task red because its recorded due date is in the
past. Lateness takes colour precedence over blocking, but retain the Blocked text
and dashed-outline cue when both apply.

Retain the existing rule that an open task is late when due **on or before** the
diary-local Today. Do not introduce a different overdue definition for the graph.
This design does not add a historical late-at-completion metric.

Additional conditions are badges, not competing primary colours:

- **Owner needs review** for orphaned template tasks. Do not change readiness merely
  because ownership is unresolved; retain the existing recovery rules.
- **Date not set** for tasks without a calculable date. An undated task can still
  be Ready or Blocked; never invent a date or label it late.
- **Diary addition** where it helps distinguish tasks that came from the template.

Provide a compact legend and full status wording on task nodes. The proposed
default is Colour by status enabled. An optional switch removes status fills while
retaining labels, icons and outline styles. Colour must never be the only way to
recognise a condition. Do not colour every day cell by the worst task: individual
tasks keep their own states and dates remain readable.

## Graph content and relationships

Use boxes for tasks and diamonds for referenced diary milestones. Include copied
template tasks, diary-only tasks, and disconnected tasks. Include a shared milestone
once when at least one displayed task uses it as a date source. Show its actual
diary date, or Date not set. Milestones have no task completion state and retain
neutral milestone styling.

Show solid completion-prerequisite arrows and dashed date-source arrows, with
signed offsets in their accessible descriptions. When both relationships connect
the same pair, draw the solid relationship once and expose both meanings in its
description. Preserve the underlying date relation for inspection and layout.
Completed prerequisite connections remain meaningful historical relationships;
they are not active blockers and must not receive a blocking warning style.

The manager graph uses the diary's saved relationships, not the latest template
version. A later template edit must not silently change an existing diary's graph.
Live dependency editing and task deletion remain governed by their existing policies.

## Dates and layout

Reuse crossing reduction, connected components, zoom, pan and fit from the template
navigator. Actual effective due dates guide the relative placement of live tasks.
Use recorded completion due dates for completed tasks. Positions are schematic,
not a calendar-day scale; the dated Day/Week/Month presentations provide that scale.
Put undated components in an explicitly labelled area rather than assigning Today.

Stored date-source offsets explain provenance, but are not always current layout
equations. In particular, a task-relative date is fixed at initialization and can
diverge from a source task's current due date after an explicit source override.
Show the saved offset and fixed/resolved date in relationship details without
moving the dependent task to make the equation appear true again. An explicit
override of the dependent task also takes precedence for its displayed due date.

A late or completed source must not automatically move its successors. Where actual
dates and completion dependencies disagree, retain backward-pointing completion
arrows and explain them; do not rearrange dates to hide the disagreement.

Stable identity is `(diary_key, entry_key)` for task nodes and
`(diary_key, milestone_name)` for milestone nodes. A reused template task UUID
alone must not identify a saved selection, DOM node, or graph update across diaries.

## Filters and graph context

Reuse the manager page's existing filters unchanged. In particular, completed
tasks remain hidden until Show completed is selected. The green completion colour
applies when those tasks are included; selecting Graph does not change that filter.
Hide blocked and late-only choices retain their current meanings.

Calculate status from the full authorised diary graph **before** applying display
filters. A prerequisite excluded by a display filter can still block a displayed
task. Filtered counts and the graph's visible task count must agree with the list
for the same manager filters. Graph covers the selected diary, not an accidental
date window inherited from the previous Week/Month presentation.

Initially show only matching nodes and relationships whose endpoints are displayed.
Do not connect around omitted nodes or invent a direct dependency between their
visible neighbours. A task may say that prerequisite context is outside the
current view without exposing omitted names, UUIDs, dates or counts.

A future optional Show connection context mode could add authorised, dimmed
nonmatching neighbours. It must be explicitly separate from matching results and
must not bypass privacy. This is not required for initial delivery.

## Toolbar, inspection and actions

Keep the graph as the main content area. The package toolbar contains zoom out,
zoom in, Fit, Refresh, Colour by status, shared Filters, Legend/Help, and any
currently permitted Add task action. Reuse host-configurable icons, labels and
tooltips. Zoom changes graph contents without changing panel size or losing either
scrollable edge. Put detailed guidance and the legend in popups.

Task nodes show name, effective due date, state and useful owner information.
Long names remain fully available through accessible labels and task inspection.
Selecting a task opens the existing task details and permitted operations: notes,
completion, date override, ownership recovery and Close all as already supported.
It must not open the template task editor or expose template-edit controls.

Use existing host POST-selection hooks for identifier-free navigation. Keep a
signed return link to the manager page with Graph selected and the same filters.
After a successful write, return to fresh server state; completion of a predecessor
can change several successors' states, so do not just recolour the clicked node.
During an in-page refresh retain zoom/pan and selected task where possible. If a
task disappears under the active filters, announce that rather than selecting a
different task accidentally. Display errors without claiming an unsuccessful write
completed. No new task signal is emitted for reading, filtering or recolouring.

An archived diary graph remains available for inspection. Keep existing restrictions
on date changes and completion; allow notes only where the current API allows them.

## API and implementation approach

Extract a reusable renderer/layout module from the template editor's graph code.
Separate graph layout/rendering from the template form adapter: manager nodes
come from diary records, not hidden editable template forms. Both consumers use
the same basic shapes, route conventions, interaction controls and host style hooks.
Keep template editing and diary task actions in their respective adapters.

Proposed read contract: a scoped `DiaryInstance.graph(...)` or equivalent shared
graph service that returns:

- Selected diary identity, name, archived state and local Today.
- Visible task nodes with both identity keys, names, effective dates, state labels,
  completion flags, ownership warnings, revisions and permitted detail navigation.
- Referenced diary milestone nodes and their current dates.
- Completion/date-source edges with scoped endpoints, saved offset/provenance,
  active-blocking meaning and accessible relationship descriptions.
- Matching counts and the state/legend metadata necessary for rendering.

Reuse the shared diary task-status helpers and current permission/visibility
rules. Batch-load visible source provenance, dependencies, milestones and owner
labels; do not issue `task()`/notes queries separately for every node. Any optional
JSON response must be scoped and private/no-store like the existing diary data
views. The host should not calculate states or supply graph layout data.

The browser must receive only authorised nodes and edges. Hiding a private SVG
node is insufficient if its identifier or text remains in the payload or tooltip.
Check scope again after a current-event change or permission change. Session
preferences may remember Graph and colour mode; they do not authorise a diary.
Do not keep task data in persistent browser storage.

Initial implementation should need no task-data migration. Permanent layout
positions are outside this delivery unless DFUT-017 is implemented separately.

## Host styling

Expose semantic classes such as `diary-graph-task-completed`,
`diary-graph-task-late`, `diary-graph-task-blocked`,
`diary-graph-task-blocked-late`, `diary-graph-task-ready`, and
`diary-graph-task-orphaned`. Use shared task-state palette properties for the
manager list, dated calendar cards and graph nodes; retain existing Diary CSS
hooks and provide compatible fallbacks.

**Requirement:** all graph state colours must be overridable from the host's CSS
alone. No JavaScript changes, template overrides or package edits should be needed
to adapt the palette. Server and JavaScript code select semantic states/classes;
they must not assign literal state colours or inline styles that defeat host CSS.

Define the following shared CSS custom-property contract. For each state
`completed`, `late`, `blocked-late`, `blocked`, and `ready`, expose:

- `--diary-task-<state>-background` for the node/card background.
- `--diary-task-<state>-border` for the outline and state shadow.
- `--diary-task-<state>-text` for the label colour.

Also expose `--diary-task-orphaned-text` and `--diary-task-undated-text` for the
secondary warnings. Provide package defaults through `var(...)` fallbacks at
the point of use so a host can set these properties on the `.diary` root or an
individual graph. The default palette above is illustrative, not a fixed scheme.

For SVG nodes, map background to `fill`, border to `stroke` and any status shadow,
and text to the actual label element's fill. For HTML calendar/list cards, use the
same properties for background, border/shadow and text respectively. Avoid SVG
presentation attributes or descendant colour declarations that bypass the properties.

For example, a host stylesheet loaded after Diary's styles can apply its own scheme:

```css
.diary {
    --diary-task-completed-background: #e6f2ff;
    --diary-task-completed-border: #245b91;
    --diary-task-completed-text: #153858;
    --diary-task-late-background: #fff0e5;
    --diary-task-late-border: #9a4100;
    --diary-task-late-text: #662b00;
}

/* A graph-only override can leave the host's other task views unchanged. */
.diary .diary-manager-graph {
    --diary-task-blocked-background: #f0ebff;
    --diary-task-blocked-border: #60418f;
    --diary-task-blocked-text: #392653;
}
```

Use `diary-manager-graph` as the stable graph container hook. Hosts can adapt colour
and contrast without changing state precedence, visible status wording, outline
patterns or permissions. Do not remove the non-colour cues when overriding colours.

Keyboard users can tab to tasks and use Enter to inspect them. Provide zoom/fit
controls outside the SVG, visible focus, Escape to close dialogs, full node names,
and an equivalent manager List presentation without JavaScript. Status labels and
outline patterns must remain useful in monochrome and host high-contrast themes.

## Delivery and verification

1. Extract shared graph layout/rendering without changing template graph behaviour.
2. Add the scoped live diary graph projection and verify task/date/status identity.
3. Add manager-only Graph presentation and the shared task-state palette.
4. Integrate existing filters, task actions, return navigation, accessible controls
   and help. Document host CSS hooks and verify the host needs no new routes.

Acceptance coverage includes:

- Each status and combination, including due today, blocked-and-late, late direct
  prerequisite, completed tasks with past due dates, orphaned and undated tasks.
- Completion changing successor readiness; shared/group completion; notes on
  archived diaries; stale writes and permission changes during navigation.
- Filters matching the manager list; hidden prerequisite context; payload privacy;
  duplicate task UUIDs in separate diaries and scoped milestone identities.
- Diary-only and disconnected tasks; completed prerequisite edges; milestone/date
  links, zero/negative offsets, overrides and fixed task-relative snapshots.
- Unchanged template graph editing, crossing reduction, zoom/pan containment,
  keyboard/touch interaction, no-JavaScript List fallback, and host CSS overrides.
- A host-only stylesheet changes every state's node fill, outline/shadow and label
  colour, including secondary warnings, without JavaScript/template changes.
  Verify both shared `.diary` overrides and graph-only overrides, and confirm SVG
  labels and HTML cards use the configured colours rather than package literals.
- Busy graph response size and query counts that do not grow per rendered node.

## Related requirements

- [DFUT-019 in the feature backlog](../../TODO.md#diary-feature-backlog).
- DFUT-016: future subgraph selection should also apply to live diary graphs,
  preserving permissions and displayed status. It is not assumed implemented here.
- DFUT-017: future manual layout positions need separate template/diary scope and
  reset rules. Moving a box must never reschedule a task.
- DFUT-015: forward-impact review remains separate from displaying current states.
- [Calendar presentation design](weekly-monthly-task-views.md) and
  [host integration](../../Diary/CALENDAR_VIEWS.md).
