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

    /** Preserve signed date offsets, then use completion order to position independent date groups. */
    function positionGraphDates(nodes, links, dateLinks) {
        const neighbors = new Map(nodes.map(node => [node, []]));
        const zeroOutgoing = new Map(nodes.map(node => [node, []]));
        const zeroRemaining = new Map(nodes.map(node => [node, 0]));
        const zeroDepth = new Map(nodes.map(node => [node, 0]));
        let invalid = false;
        for (const [source, task, offset] of dateLinks) {
            if (!Number.isSafeInteger(offset)) { invalid = true; continue; }
            neighbors.get(source).push({node: task, offset});
            neighbors.get(task).push({node: source, offset: -offset});
            if (offset === 0) {
                zeroOutgoing.get(source).push(task);
                zeroRemaining.set(task, zeroRemaining.get(task) + 1);
            }
        }
        // Zero days still means the same date. Give zero-offset chains separate visual rows only.
        const zeroReady = nodes.filter(node => zeroRemaining.get(node) === 0);
        for (let index = 0; index < zeroReady.length; index++) {
            const source = zeroReady[index];
            for (const task of zeroOutgoing.get(source)) {
                zeroDepth.set(task, Math.max(zeroDepth.get(task), zeroDepth.get(source) + 1));
                zeroRemaining.set(task, zeroRemaining.get(task) - 1);
                if (zeroRemaining.get(task) === 0) zeroReady.push(task);
            }
        }
        const groups = [];
        for (const node of nodes) {
            if (node.dateGroup) continue;
            const group = {nodes: [node], outgoing: new Map(), remaining: 0, shift: 0};
            node.dateGroup = group;
            node.relativeDay = 0;
            let degree = 0;
            for (let index = 0; index < group.nodes.length; index++) {
                const current = group.nodes[index];
                degree += neighbors.get(current).length;
                for (const next of neighbors.get(current)) {
                    const day = current.relativeDay + next.offset;
                    if (!next.node.dateGroup) {
                        next.node.dateGroup = group;
                        next.node.relativeDay = day;
                        group.nodes.push(next.node);
                    } else if (next.node.relativeDay !== day) invalid = true;
                }
            }
            if (degree / 2 >= group.nodes.length) invalid = true;
            // Sort actual days first, then separate zero-offset sources and their same-day tasks.
            const slots = group.nodes.map(current => ({day: current.relativeDay, depth: zeroDepth.get(current)}))
                .sort((a, b) => a.day - b.day || a.depth - b.depth);
            const ranks = new Map();
            for (const {day, depth} of slots) {
                const key = `${day}:${depth}`;
                if (!ranks.has(key)) ranks.set(key, ranks.size);
            }
            for (const current of group.nodes) current.dateRank = ranks.get(`${current.relativeDay}:${zeroDepth.get(current)}`);
            groups.push(group);
        }
        // Completion links are layout hints between groups, never instructions to move a calculated date.
        for (const [from, to, relation] of links) {
            if (relation !== 'dependency' || from.dateGroup === to.dateGroup) continue;
            const source = from.dateGroup, target = to.dateGroup;
            if (!source.outgoing.has(target)) {
                const pending = [target], seen = new Set();
                let cycle = false;
                while (groups.length < nodes.length && pending.length) {
                    const current = pending.pop();
                    if (current === source) { cycle = true; break; }
                    if (!seen.has(current)) { seen.add(current); pending.push(...current.outgoing.keys()); }
                }
                // Collapsing date groups can create a layout cycle even in a valid completion DAG.
                if (cycle) continue;
                target.remaining++;
            }
            const distance = from.dateRank - to.dateRank + 1;
            source.outgoing.set(target, Math.max(source.outgoing.get(target) ?? -Infinity, distance));
        }
        const ready = groups.filter(group => group.remaining === 0);
        for (let index = 0; index < ready.length; index++) {
            const group = ready[index];
            for (const [next, distance] of group.outgoing) {
                next.shift = Math.max(next.shift, group.shift + distance);
                if (--next.remaining === 0) ready.push(next);
            }
        }
        const levels = [...new Set(nodes.map(node => node.dateGroup.shift + node.dateRank))].sort((a, b) => a - b);
        const ranks = new Map(levels.map((level, index) => [level, index]));
        for (const node of nodes) node.level = ranks.get(node.dateGroup.shift + node.dateRank);
        return invalid;
    }

    /** Layered layout with crossing reduction and reserved lanes for edges spanning rows. */
    function arrangeGraph(nodes, links, cyclic, dateLinks = []) {
        const neighbors = new Map(nodes.map(node => [node, []]));
        const pairs = new Map();
        const pairKey = (from, to) => JSON.stringify([from.key, to.key].sort());
        for (const [from, to] of links) {
            const key = pairKey(from, to);
            pairs.set(key, (pairs.get(key) || 0) + 1);
        }
        // Keep a date arrow distinct when the same tasks also have a completion link.
        const portShift = (from, to, relation) => pairs.get(pairKey(from, to)) > 1 ? (relation === 'date' ? 8 : -8) : 0;
        for (const [from, to] of [...links, ...dateLinks]) { neighbors.get(from).push(to); neighbors.get(to).push(from); }
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
            const chains = [], bypasses = [], sameRows = [];
            for (const [from, to, relation] of component.links) {
                if (!cyclic && from.level === to.level) { sameRows.push({from, to, relation}); continue; }
                const reversed = !cyclic && from.level > to.level;
                const low = reversed ? to : from, high = reversed ? from : to;
                const span = high.level - low.level - 1;
                // Bound work even for dense templates. Overflow edges use exterior lanes instead.
                if (!cyclic && span > virtualBudget) { bypasses.push({from, to, low, high, relation, reversed}); continue; }
                const chain = [low];
                if (!cyclic) {
                    for (let level = low.level + 1; level < high.level; level++) {
                        const waypoint = {virtual: true};
                        add(waypoint, level);
                        chain.push(waypoint);
                        virtualBudget--;
                    }
                    chain.push(high);
                    for (let i = 1; i < chain.length; i++) {
                        outgoing.get(chain[i - 1]).push(chain[i]);
                        incoming.get(chain[i]).push(chain[i - 1]);
                    }
                } else chain.push(high);
                chains.push({from, to, chain, relation, reversed});
            }
            for (let level = 0; level < layers.length; level++) layers[level] ||= [];
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
            for (const {from, to, chain, relation, reversed} of chains) {
                const low = chain[0];
                const shift = portShift(from, to, relation);
                const x = vertex => vertex.center + (vertex.virtual ? 0 : shift);
                let path = `M ${x(low)} ${low.y + (reversed ? 86 : 82)}`;
                for (let i = 1; i < chain.length; i++) {
                    const previous = chain[i - 1], current = chain[i];
                    const top = current.y - 4;
                    const bottom = previous.y + (previous.virtual || (i === 1 && reversed) ? 86 : 82);
                    const middle = (bottom + top) / 2;
                    // Change horizontal position only in the gap between task rows.
                    path += ` C ${x(previous)} ${middle} ${x(current)} ${middle} ${x(current)} ${top}`;
                    if (current.virtual) path += ` L ${x(current)} ${current.y + 86}`;
                }
                routes.push({from, to, path, relation, reversed});
            }
            bypasses.forEach(({from, to, low, high, relation, reversed}, index) => {
                const lane = left + componentWidth + 16 + (index % 12) * 8;
                const shift = portShift(from, to, relation);
                const lowX = low.center + shift, highX = high.center + shift;
                routes.push({from, to, relation, reversed, path: `M ${lowX} ${low.y + (reversed ? 86 : 82)} L ${lowX} ${low.y + 102} L ${lane} ${low.y + 102} L ${lane} ${high.y - 20} L ${highX} ${high.y - 20} L ${highX} ${high.y - 4}`});
            });
            sameRows.forEach(({from, to, relation}, index) => {
                const lane = from.y + 102 + (index % 5) * 6;
                const shift = portShift(from, to, relation);
                const fromX = from.center + shift, toX = to.center + shift;
                routes.push({from, to, relation, path: `M ${fromX} ${from.y + 82} L ${fromX} ${lane} L ${toX} ${lane} L ${toX} ${to.y + 86}`});
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
        const toolbar = editor.querySelector('.diary-graph-toolbar');
        const zoom = toolbar.querySelector('.diary-graph-zoom');
        show(toolbar.querySelector('.diary-graph-zoom-controls'), true);
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
            if (!latest.length) scale = 1;
            else if (fitting) {
                scale = Math.min(1, Math.max(1, viewport.clientWidth - 8) / width,
                    Math.max(1, viewport.clientHeight - 8) / height);
            }
            svg.setAttribute('width', String(Math.ceil(width * scale)));
            svg.setAttribute('height', String(Math.ceil(height * scale)));
            // Explicit CSS dimensions prevent host SVG sizing rules from shrinking the scrollable canvas.
            svg.style.width = `${Math.ceil(width * scale)}px`;
            svg.style.height = `${Math.ceil(height * scale)}px`;
            zoom.value = `${Math.round(scale * 100)}%`;
            toolbar.querySelector('[data-graph-action="in"]').disabled = !latest.length || scale >= 2;
            toolbar.querySelector('[data-graph-action="out"]').disabled = !latest.length || scale <= .1;
            toolbar.querySelector('[data-graph-action="fit"]').disabled = !latest.length;
        }

        function changeZoom(action) {
            fitting = action === 'fit';
            if (!fitting) scale = Math.max(.1, Math.min(2, scale * (action === 'in' ? 1.25 : .8)));
            resize();
            if (fitting) viewport.scrollTo(0, 0);
        }

        toolbar.addEventListener('click', event => {
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
