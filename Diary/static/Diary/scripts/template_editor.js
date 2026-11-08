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

    /** Layered layout with crossing reduction and reserved lanes for edges spanning rows. */
    function arrangeGraph(nodes, links, cyclic) {
        const neighbors = new Map(nodes.map(node => [node, []]));
        for (const [from, to] of links) { neighbors.get(from).push(to); neighbors.get(to).push(from); }
        const seen = new Set(), components = [];
        for (const node of nodes) {
            if (seen.has(node)) continue;
            const component = {nodes: [node], links: []};
            seen.add(node);
            for (let i = 0; i < component.nodes.length; i++) {
                const current = component.nodes[i];
                current.component = component;
                for (const next of neighbors.get(current)) {
                    if (!seen.has(next)) { seen.add(next); component.nodes.push(next); }
                }
            }
            // Form order supplies deterministic ties without moving tasks when their names change.
            component.nodes.sort((a, b) => a.index - b.index);
            components.push(component);
        }
        for (const link of links) link[0].component.links.push(link);

        /** Count inversions between adjacent rows, excluding shared endpoints. */
        function crossings(layers, outgoing) {
            let total = 0;
            for (let level = 0; level < layers.length - 1; level++) {
                const next = layers[level + 1];
                const ranks = new Map(next.map((node, index) => [node, index + 1]));
                const tree = new Array(next.length + 1).fill(0);
                let inserted = 0;
                for (const node of layers[level]) {
                    const targets = outgoing.get(node);
                    for (const target of targets) {
                        let sum = 0;
                        for (let i = ranks.get(target); i > 0; i -= i & -i) sum += tree[i];
                        total += inserted - sum;
                    }
                    // Add a source's whole group afterwards: its own edges do not cross each other.
                    for (const target of targets) {
                        for (let i = ranks.get(target); i < tree.length; i += i & -i) tree[i]++;
                        inserted++;
                    }
                }
            }
            return total;
        }

        function reduceCrossings(layers, incoming, outgoing) {
            let best = layers.map(layer => layer.slice());
            let score = crossings(layers, outgoing);
            for (let sweep = 0; sweep < 12 && score > 0; sweep++) {
                const down = sweep % 2 === 0;
                for (let level = down ? 1 : layers.length - 2;
                     down ? level < layers.length : level >= 0; level += down ? 1 : -1) {
                    const adjacent = layers[level + (down ? -1 : 1)];
                    const positions = new Map(adjacent.map((node, index) => [node, index]));
                    const relationships = down ? incoming : outgoing;
                    const centers = new Map(layers[level].map((node, index) => {
                        const connected = relationships.get(node);
                        return [node, connected.length ? connected.reduce((sum, neighbor) => sum + positions.get(neighbor), 0) / connected.length : index];
                    }));
                    layers[level].sort((a, b) => centers.get(a) - centers.get(b));
                }
                const candidate = crossings(layers, outgoing);
                if (candidate < score) { score = candidate; best = layers.map(layer => layer.slice()); }
            }
            return best;
        }

        let left = 24, height = 130, virtualBudget = 4000;
        const routes = [];
        for (const component of components) {
            let layers = [];
            const incoming = new Map(), outgoing = new Map();
            function add(vertex, level) {
                (layers[level] ||= []).push(vertex);
                incoming.set(vertex, []);
                outgoing.set(vertex, []);
            }
            for (const node of component.nodes) add(node, cyclic ? 0 : node.level);
            const chains = [], bypasses = [];
            for (const [from, to, relation] of component.links) {
                const span = to.level - from.level - 1;
                // Bound work even for dense templates. Overflow edges use exterior lanes instead.
                if (!cyclic && span > virtualBudget) { bypasses.push({from, to, relation}); continue; }
                const chain = [from];
                if (!cyclic) {
                    for (let level = from.level + 1; level < to.level; level++) {
                        const waypoint = {virtual: true};
                        add(waypoint, level);
                        chain.push(waypoint);
                        virtualBudget--;
                    }
                    chain.push(to);
                    for (let i = 1; i < chain.length; i++) {
                        outgoing.get(chain[i - 1]).push(chain[i]);
                        incoming.get(chain[i]).push(chain[i - 1]);
                    }
                } else chain.push(to);
                chains.push({from, to, chain, relation});
            }
            if (!cyclic) layers = reduceCrossings(layers, incoming, outgoing);
            const rowWidth = layer => layer.reduce((sum, node) => sum + (node.virtual ? 20 : 216), 0) + Math.max(0, layer.length - 1) * 32;
            const componentWidth = Math.max(...layers.map(rowWidth)) + 48;
            layers.forEach((layer, level) => {
                let x = left + (componentWidth - rowWidth(layer)) / 2;
                for (const node of layer) {
                    node.x = x;
                    node.y = 24 + level * 166;
                    node.center = x + (node.virtual ? 10 : 108);
                    x += (node.virtual ? 20 : 216) + 32;
                }
            });
            for (const {from, to, chain, relation} of chains) {
                let path = `M ${from.center} ${from.y + 82}`;
                for (let i = 1; i < chain.length; i++) {
                    const previous = chain[i - 1], current = chain[i];
                    const top = current.y - 4, bottom = previous.y + (previous.virtual ? 86 : 82);
                    const middle = (bottom + top) / 2;
                    // Change horizontal position only in the gap between task rows.
                    path += ` C ${previous.center} ${middle} ${current.center} ${middle} ${current.center} ${top}`;
                    if (current.virtual) path += ` L ${current.center} ${current.y + 86}`;
                }
                routes.push({from, to, path, relation});
            }
            bypasses.forEach(({from, to, relation}, index) => {
                const lane = left + componentWidth + 16 + (index % 12) * 8;
                routes.push({from, to, relation, path: `M ${from.center} ${from.y + 82} L ${from.center} ${from.y + 102} L ${lane} ${from.y + 102} L ${lane} ${to.y - 20} L ${to.center} ${to.y - 20} L ${to.center} ${to.y - 4}`});
            });
            left += componentWidth + (bypasses.length ? 40 + Math.min(12, bypasses.length) * 8 : 0) + 32;
            height = Math.max(height, layers.length * 166 + 32);
        }
        return {width: Math.max(320, left - 8), height, routes};
    }

    /** Read-only graph of the proposed form state; all mutations still use the task forms. */
    function taskGraph(editor, milestones) {
        const panel = editor.querySelector('.diary-template-graph');
        if (!panel) return () => {}; // Older host template overrides can keep their existing forms.
        const viewport = panel.querySelector('.diary-graph-viewport');
        const svg = panel.querySelector('svg');
        const status = panel.querySelector('.diary-graph-status');
        const zoom = panel.querySelector('.diary-graph-zoom');
        const markerId = `diary-graph-arrow-${entryKey()}`;
        const milestoneLabels = new Map(milestones.map(milestone => [milestone.name, milestone.label]));
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
            if (event.pointerType !== 'mouse' || event.button !== 0
                || event.target.closest('.diary-graph-node, .diary-graph-milestone')) return;
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
            const layout = arrangeGraph(nodes, links, cyclic);
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
            for (const {from, to, path: route, relation} of layout.routes) {
                const dateRelation = relation === 'date';
                let label = `${from.name} → ${to.name}`;
                if (dateRelation) {
                    const offset = to.dateOffset;
                    const rule = !Number.isInteger(offset) ? 'Incomplete day offset'
                        : offset === 0 ? 'Same date as milestone'
                        : `${Math.abs(offset)} calendar days ${offset < 0 ? 'before' : 'after'} milestone`;
                    label += `: ${rule}`;
                }
                const path = element('path', {class: `diary-graph-edge${dateRelation ? ' diary-graph-edge-date' : ''}`,
                    d: route, 'data-source-key': from.key, 'data-target-key': to.key,
                    'data-relation': relation, 'aria-label': label,
                    'marker-end': `url(#${markerId}-${relation})`});
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
                    node.row.scrollIntoView({block: 'center'});
                    input.focus({preventScroll: true});
                });
                svg.append(link);
            }
            const dateCount = links.filter(link => link[2] === 'date').length;
            const summary = taskNodes.length
                ? `${taskNodes.length} tasks · ${milestoneNodes.size} milestones · ${links.length - dateCount} completion connections · ${dateCount} date relations.`
                : 'No tasks yet. Add a task below to start the graph.';
            status.textContent = summary + (cyclic || invalid ? ' Check task keys, milestones, and predecessor selections; this preview is not a valid dependency order.' : '');
            viewport.hidden = !taskNodes.length;
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
        const updateGraph = taskGraph(editor, milestones);

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
