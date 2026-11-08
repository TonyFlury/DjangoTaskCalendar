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

    /** Read-only graph of the proposed form state; all mutations still use the task forms. */
    function taskGraph(editor) {
        const panel = editor.querySelector('.diary-template-graph');
        if (!panel) return () => {}; // Older host template overrides can keep their existing forms.
        const viewport = panel.querySelector('.diary-graph-viewport');
        const svg = panel.querySelector('svg');
        const status = panel.querySelector('.diary-graph-status');
        const zoom = panel.querySelector('.diary-graph-zoom');
        const markerId = `diary-graph-arrow-${entryKey()}`;
        let width = 1, height = 1, scale = 1, fitting = true, pending = 0, latest = [];
        const ns = 'http://www.w3.org/2000/svg';

        function element(tag, attributes = {}, text = null) {
            const node = document.createElementNS(ns, tag);
            for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
            if (text !== null) node.textContent = text;
            return node;
        }

        function resize() {
            if (fitting) {
                const maxHeight = parseFloat(getComputedStyle(viewport).maxHeight) || height;
                scale = Math.min(1, Math.max(1, viewport.clientWidth - 8) / width, (maxHeight - 8) / height);
            }
            svg.setAttribute('width', String(Math.ceil(width * scale)));
            svg.setAttribute('height', String(Math.ceil(height * scale)));
            zoom.value = `${Math.round(scale * 100)}%`;
            panel.querySelector('[data-graph-action="in"]').disabled = scale >= 2;
            panel.querySelector('[data-graph-action="out"]').disabled = scale <= .1;
        }

        function changeZoom(action) {
            fitting = action === 'fit';
            if (!fitting) scale = Math.max(.1, Math.min(2, scale * (action === 'in' ? 1.25 : .8)));
            resize();
            if (fitting) viewport.scrollTo(0, 0);
        }

        panel.querySelector('.diary-graph-toolbar').addEventListener('click', event => {
            const button = event.target.closest('[data-graph-action]');
            if (button) changeZoom(button.dataset.graphAction);
        });
        viewport.addEventListener('keydown', event => {
            if (event.target !== viewport) return;
            const action = {'+': 'in', '=': 'in', '-': 'out', 'Home': 'fit'}[event.key];
            if (action) { event.preventDefault(); changeZoom(action); }
        });
        let drag = null;
        viewport.addEventListener('pointerdown', event => {
            if (event.pointerType !== 'mouse' || event.button !== 0 || event.target.closest('.diary-graph-node')) return;
            drag = {x: event.clientX, y: event.clientY, left: viewport.scrollLeft, top: viewport.scrollTop};
            viewport.setPointerCapture(event.pointerId);
            viewport.classList.add('diary-graph-dragging');
        });
        viewport.addEventListener('pointermove', event => {
            if (!drag) return;
            viewport.scrollLeft = drag.left + drag.x - event.clientX;
            viewport.scrollTop = drag.top + drag.y - event.clientY;
        });
        function stopDragging() { drag = null; viewport.classList.remove('diary-graph-dragging'); }
        viewport.addEventListener('pointerup', stopDragging);
        viewport.addEventListener('pointercancel', stopDragging);
        viewport.addEventListener('lostpointercapture', stopDragging);
        if (window.ResizeObserver) new ResizeObserver(resize).observe(viewport);
        else window.addEventListener('resize', resize);

        function draw() {
            pending = 0;
            const nodes = latest.map((row, index) => ({
                row, index, key: field(row, 'entry-key').value,
                name: field(row, 'name').value.trim() || `Unnamed task ${index + 1}`,
                predecessors: Array.from(field(row, 'predecessors').selectedOptions, option => option.value),
                level: 0, outgoing: [], remaining: 0,
            }));
            const byKey = new Map(nodes.map(node => [node.key, node]));
            const links = [];
            let invalid = byKey.size !== nodes.length;
            for (const node of nodes) {
                for (const key of node.predecessors) {
                    const predecessor = byKey.get(key);
                    if (!predecessor) { invalid = true; continue; }
                    predecessor.outgoing.push(node);
                    node.remaining++;
                    links.push([predecessor, node]);
                }
            }
            // Kahn's traversal gives dependencies earlier rows and cannot loop on invalid input.
            const ready = nodes.filter(node => node.remaining === 0);
            for (let i = 0; i < ready.length; i++) {
                for (const next of ready[i].outgoing) {
                    next.level = Math.max(next.level, ready[i].level + 1);
                    if (--next.remaining === 0) ready.push(next);
                }
            }
            const cyclic = ready.length !== nodes.length;
            const layers = [];
            // Keep malformed graphs visible in a simple row instead of implying a valid ordering.
            for (const node of nodes) {
                const level = cyclic ? 0 : node.level;
                (layers[level] ||= []).push(node);
            }
            width = Math.max(320, ...layers.map(layer => layer.length * 248 + 32));
            height = Math.max(130, layers.length * 166 + 32);
            svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
            svg.replaceChildren();
            const defs = element('defs');
            const marker = element('marker', {id: markerId, viewBox: '0 0 10 10', refX: 9,
                refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse'});
            marker.append(element('path', {d: 'M 0 0 L 10 5 L 0 10 z', class: 'diary-graph-arrow'}));
            defs.append(marker);
            svg.append(defs);
            for (const [level, layer] of layers.entries()) {
                const offset = (width - layer.length * 248) / 2;
                layer.forEach((node, index) => { node.x = offset + index * 248 + 12; node.y = 24 + level * 166; });
            }
            for (const [from, to] of links) {
                const x1 = from.x + 108, y1 = from.y + 82, x2 = to.x + 108, y2 = to.y - 4;
                const middle = (y1 + y2) / 2;
                const path = element('path', {class: 'diary-graph-edge',
                    d: `M ${x1} ${y1} C ${x1} ${middle} ${x2} ${middle} ${x2} ${y2}`,
                    'marker-end': `url(#${markerId})`});
                path.append(element('title', {}, `${from.name} → ${to.name}`));
                svg.append(path);
            }
            for (const node of nodes) {
                const input = field(node.row, 'name');
                const link = element('a', {href: `#${input.id}`, class: 'diary-graph-node',
                    'data-task-key': node.key, 'aria-label': `Edit task: ${node.name}`});
                link.append(element('title', {}, node.name));
                link.append(element('rect', {x: node.x, y: node.y, width: 216, height: 82, rx: 10}));
                const label = element('text', {x: node.x + 14, y: node.y + 25});
                // Wrap labels without inserting task text as HTML. Full names remain in the accessible label.
                const parts = node.name.match(/.{1,25}(?:\s|$)|.{1,25}/gu) || [node.name];
                parts.slice(0, 3).forEach((part, index) => {
                    const text = index === 2 && parts.length > 3 ? `${part.trim().slice(0, 23)}…` : part.trim();
                    label.append(element('tspan', {x: node.x + 14, dy: index ? 20 : 0}, text));
                });
                link.append(label);
                link.addEventListener('click', event => {
                    event.preventDefault();
                    node.row.scrollIntoView({block: 'center'});
                    input.focus({preventScroll: true});
                });
                svg.append(link);
            }
            const summary = nodes.length ? `${nodes.length} tasks · ${links.length} connections.` : 'No tasks yet. Add a task below to start the graph.';
            status.textContent = summary + (cyclic || invalid ? ' Check task keys and predecessor selections; this preview is not a valid dependency order.' : '');
            viewport.hidden = !nodes.length;
            resize();
        }

        panel.hidden = false;
        return rows => {
            latest = rows;
            if (!pending) pending = requestAnimationFrame(draw);
        };
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
        const updateGraph = taskGraph(editor);

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
                const availableMilestones = milestones;
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
                show(task.querySelector('.diary-template-relative-fields'), kind === 'relative' || kind === 'task');
                show(task.querySelector('.diary-template-task-date-fields'), kind === 'task');
                const sourceSelect = field(task, 'source-task-key');
                const sourceValue = sourceSelect.value;
                const dateChoices = [{value: '', label: 'Select a source task', selected: !sourceValue},
                    ...active.filter(candidate => candidate !== task).map(candidate => {
                        const key = field(candidate, 'entry-key').value;
                        return {value: key, label: field(candidate, 'name').value.trim() || 'Unnamed task',
                                selected: key === sourceValue};
                    })];
                const currentDateChoices = Array.from(sourceSelect.options, option => ({
                    value: option.value, label: option.text, selected: option.selected,
                }));
                if (JSON.stringify(currentDateChoices) !== JSON.stringify(dateChoices)) {
                    sourceSelect.replaceChildren(...dateChoices.map(option => new Option(option.label, option.value, false, option.selected)));
                }
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
                const choices = [];
                for (const candidate of active) {
                    const key = field(candidate, 'entry-key').value;
                    const name = field(candidate, 'name').value.trim();

                    // Search retains selected tasks and always excludes this task and its successors.
                    if ((name || selected.has(key)) && !excluded.has(key)
                        && (selected.has(key) || name.toLocaleLowerCase().includes(search))) {
                        choices.push({value: key, label: name || 'Unnamed task', selected: selected.has(key)});
                    }
                }
                const current = Array.from(select.options, option => ({
                    value: option.value, label: option.text, selected: option.selected,
                }));
                // Leave unchanged native options in place, especially during focus/selection events.
                if (JSON.stringify(current) !== JSON.stringify(choices)) {
                    select.replaceChildren(...choices.map(option => new Option(option.label, option.value, false, option.selected)));
                }
            }
            updateGraph(active);
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
