# Dashboard Diary count mock-up

Open [index.html](index.html) in a browser.
No server, database, or application integration is necessary.

The preview uses the existing dashboard stylesheet and chart renderer.
The event figures and comparison curves are sample data.
The surrounding page is a simplified version of the team page shell.

Saved images show the [desktop layout](previews/desktop.png) and the [phone layout](previews/mobile.png).

## Diary panel

**My Diary** uses a compact row with three clickable counts for the selected user:

- **Late** counts incomplete tasks whose due date is today or earlier.
- **Ready** counts tasks that are not late and have no unfinished predecessors.
- **Blocked** counts tasks that are not late and have unfinished predecessors.

A task contributes to one count only.
Late has priority, including when the task also has unfinished predecessors.
The three counts together give the number of open tasks owned by this user or their roles.
Completed tasks and whole-team tasks are excluded.
The owner must be the user or a role that includes the user.

The panel does not show a task list.
Each count opens **My tasks** in the Diary preview with the same exclusive status filter.
The link keeps the selected preview user.
The **Open Diary** link opens the personal list with its normal open-task filter.

## Review steps

1. Select Jess Morgan in **Preview user**.
2. Select the **Late** count.
3. Check that the Diary shows Jess's late tasks.
4. Open **Confirm sponsor list**.
5. Complete that sample task.
6. Return to the dashboard preview.
7. Check that the late count decreases and the blocked count decreases.
8. Select **Ready** to inspect the task that the completed predecessor enabled.

Select Sam Patel to inspect a user with no late tasks.
A zero count still opens the corresponding empty task list.

Clear **Diary enabled** to hide the complete panel and its sidebar link.
The existing dashboard charts remain available.
The checkbox simulates an optional installed app.
It does not change Django settings.

## Shared sample state

The preview and the Diary UI use `../ui/sample-state.js`.
They use the same sample tasks and browser session storage.
The preview date is 12 June 2027.
Use **Reset sample** in the Diary UI to restore the original tasks.

Links use `previewAs` and `taskStatus` query parameters for this mock-up only.
These parameters are not authentication or production access controls.
No route, API, database, or deployed dashboard was changed.

## Styling

The preview loads the production dashboard stylesheet and the Diary stylesheet.
Its own `preview.css` adds the sample page shell and the count panel.
The panel uses named `diary-dashboard-` classes within `.diary`.
The surrounding shell uses `dashboard-preview-` classes.
The [Diary styling guide](../../README.md#dashboard-count-mock-up) lists the new panel classes.

The production chart renderer supplies its own existing markup and styles.
This mock-up does not change that renderer or its stylesheet.

## Browser checks

Chrome checks cover the count links, personal ownership, role membership, completion updates, empty results, and the disabled Diary state.
They also cover chart controls and desktop and phone widths.
The checked paths reported no browser script errors.
