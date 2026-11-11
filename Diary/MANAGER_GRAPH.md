# Diary Manager graph (DFUT-019, version 0.1.12.1)

Choose **Graph** on the existing Diary Manager page, or add `?view=graph` to that
page's URL. The package remembers the presentation for the signed-in user and
manager role. Personal diary presentations remain List, Day, Week and Month.

The graph shows instantiated diary tasks, including diary additions and isolated
tasks, and only the milestones referenced by their date rules. It uses saved diary
data rather than the current template. Task keys always include the diary scope.
Positions follow actual effective due dates; spacing is schematic rather than a
calendar-day scale. Undated items follow dated items. A task-relative date remains
the snapshot fixed when the diary/task was created; late predecessors or subsequent
source-date overrides do not shift it. Completed tasks use their recorded due date.

Task states are Completed, Late, Blocked with a late prerequisite, Blocked, or Ready,
in that priority order. Open tasks due today count as late. Blocked late tasks keep
their blocked label and dashed outline. Ownership and missing-date warnings are
separate. Completed prerequisites never remain active blockers.

Graph uses the existing manager filters, including **Show completed**, which is off
by default. Hidden neighbours are omitted from both the diagram and its payload;
the remaining tasks keep status calculated from the complete diary. No shortcut
edges are invented. Solid arrows show completion prerequisites and dashed arrows
show date sources. When both connect a pair, a solid arrow describes both rules.
Hover or focus an arrow for its description.

Select a task to open the existing task details and actions. After a note or task
change, **Back to calendar** returns to Graph with the same filters and fresh states
for every task. **Refresh** reloads the same manager page and fits the new graph;
zoom/pan are not persisted across page loads. Zoom and background dragging stay
inside the fixed-size panel; focus its background and use `+`, `-`, or `Home` to zoom
or fit. Filters and Legend / Help open dialogs. The expandable task list and inline
filters/help remain usable without JavaScript. Reads and colour changes emit no
signals. Archived diaries keep their existing action restrictions.

## Host integration

An existing integration using `ManagerDiaryView`, the package templates and the
`diary_scripts` block needs **no new URLs, controllers, settings, database migration,
or task action handlers**. Keep the existing host wrapper, permissions, permitted
diary scope, task URL/success hooks and optional `diary_ui.selection_url` POST
selection. Identifier-free trusted scope stays identifier-free. Deploy the updated
package and static assets with the host's normal static-file deployment process.

Hosts embedding fragments explicitly can include
`Diary/partials/manager_graph.html` and load `Diary/scripts/manager_graph.js` once
after it. That script loads the shared `graph_layout.js` helper if needed. Hosts
with custom full manager templates must expose the new package Graph template or
fragment and its script, just as for the existing calendar presentations.

The additive callable API is
`DiaryAPI(actor=actor).diary(key=diary_key).graph(directory=owner_directory, ...)`.
It requires manager edit permission and the same permitted diary scope. Optional
`include_completed`, `exclude_blocked`, and `exclude_non_late` booleans match the
manager filters; `today` optionally supplies a comparison date. It returns diary
metadata, scoped task/milestone nodes and visible-endpoint edges. Supply the normal
owner directory to inspect template person ownership. The host need not call this
API or calculate graph data to use the UI.

## Host CSS colours

Override these properties on `.diary` for shared manager list/calendar/graph colours,
or on `.diary .diary-manager-graph` for graph-only overrides:

| State | Property prefix |
| --- | --- |
| Completed | `--diary-task-completed-` |
| Late | `--diary-task-late-` |
| Blocked with a late prerequisite | `--diary-task-blocked-late-` |
| Blocked | `--diary-task-blocked-` |
| Ready | `--diary-task-ready-` |

Each prefix accepts `background`, `border` (also used for state shadows), and `text`.
Separate warnings use `--diary-task-orphaned-text` and `--diary-task-undated-text`.
For example:

```css
.diary {
    --diary-task-completed-background: #e2f4e8;
    --diary-task-completed-border: #24683d;
    --diary-task-completed-text: #174528;
    --diary-task-late-background: #ffe9e9;
    --diary-task-late-border: #a51e16;
    --diary-task-late-text: #79160f;
}
.diary .diary-manager-graph {
    --diary-task-blocked-background: #f4f1e9;
}
```

The stable container is `.diary-manager-graph`; task groups have
`.diary-graph-task-completed`, `-late`, `-blocked-late`, `-blocked`, or `-ready`, with
`.diary-graph-task-orphaned` and `.diary-graph-task-blocked-pattern` as secondary hooks.
SVG fills, strokes and text use CSS variables; JavaScript assigns no state colours.
**Colour by status** switches task boxes to neutral colours without hiding labels,
blocked patterns or warnings. Its choice applies to the current page only.

Permanent manual layout and subgraph selection remain DFUT-017 and DFUT-016.

Toolbar actions reuse the template navigator CSS contract: set
`--diary-toolbar-icon`, `--diary-toolbar-label`, and `--diary-toolbar-tooltip` on
`.diary-toolbar-add`, `-zoom-in`, `-zoom-out`, `-fit`, `-refresh`, `-filter`, or
`-legend`. Labels appear on hover/focus; accessible names stay in the markup.
