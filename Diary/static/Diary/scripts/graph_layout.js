/* Shared graph layout and navigation. No task mutations or permission decisions. */
(() => {
    'use strict';
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


    function createViewport(viewport, svg, toolbar) {
        const zoom = toolbar.querySelector('.diary-graph-zoom');
        let width=1, height=1, scale=1, fitting=true, hasNodes=false;
        function resize() {
            if (!hasNodes) scale = 1;
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
            toolbar.querySelector('[data-graph-action="in"]').disabled = !hasNodes || scale >= 2;
            toolbar.querySelector('[data-graph-action="out"]').disabled = !hasNodes || scale <= .1;
            toolbar.querySelector('[data-graph-action="fit"]').disabled = !hasNodes;
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

        return {update(w, h, populated) { width=w; height=h; hasNodes=populated; resize(); }};
    }
    window.DiaryGraph = Object.freeze({arrangeGraph, positionGraphDates, createViewport});
})();
