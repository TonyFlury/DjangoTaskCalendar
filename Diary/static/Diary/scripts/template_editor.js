/* Enhance the server editor without changing its validation or save permissions. */
(() => {
    'use strict';

    /** Return one task control by its documented field class. */
    function field(task, name) {
        return task.querySelector(`.diary-template-field-${name}`);
    }

    /** Keep semantic visibility and the class styling interface in agreement. */
    function show(element, visible) {
        element.hidden = !visible;
        element.classList.toggle('diary-template-hidden', !visible);
    }

    /** Create an entry UUID without requiring the randomUUID secure-context method. */
    function entryKey() {
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        bytes[6] = (bytes[6] & 15) | 64;
        bytes[8] = (bytes[8] & 63) | 128;
        const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
        return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    }

    /**
     * Initialize each editor fragment independently of host document structure.
     * DV1-025: Template authoring controls.
     * DV1-017: Immediate ownership group warnings.
     */
    function initialize(editor) {
        const form = editor.querySelector('.diary-template-form');
        const list = editor.querySelector('.diary-template-task-list');
        const prototype = editor.querySelector('.diary-template-empty-task');
        const total = form.querySelector('[name="tasks-TOTAL_FORMS"]');
        const message = editor.querySelector('.diary-template-live-message');
        const emptyRoles = new Set(JSON.parse(editor.querySelector('[id="diary-template-empty-roles"]').textContent));
        const milestones = JSON.parse(editor.querySelector('[id="diary-template-milestones"]').textContent);
        const taskLimit = Number(editor.dataset.taskLimit);
        show(editor.querySelector('.diary-template-refresh-milestones'), false);

        /** Return task rows from this editor, including rows marked for deletion. */
        function tasks() {
            return Array.from(list.querySelectorAll('.diary-template-task'));
        }

        /**
         * Refresh rule panels and safe predecessor choices from all proposed task edits.
         * DV1-027: Exclude this task and its successors using the proposed graph.
         * DV1-017: Show the selected ownership group warning.
         */
        function refresh() {
            const rows = tasks();
            const active = rows.filter(task => !field(task, 'delete').checked);
            const successors = new Map();
            for (const task of active) {
                const key = field(task, 'entry-key').value;
                for (const option of field(task, 'predecessors').selectedOptions) {
                    const values = successors.get(option.value) || new Set();
                    values.add(key);
                    successors.set(option.value, values);
                }
            }
            for (const task of rows) {
                const deleted = field(task, 'delete').checked;
                const kind = field(task, 'date-kind').value;
                const milestoneSelect = field(task, 'milestone-name');
                const previousMilestone = milestoneSelect.value;
                const declared = new Set(Array.from(form.querySelectorAll('[name="milestone_names"]:checked'), control => control.value));
                const availableMilestones = milestones.filter(milestone => declared.has(milestone.name));
                const expectedValues = ['', ...availableMilestones.map(milestone => milestone.name)];
                const currentValues = Array.from(milestoneSelect.options, option => option.value);
                // Keep the active option in place during its own change event.
                if (JSON.stringify(currentValues) !== JSON.stringify(expectedValues)) {
                    milestoneSelect.replaceChildren(new Option('Select a milestone', ''));
                    for (const milestone of availableMilestones) {
                        milestoneSelect.add(new Option(milestone.label, milestone.name, false, previousMilestone === milestone.name));
                    }
                }
                const owner = field(task, 'owner-kind').value;
                task.classList.toggle('diary-template-task-deleted', deleted);
                show(task.querySelector('.diary-template-task-fields'), !deleted);
                for (const control of task.querySelector('.diary-template-task-fields').querySelectorAll('input, select, textarea')) {
                    control.disabled = deleted;
                }
                task.querySelector('.diary-template-remove').textContent = 'Remove task';

                // Keep a restoration action available until the manager saves the new version.
                if (deleted) {
                    task.querySelector('.diary-template-remove').textContent = 'Restore task';
                }
                task.querySelector('.diary-template-task-title').textContent = field(task, 'name').value || 'New task';
                show(task.querySelector('.diary-template-milestone-fields'), kind === 'source' || kind === 'relative');
                show(task.querySelector('.diary-template-relative-fields'), kind === 'relative');
                show(task.querySelector('.diary-template-annual-fields'), kind === 'annual');
                show(task.querySelector('.diary-template-person-fields'), owner === 'person');
                show(task.querySelector('.diary-template-role-fields'), owner === 'role');
                const warning = task.querySelector('.diary-template-owner-warning');
                warning.textContent = '';

                // Warn immediately when the manager selects a group with no current members.
                if (!deleted && owner === 'role' && emptyRoles.has(field(task, 'role-ref').value)) {
                    warning.textContent = `No role members — ${field(task, 'role-ref').value}.`;
                }
                const excluded = new Set();
                const pending = [field(task, 'entry-key').value];

                // Every successor would create a cycle if selected as a predecessor.
                while (pending.length) {
                    const key = pending.pop();

                    // Visit shared descendants once so a large dependency graph remains bounded.
                    if (!excluded.has(key)) {
                        excluded.add(key);
                        pending.push(...(successors.get(key) || []));
                    }
                }
                const select = field(task, 'predecessors');
                const selected = new Set(Array.from(select.selectedOptions, option => option.value));
                const search = task.querySelector('.diary-template-predecessor-search').value.trim().toLocaleLowerCase();
                select.replaceChildren();
                for (const candidate of active) {
                    const key = field(candidate, 'entry-key').value;
                    const name = field(candidate, 'name').value.trim();

                    // Search retains selected tasks and always excludes this task and its successors.
                    if (name && !excluded.has(key) && (selected.has(key) || name.toLocaleLowerCase().includes(search))) {
                        select.add(new Option(name, key, false, selected.has(key)));
                    }
                }
            }
        }

        /** Enable removal controls while retaining the server checkbox fallback. */
        function prepare(task) {
            show(task.querySelector('.diary-template-remove'), true);
            show(task.querySelector('.diary-template-delete-field'), false);
            show(task.querySelector('.diary-template-predecessor-filter'), true);
        }

        for (const task of tasks()) {
            prepare(task);
        }
        form.addEventListener('click', event => {
            const remove = event.target.closest('.diary-template-remove');

            // Removal updates the proposed version only and is reversible before Save.
            if (remove) {
                const task = remove.closest('.diary-template-task');
                const checkbox = field(task, 'delete');
                checkbox.checked = !checkbox.checked;
                refresh();
                message.textContent = 'Task selection changed. Save template to apply the new version.';
            }
        });
        form.addEventListener('change', refresh);
        form.addEventListener('input', event => {

            // Task names and search text update choices while retaining selected predecessors.
            if (event.target.classList.contains('diary-template-field-name')
                || event.target.classList.contains('diary-template-predecessor-search')) {
                refresh();
            }
        });
        editor.querySelector('.diary-template-add').addEventListener('click', event => {
            event.preventDefault();
            const index = Number(total.value);

            // Match the server editor limit without allocating an unbounded number of controls.
            if (index >= taskLimit) {
                message.textContent = `The configured request limit permits ${taskLimit} task rows.`;
                return;
            }
            const content = prototype.innerHTML.replaceAll('__prefix__', String(index));
            const holder = document.createElement('template');
            holder.innerHTML = content;
            const task = holder.content.querySelector('.diary-template-task');
            field(task, 'entry-key').value = entryKey();
            list.append(holder.content);
            total.value = String(index + 1);
            prepare(task);
            refresh();
            field(task, 'name').focus();
            message.textContent = 'New task added. Save template to apply the new version.';
        });
        refresh();
    }

    for (const editor of document.querySelectorAll('.diary-template-editor')) {
        initialize(editor);
    }
})();
