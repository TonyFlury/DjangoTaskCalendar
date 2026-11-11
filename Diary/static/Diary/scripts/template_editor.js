/* Enhance the server editor without changing its validation or save permissions. */
(async () => {
    'use strict';
    if (!window.DiaryGraph) await import(new URL('graph_layout.js', document.currentScript.src));
    const {arrangeGraph, positionGraphDates} = window.DiaryGraph;

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

    /** Match the server's source-first, connected-subgraph choice order, including unsaved rows. */
    function orderedTaskChoices(rows, dateSources = false) {
        if (dateSources) rows = orderedTaskChoices(rows);
        const keys = rows.map(row => field(row, 'entry-key').value);
        const byKey = new Map(keys.map((key, index) => [key, rows[index]]));
        if (byKey.size !== rows.length) return rows;
        const incoming = new Map(), outgoing = new Map(keys.map(key => [key, []]));
        const neighbors = new Map(keys.map(key => [key, new Set()]));
        rows.forEach((row, index) => {
            const references = dateSources
                ? (field(row, 'date-kind').value === 'task' ? [field(row, 'source-task-key').value] : [])
                : Array.from(field(row, 'predecessors').selectedOptions, option => option.value);
            const sources = new Set(references.filter(key => byKey.has(key)));
            incoming.set(keys[index], sources);
            for (const source of sources) {
                outgoing.get(source).push(keys[index]);
                neighbors.get(source).add(keys[index]);
                neighbors.get(keys[index]).add(source);
            }
        });
        const seen = new Set(), result = [];
        for (const key of keys) {
            if (seen.has(key)) continue;
            const component = new Set([key]), pending = [key];
            while (pending.length) {
                for (const neighbor of neighbors.get(pending.pop())) {
                    if (!component.has(neighbor)) { component.add(neighbor); pending.push(neighbor); }
                }
            }
            const members = keys.filter(candidate => component.has(candidate));
            const remaining = new Map(members.map(candidate => [candidate, incoming.get(candidate).size]));
            const ready = members.filter(candidate => remaining.get(candidate) === 0);
            for (let index = 0; index < ready.length; index++) {
                const current = ready[index];
                seen.add(current);
                result.push(byKey.get(current));
                for (const next of outgoing.get(current)) {
                    remaining.set(next, remaining.get(next) - 1);
                    if (remaining.get(next) === 0) ready.push(next);
                }
            }
            // Invalid proposed date cycles must remain selectable and be reported on Save.
            for (const current of members) {
                if (!seen.has(current)) { seen.add(current); result.push(byKey.get(current)); }
            }
        }
        return result;
    }

    /** Read-only graph of the proposed form state; all mutations still use the task forms. */
    function taskGraph(editor, milestones) {
        const panel = editor.querySelector('.diary-template-graph');
        if (!panel) return () => {}; // Older host template overrides can keep their existing forms.
        const viewport = panel.querySelector('.diary-graph-viewport');
        const svg = panel.querySelector('svg');
        const status = panel.querySelector('.diary-graph-status');
        const toolbar = editor.querySelector('.diary-graph-toolbar');
        show(toolbar.querySelector('.diary-graph-zoom-controls'), true);
        const markerId = `diary-graph-arrow-${entryKey()}`;
        const milestoneLabels = new Map(milestones.map(milestone => [milestone.name, milestone.label]));
        let width = 1, height = 1, pending = 0, latest = [];
        const ns = 'http://www.w3.org/2000/svg';

        function element(tag, attributes = {}, text = null) {
            const node = document.createElementNS(ns, tag);
            for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
            if (text !== null) node.textContent = text;
            return node;
        }

        const navigation = window.DiaryGraph.createViewport(viewport, svg, toolbar);

        function draw() {
            pending = 0;
            const taskNodes = latest.map((row, index) => ({
                row, index, key: field(row, 'entry-key').value,
                name: field(row, 'name').value.trim() || `Unnamed task ${index + 1}`,
                predecessors: Array.from(field(row, 'predecessors').selectedOptions, option => option.value),
                level: 0, outgoing: [], remaining: 0,
            }));
            const nodes = taskNodes.slice();
            const byKey = new Map(taskNodes.map(node => [node.key, node]));
            const milestoneNodes = new Map();
            const links = [];
            const dateLinks = [];
            let invalid = byKey.size !== nodes.length;
            for (const node of taskNodes) {
                for (const key of node.predecessors) {
                    const predecessor = byKey.get(key);
                    if (!predecessor) { invalid = true; continue; }
                    predecessor.outgoing.push(node);
                    node.remaining++;
                    links.push([predecessor, node, 'dependency']);
                }
                const kind = field(node.row, 'date-kind').value;
                const milestoneName = field(node.row, 'milestone-name').value;
                if ((kind === 'source' || kind === 'relative') && milestoneName) {
                    if (!milestoneLabels.has(milestoneName)) { invalid = true; continue; }
                    if (!milestoneNodes.has(milestoneName)) {
                        const milestone = {key: `milestone:${milestoneName}`, name: milestoneLabels.get(milestoneName),
                            milestone: milestoneName, index: nodes.length, level: 0, outgoing: [], remaining: 0};
                        milestoneNodes.set(milestoneName, milestone);
                        nodes.push(milestone);
                    }
                    const milestone = milestoneNodes.get(milestoneName);
                    milestone.outgoing.push(node);
                    node.remaining++;
                    node.dateOffset = kind === 'source' ? 0 : Number(field(node.row, 'day-offset').value || 0);
                    links.push([milestone, node, 'date']);
                    dateLinks.push([milestone, node, node.dateOffset]);
                } else if (kind === 'task') {
                    const sourceKey = field(node.row, 'source-task-key').value;
                    const source = byKey.get(sourceKey);
                    if (source) {
                        node.dateOffset = Number(field(node.row, 'day-offset').value || 0);
                        dateLinks.push([source, node, node.dateOffset]);
                        links.push([source, node, 'date']);
                    }
                    else if (sourceKey) invalid = true;
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
            if (!cyclic) invalid = positionGraphDates(nodes, links, dateLinks) || invalid;
            const pair = (from, to) => JSON.stringify([from.key, to.key].sort());
            const dependencyPairs = new Set(links.filter(link => link[2] === 'dependency')
                .map(([from, to]) => pair(from, to)));
            // Suppress duplicate visual date links, retaining every date constraint for positioning.
            const visibleLinks = links.filter(([from, to, relation]) => relation !== 'date'
                || !dependencyPairs.has(pair(from, to)));
            const layout = arrangeGraph(nodes, visibleLinks, cyclic, dateLinks);
            width = layout.width;
            height = layout.height;
            svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
            svg.replaceChildren();
            const defs = element('defs');
            for (const relation of ['dependency', 'date']) {
                const marker = element('marker', {id: `${markerId}-${relation}`, viewBox: '0 0 10 10', refX: 9,
                    refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse'});
                marker.append(element('path', {d: 'M 0 0 L 10 5 L 0 10 z',
                    class: `diary-graph-arrow${relation === 'date' ? ' diary-graph-arrow-date' : ''}`}));
                defs.append(marker);
            }
            svg.append(defs);
            for (const {from, to, path: route, relation, reversed} of layout.routes) {
                const dateRelation = relation === 'date';
                let label = `${from.name} → ${to.name}`;
                if (dateRelation) {
                    const offset = to.dateOffset;
                    const sourceKind = from.milestone ? 'milestone' : 'source task';
                    const rule = !Number.isInteger(offset) ? 'Incomplete day offset'
                        : offset === 0 ? `Same date as ${sourceKind}`
                        : `${Math.abs(offset)} calendar days ${offset < 0 ? 'before' : 'after'} ${sourceKind}`;
                    label += `: ${rule}`;
                }
                const path = element('path', {class: `diary-graph-edge${dateRelation ? ' diary-graph-edge-date' : ''}`,
                    d: route, 'data-source-key': from.key, 'data-target-key': to.key,
                    'data-relation': relation, 'aria-label': label,
                    [reversed ? 'marker-start' : 'marker-end']: `url(#${markerId}-${relation})`});
                path.append(element('title', {}, label));
                svg.append(path);
            }
            for (const node of nodes) {
                if (node.milestone) {
                    const diamond = element('g', {class: 'diary-graph-milestone', tabindex: 0, role: 'img',
                        'data-milestone-name': node.milestone, 'aria-label': `Milestone: ${node.name} (${node.milestone})`});
                    diamond.append(element('title', {}, `${node.name} (${node.milestone})`));
                    diamond.append(element('polygon', {points: `${node.center},${node.y} ${node.x + 216},${node.y + 41} ${node.center},${node.y + 82} ${node.x},${node.y + 41}`}));
                    const label = element('text', {x: node.center, y: node.y + 36, 'text-anchor': 'middle'});
                    const parts = node.name.match(/.{1,18}(?:\s|$)|.{1,18}/gu) || [node.name];
                    parts.slice(0, 2).forEach((part, index) => {
                        const text = index === 1 && parts.length > 2 ? `${part.trim().slice(0, 16)}…` : part.trim();
                        label.append(element('tspan', {x: node.center, dy: index ? 18 : 0}, text));
                    });
                    diamond.append(label);
                    svg.append(diamond);
                    continue;
                }
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
                    node.row.dispatchEvent(new CustomEvent('diary:edit-task', {bubbles: true}));
                });
                svg.append(link);
            }
            const dateCount = visibleLinks.filter(link => link[2] === 'date').length;
            const summary = taskNodes.length
                ? `${taskNodes.length} tasks · ${milestoneNodes.size} milestones · ${visibleLinks.length - dateCount} completion connections · ${dateCount} date relations.`
                : 'No tasks yet. Use Add task to start the graph.';
            status.textContent = summary + (cyclic || invalid ? ' Check task keys, milestones, and predecessor selections; this preview is not a valid dependency order.' : '');
            viewport.hidden = !taskNodes.length;
            navigation.update(width, height, latest.length > 0);
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
        const updateGraph = taskGraph(editor, milestones);
        const rows = Array.from(list.querySelectorAll('.diary-template-task'));
        const dialog = editor.querySelector('.diary-template-task-dialog');
        const enhanced = typeof dialog.showModal === 'function';
        const index = editor.querySelector('.diary-template-task-index');
        const indexButtons = editor.querySelector('.diary-template-task-buttons');
        const search = editor.querySelector('.diary-template-task-search');
        const metadata = editor.querySelector('.diary-template-metadata');
        const settingsDialog = editor.querySelector('.diary-template-settings-dialog');
        const helpDialog = editor.querySelector('.diary-template-help-dialog');
        const settingsButton = editor.querySelector('.diary-template-settings');
        const helpButton = editor.querySelector('.diary-template-help');
        let settingsSnapshot = [], settingsFocus = null;
        let editing = null, snapshot = [], isNew = false, returnFocus = null;

        function openSettings() {
            if (!enhanced || settingsDialog.open || dialog.open || helpDialog.open) return;
            settingsFocus = document.activeElement;
            settingsSnapshot = Array.from(metadata.querySelectorAll('input, textarea'), control => ({control, value: control.value}));
            settingsDialog.showModal();
            settingsButton.setAttribute('aria-expanded', 'true');
            const first = metadata.querySelector('input:not(:disabled), textarea');
            if (first) first.focus();
        }

        function closeSettings(accept) {
            if (!settingsDialog.open) return;
            if (accept) {
                const invalid = Array.from(metadata.querySelectorAll('input, textarea')).find(control => !control.checkValidity());
                if (invalid) { invalid.reportValidity(); return; }
            } else {
                for (const {control, value} of settingsSnapshot) control.value = value;
            }
            settingsDialog.close();
            settingsButton.setAttribute('aria-expanded', 'false');
            message.textContent = accept ? 'Settings saved to draft. Save template to publish the new version.' : 'Settings edits canceled.';
            if (settingsFocus && settingsFocus !== document.body && settingsFocus.isConnected) settingsFocus.focus();
            else settingsButton.focus();
        }

        if (enhanced) {
            settingsDialog.querySelector('.diary-template-settings-content').append(metadata);
            helpDialog.querySelector('.diary-template-help-container').append(editor.querySelector('.diary-template-help-content'));
            show(editor.querySelector('.diary-graph-toolbar-end'), true);
            settingsButton.addEventListener('click', () => settingsDialog.open ? closeSettings(false) : openSettings());
            editor.querySelector('.diary-template-settings-save').addEventListener('click', () => closeSettings(true));
            editor.querySelector('.diary-template-settings-cancel').addEventListener('click', () => closeSettings(false));
            settingsDialog.addEventListener('cancel', event => { event.preventDefault(); closeSettings(false); });
            settingsDialog.addEventListener('keydown', event => {
                if (event.key === 'Enter' && event.target.matches('input')) {
                    event.preventDefault(); closeSettings(true);
                }
            });
            helpButton.addEventListener('click', () => {
                if (!helpDialog.open && !dialog.open && !settingsDialog.open) {
                    helpDialog.showModal(); helpButton.setAttribute('aria-expanded', 'true');
                }
            });
            editor.querySelector('.diary-template-help-close').addEventListener('click', () => helpDialog.close());
            helpDialog.addEventListener('close', () => {
                helpButton.setAttribute('aria-expanded', 'false'); helpButton.focus();
            });
        }

        /** Keep canceled edits, including removed source choices, out of the draft. */
        function capture() {
            return rows.flatMap(row => Array.from(row.querySelectorAll('input, select, textarea'))
                .filter(control => !control.matches('.diary-template-date-mode, .diary-template-date-source'))
                .map(control => ({
                    control, value: control.value, checked: control.checked,
                    options: control.options ? Array.from(control.options, option => ({
                        value: option.value, text: option.text, selected: option.selected,
                    })) : null,
                })));
        }

        function closeTask(accept) {
            if (!editing) return;
            const discardNew = !accept && isNew;
            if (!accept) {
                for (const saved of snapshot) {
                    if (saved.options) saved.control.replaceChildren(...saved.options.map(option =>
                        new Option(option.text, option.value, false, option.selected)));
                    else saved.control.value = saved.value;
                    saved.control.checked = saved.checked;
                }
                for (const control of editing.querySelectorAll('.diary-template-date-mode, .diary-template-date-source')) {
                    delete control.dataset.rule;
                }
            }
            if (discardNew) {
                rows.splice(rows.indexOf(editing), 1);
                editing.remove();
                total.value = String(Number(total.value) - 1);
            } else {
                list.append(editing);
                show(editing, false);
            }
            editing = null;
            dialog.close();
            refresh();
            message.textContent = accept ? 'Task saved to draft. Save template to persist the new version.' : 'Task edits canceled.';
            if (returnFocus && returnFocus.isConnected && returnFocus.getClientRects().length) returnFocus.focus();
            else editor.querySelector('.diary-template-add').focus();
        }

        function openTask(task, adding = false) {
            if (!enhanced || editing) return;
            returnFocus = document.activeElement;
            snapshot = capture();
            isNew = adding;
            editing = task;
            dialog.querySelector('.diary-template-dialog-content').append(task);
            show(task, true);
            dialog.showModal();
            field(task, 'name').focus();
        }

        editor.addEventListener('diary:edit-task', event => {
            if (enhanced) openTask(event.target);
            else {
                event.target.scrollIntoView({block: 'center'});
                field(event.target, 'name').focus({preventScroll: true});
            }
        });
        editor.querySelector('.diary-template-task-save').addEventListener('click', () => {
            if (!editing) return;
            const invalid = Array.from(editing.querySelectorAll('input, select, textarea'))
                .find(control => !control.disabled && !control.checkValidity());
            if (invalid) { invalid.reportValidity(); return; }
            closeTask(true);
        });
        editor.querySelector('.diary-template-task-cancel').addEventListener('click', () => closeTask(false));
        dialog.addEventListener('cancel', event => { event.preventDefault(); closeTask(false); });
        // Enter accepts the task, rather than inadvertently publishing a template version.
        dialog.addEventListener('keydown', event => {
            if (event.key === 'Enter' && event.target.matches('input:not([type="search"])')) {
                event.preventDefault();
                editor.querySelector('.diary-template-task-save').click();
            }
        });
        form.addEventListener('invalid', event => {
            const row = event.target.closest('.diary-template-task');
            if (row && enhanced) { event.preventDefault(); openTask(row); }
            else if (enhanced && metadata.contains(event.target)) { event.preventDefault(); openSettings(); }
        }, true);
        form.addEventListener('submit', event => {
            if (editing || settingsDialog.open || helpDialog.open) { event.preventDefault(); return; }
        });
        search.addEventListener('input', updateIndex);
        function updateIndex() {
            indexButtons.replaceChildren();
            for (const row of rows) {
                const name = field(row, 'name').value || 'Unnamed task';
                if (!name.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())) continue;
                const button = document.createElement('button');
                button.type = 'button'; button.className = 'diary-button';
                button.textContent = name + (field(row, 'delete').checked ? ' (removed — edit to restore)' : '');
                button.addEventListener('click', () => openTask(row));
                indexButtons.append(button);
            }
        }

        /** Return task rows from this editor, including rows marked for deletion. */
        function tasks() {
            return rows;
        }

        /**
         * Refresh rule panels and safe predecessor choices from all proposed task edits.
         * DV1-027: Exclude this task and its successors using the proposed graph.
         * DV1-017: Show the selected ownership group warning.
         */
        function refresh() {
            const rows = tasks();
            const active = rows.filter(task => !field(task, 'delete').checked);
            const predecessorOrder = orderedTaskChoices(active);
            const dateOrder = orderedTaskChoices(active, true);
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
                    ...dateOrder.filter(candidate => candidate !== task).map(candidate => {
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
                if (enhanced) {
                    // One date-source picker uses the same offset for tasks and milestones.
                    show(field(task, 'date-kind').closest('.diary-template-field'), false);
                    show(task.querySelector('.diary-template-milestone-fields'), false);
                    show(task.querySelector('.diary-template-task-date-fields'), false);
                    const mode = task.querySelector('.diary-template-date-mode');
                    const source = task.querySelector('.diary-template-date-source');
                    const modeValue = kind === 'annual' ? 'annual' : 'relative';
                    if (mode.dataset.rule !== modeValue) {
                        mode.value = modeValue;
                        mode.dataset.rule = modeValue;
                    }
                    const proposed = document.createElement('select');
                    proposed.append(new Option('Select a date source', ''));
                    const selectedSource = kind === 'task' ? `task:${sourceValue}` : `milestone:${previousMilestone}`;
                    for (const [label, options] of [
                        ['Milestone dates', milestones.map(item => [`milestone:${item.name}`, item.label])],
                        ['Task due dates', dateOrder.filter(row => row !== task).map(row =>
                            [`task:${field(row, 'entry-key').value}`, field(row, 'name').value || 'Unnamed task'])],
                    ]) {
                        const group = document.createElement('optgroup'); group.label = label;
                        for (const [value, label] of options) group.append(new Option(label, value, false, value === selectedSource));
                        proposed.append(group);
                    }
                    const options = select => Array.from(select.options, option => [option.value, option.text]);
                    // A name blur must not detach the option currently being chosen with a mouse.
                    if (JSON.stringify(options(source)) !== JSON.stringify(options(proposed))) {
                        const previous = source.value;
                        source.replaceChildren(...proposed.childNodes);
                        source.value = previous;
                    }
                    if (source.dataset.rule !== selectedSource) {
                        source.value = selectedSource;
                        source.dataset.rule = selectedSource;
                    }
                    if (source.selectedIndex < 0) source.value = '';
                    show(source.closest('.diary-template-field'), kind !== 'annual');
                    const errors = [field(task, 'date-kind'), field(task, 'milestone-name'), sourceSelect]
                        .map(control => control.closest('.diary-template-field').querySelector('.diary-field-errors'))
                        .filter(Boolean).map(error => error.textContent.trim());
                    task.querySelector('.diary-template-date-errors').textContent = errors.join(' ');
                }
                show(task.querySelector('.diary-template-person-fields'), owner === 'person');
                show(task.querySelector('.diary-template-role-fields'), owner === 'role');
                if (enhanced) {
                    task.querySelector('.diary-template-date-source').required = !deleted && kind !== 'annual';
                    for (const [name, required] of [['month', kind === 'annual'], ['day', kind === 'annual'],
                        ['person-ref', owner === 'person'], ['role-ref', owner === 'role']]) {
                        field(task, name).required = !deleted && required;
                    }
                    const month = Number(field(task, 'month').value), day = Number(field(task, 'day').value);
                    const annualDate = new Date(Date.UTC(2000, month - 1, day));
                    field(task, 'day').setCustomValidity(!deleted && kind === 'annual' && month && day
                        && (annualDate.getUTCMonth() !== month - 1 || annualDate.getUTCDate() !== day)
                        ? 'Enter a valid month and day.' : '');
                }
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
                for (const candidate of predecessorOrder) {
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
            updateIndex();
        }

        /** Enable removal controls while retaining the server checkbox fallback. */
        function prepare(task) {
            const kind = field(task, 'date-kind');
            // Legacy milestone dates are displayed as the one milestone rule with zero offset.
            if (kind.value === 'source') {
                kind.value = 'relative';
                field(task, 'day-offset').value = '0';
            }
            show(task.querySelector('.diary-template-remove'), true);
            show(task.querySelector('.diary-template-delete-field'), false);
            show(task.querySelector('.diary-template-predecessor-filter'), true);
            if (enhanced) {
                const controls = document.createElement('div');
                controls.className = 'diary-template-date-controls';
                for (const [className, labelText, options] of [
                    ['mode', 'Due date', [['relative', 'From a date source'], ['annual', 'Annual date']]],
                    ['source', 'Date source', []],
                ]) {
                    const wrapper = document.createElement('div'); wrapper.className = 'diary-template-field';
                    const label = document.createElement('label'); label.className = 'diary-field-label'; label.textContent = labelText;
                    const select = document.createElement('select'); select.className = `diary-input diary-template-date-${className}`;
                    select.id = `${field(task, 'name').id}-date-${className}`; label.htmlFor = select.id;
                    for (const [value, text] of options) select.add(new Option(text, value));
                    wrapper.append(label, select); controls.append(wrapper);
                }
                const errors = document.createElement('p'); errors.className = 'diary-field-errors diary-template-date-errors';
                errors.setAttribute('role', 'alert'); controls.append(errors);
                field(task, 'date-kind').closest('.diary-template-field').before(controls);
                controls.addEventListener('change', () => {
                    const mode = controls.querySelector('.diary-template-date-mode').value;
                    const value = controls.querySelector('.diary-template-date-source').value;
                    const taskSource = value.startsWith('task:');
                    kind.value = mode === 'annual' ? 'annual' : taskSource ? 'task' : 'relative';
                    if (mode !== 'annual') field(task, taskSource ? 'source-task-key' : 'milestone-name').value = value.slice(value.indexOf(':') + 1);
                    refresh();
                });
                show(task, false);
            }
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
                || event.target.classList.contains('diary-template-field-day-offset')
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
            rows.push(task);
            total.value = String(index + 1);
            prepare(task);
            refresh();
            if (enhanced) openTask(task, true);
            else field(task, 'name').focus();
            message.textContent = 'New task added. Save template to apply the new version.';
        });
        refresh();
        if (enhanced) {
            show(index, true);
            const errorRow = rows.find(row => row.querySelector('.diary-field-error, .diary-form-error'));
            if (errorRow) openTask(errorRow);
            else if (editor.dataset.creating === 'true' || metadata.querySelector('.diary-field-error')) openSettings();
        }
    }

    for (const editor of document.querySelectorAll('.diary-template-editor')) {
        initialize(editor);
    }
})();
