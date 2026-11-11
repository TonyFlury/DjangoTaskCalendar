/* Live diary graph: presentation only; actions use existing task navigation. */
(async () => {
    'use strict';
    const script = document.currentScript;
    if (!window.DiaryGraph) await import(new URL('graph_layout.js', script.src));
    const root = document.querySelector('.diary-manager-graph');
    if (!root) return;
    const data = JSON.parse(document.getElementById('diary-manager-graph-data').textContent);
    const viewport = root.querySelector('.diary-graph-viewport');
    const svg = viewport.querySelector('svg');
    const toolbar = root.querySelector('.diary-graph-toolbar');
    const element = (tag, attrs = {}, text = null) => {
        const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
        Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, value));
        if (text !== null) el.textContent = text;
        return el;
    };
    const nodes = data.nodes.map((node, index) => ({...node, index, level: 0}));
    const byKey = new Map(nodes.map(node => [node.key, node]));
    const pairs = new Map();
    for (const edge of data.edges) {
        const key = JSON.stringify([edge.source, edge.target].sort());
        if (!pairs.has(key)) pairs.set(key, []);
        pairs.get(key).push(edge);
    }
    const edges = [];
    for (const group of pairs.values()) {
        const dependencies = group.filter(edge => edge.kind === 'dependency');
        for (const edge of dependencies.length ? dependencies : group) {
            edges.push({...edge, description: group.map(item => item.description).join('; ')});
        }
    }
    const links = edges.map(edge => [byKey.get(edge.source), byKey.get(edge.target), edge.kind]);
    // Saved effective dates lead the layout. Never recalculate snapshots from offsets.
    const dates = [...new Set(nodes.filter(node => node.date).map(node => node.date))].sort();
    let nextLevel = 0;
    for (const date of [...dates, null]) {
        const group = nodes.filter(node => (node.date || null) === date);
        const same = links.filter(([from, to]) => group.includes(from) && group.includes(to));
        const remaining = new Map(group.map(node => [node, same.filter(link => link[1] === node).length]));
        const ready = group.filter(node => !remaining.get(node));
        for (let index=0; index<ready.length; index++) {
            const from = ready[index];
            for (const [, to] of same.filter(link => link[0] === from)) {
                to.level = Math.max(to.level, from.level + 1);
                remaining.set(to, remaining.get(to)-1);
                if (!remaining.get(to)) ready.push(to);
            }
        }
        const depth = Math.max(0, ...group.map(node => node.level));
        group.forEach(node => { node.level += nextLevel; });
        nextLevel += depth + 1;
    }
    const layout = window.DiaryGraph.arrangeGraph(nodes, links, false);
    svg.setAttribute('viewBox', `0 0 ${layout.width} ${layout.height}`);
    const defs = element('defs');
    for (const relation of ['dependency', 'date']) {
        const marker = element('marker', {id:`diary-live-arrow-${relation}`, viewBox:'0 0 10 10', refX:9, refY:5, markerWidth:7, markerHeight:7, orient:'auto-start-reverse'});
        marker.append(element('path', {d:'M 0 0 L 10 5 L 0 10 z', class:`diary-graph-arrow${relation === 'date' ? '-date' : ''}`}));
        defs.append(marker);
    }
    svg.append(defs);
    for (const route of layout.routes) {
        const edge = edges.find(item => item.source === route.from.key && item.target === route.to.key && item.kind === route.relation);
        const path = element('path', {d:route.path, class:`diary-graph-edge diary-graph-edge-${route.relation}${edge.active_blocker ? '' : ' diary-graph-edge-inactive'}`,
            'marker-end':`url(#diary-live-arrow-${route.relation})`, tabindex:0, 'data-source-key':edge.source, 'data-target-key':edge.target,
            'aria-label':`${route.from.name} → ${route.to.name}: ${edge.description}`});
        path.append(element('title', {}, path.getAttribute('aria-label')));
        svg.append(path);
    }
    const short = value => value.length > 27 ? value.slice(0,24)+'…' : value;
    for (const node of nodes) {
        const task = node.kind === 'task';
        const lines = task ? [node.name, node.status_label, node.date || 'Date not set',
            node.orphaned ? 'Owner needs review' : node.context_outside_view ? 'Related item outside view' : node.owner_label]
            : [node.name, 'Milestone', node.date || 'Date not set'];
        const title = [node.name, ...lines.slice(1), node.description || '', node.context_outside_view ? 'Related item outside view' : ''].filter(Boolean).join(' · ');
        const group = element('g', {class:task ? `diary-graph-node diary-graph-task-${node.state}${node.blocked ? ' diary-graph-task-blocked-pattern' : ''}${node.orphaned ? ' diary-graph-task-orphaned' : ''}` : 'diary-graph-milestone',
            tabindex:0, role:task ? 'link' : 'img', 'aria-label':title, 'data-node-key':node.key});
        group.append(element('title', {}, title));
        if (task) {
            group.dataset.diaryKey = node.diary_key;
            group.dataset.entryKey = node.entry_key;
            group.append(element('rect', {x:node.x, y:node.y, width:216, height:82, rx:8}));
            const open = () => {
                const button = [...root.querySelectorAll('.diary-manager-graph-task-list button[name="entry_key"]')].find(item => item.value === node.entry_key);
                if (button) button.click();
                else window.location.assign(node.detail_url);
            };
            group.addEventListener('click', open);
            group.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } });
        } else {
            group.append(element('polygon', {points:`${node.x+108},${node.y} ${node.x+216},${node.y+41} ${node.x+108},${node.y+82} ${node.x},${node.y+41}`}));
        }
        lines.forEach((line, index) => group.append(element('text', {x:node.x+108, y:node.y+18+index*18, 'text-anchor':'middle',
            class: index === 2 && !node.date ? 'diary-graph-undated' : index === 3 && node.orphaned ? 'diary-graph-owner-warning' : ''}, short(line || ''))));
        svg.append(group);
    }
    viewport.hidden = false;
    toolbar.querySelectorAll('[data-graph-action], .diary-graph-zoom, .diary-graph-colour-control').forEach(el => { el.hidden = false; });
    const navigation = window.DiaryGraph.createViewport(viewport, svg, toolbar);
    navigation.update(layout.width, layout.height, nodes.length > 0);
    root.querySelector('.diary-manager-graph-task-list').open = false;
    root.querySelector('.diary-graph-colours').addEventListener('change', event => root.classList.toggle('diary-graph-neutral', !event.target.checked));
    for (const name of ['filter', 'help']) {
        const content = root.querySelector(`.diary-manager-graph-${name}-content`);
        const dialog = root.querySelector(`.diary-manager-graph-${name}-dialog`);
        const button = root.querySelector(`.diary-manager-graph-${name === 'filter' ? 'filters' : 'help'}`);
        if (!dialog.showModal) continue;
        dialog.append(content);
        button.hidden = false;
        button.addEventListener('click', () => dialog.showModal());
        content.querySelectorAll('[data-graph-close]').forEach(close => {
            close.hidden = false;
            close.addEventListener('click', () => { content.querySelector('form')?.reset(); dialog.close(); });
        });
        dialog.addEventListener('cancel', () => content.querySelector('form')?.reset());
    }
})();
