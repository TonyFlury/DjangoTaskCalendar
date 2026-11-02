'use strict';
(() => {
    const TODAY = '2027-06-12';
    const STORE = 'diary-ui-preview-v1';
    const people = {
        riley: {name: 'Riley Evans', groups: ['Officer', 'ExecMember']},
        sam: {name: 'Sam Patel', groups: ['ExecMember']},
        jess: {name: 'Jess Morgan', groups: ['ExecMember', 'SponsorshipManager']},
    };
    const roles = ['ExecMember', 'SponsorshipManager'];
    const milestoneLabels = {event_date: 'Event day', add_board_bookings_open: 'Advertising board bookings open', volunteer_briefing: 'Volunteer briefing'};
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
    const clone = value => JSON.parse(JSON.stringify(value));
    const $ = id => document.getElementById(id);
    const main = $('preview-main');
    let filters = {query:'', state:'open', team:false};
    let templateSelection = 't1';
    let versionSelection = 'draft';
    let lastList = 'mine';
    let toastTimer;
    function initial() {
        const tasks = [
            {id:'t1',name:'Confirm sponsor list',description:'Check the final list of sponsors and contact details.',type:'relative',milestone:'event_date',offset:-21,ownerKind:'role',owner:'SponsorshipManager',pred:[]},
            {id:'t2',name:'Prepare sponsor artwork',description:'Prepare the artwork after the sponsor list is complete.',type:'relative',milestone:'event_date',offset:-14,ownerKind:'role',owner:'SponsorshipManager',pred:['t1']},
            {id:'t3',name:'Approve sponsor artwork',description:'Check the artwork and give approval before publication.',type:'relative',milestone:'event_date',offset:-10,ownerKind:'person',owner:'riley',pred:['t2']},
            {id:'t4',name:'Publish sponsor notices',description:'Publish the approved sponsor notices.',type:'relative',milestone:'event_date',offset:-7,ownerKind:'role',owner:'SponsorshipManager',pred:['t3']},
            {id:'t5',name:'Inspect advertising boards',description:'Check that the advertising boards are ready for use.',type:'relative',milestone:'add_board_bookings_open',offset:42,ownerKind:'team',owner:'',pred:[]},
            {id:'t6',name:'Check my preparation notes',description:'Review my own notes before the event.',type:'once',fixed:'2027-06-18',ownerKind:'person',owner:'sam',pred:[]},
            {id:'t7',name:'Confirm venue access',description:'Confirm the access arrangements for the event.',type:'annual',month:6,day:1,yearOffset:0,ownerKind:'person',owner:'riley',pred:[],completed:true,completedBy:'riley',completedOn:'2027-06-02',completedDue:'2027-06-01',completionNote:'Access arrangements confirmed.'},
            {id:'t8',name:'Check volunteer rota',description:'Check the rota before the volunteer briefing.',type:'relative',milestone:'volunteer_briefing',offset:-2,ownerKind:'team',owner:'',pred:[]},
        ];
        const template = tasks.filter(task => task.type !== 'once').map(task => {
            const copy = clone(task); delete copy.completed; delete copy.completedBy; delete copy.completedOn; delete copy.completionNote; delete copy.completedDue; return copy;
        });
        return {persona:'riley',milestones:{event_date:'2027-06-27',add_board_bookings_open:'2027-05-01',volunteer_briefing:''},tasks,approved:clone(template),draft:clone(template),approvedNumber:1,nextId:9};
    }
    let state;
    try { state = JSON.parse(sessionStorage.getItem(STORE)) || initial(); } catch { state = initial(); }
    function persist() { try { sessionStorage.setItem(STORE, JSON.stringify(state)); } catch { /* Preview still works in memory. */ } }
    function officer() { return people[state.persona].groups.includes('Officer'); }
    function notify(message) { $('preview-toast').textContent = message; $('preview-toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => {$('preview-toast').hidden=true;}, 5000); }
    function go(path) { if(location.hash === '#'+path) render(); else location.hash = path; }
    function dateOf(task) {
        if(task.completed && task.completedDue !== undefined) return task.completedDue;
        if(task.type === 'once') return task.fixed || '';
        if(task.type === 'annual') {
            const year = Number(state.milestones.event_date.slice(0,4) || 2027) + Number(task.yearOffset || 0);
            const date = `${year}-${String(task.month).padStart(2,'0')}-${String(task.day).padStart(2,'0')}`;
            const parsed = new Date(date+'T12:00:00Z');
            return !isNaN(parsed) && parsed.toISOString().slice(0,10) === date ? date : '';
        }
        const base = state.milestones[task.milestone]; if(!base) return '';
        const value = new Date(base+'T12:00:00Z');
        value.setUTCDate(value.getUTCDate() + (task.type === 'relative' ? Number(task.offset || 0) : 0));
        return value.toISOString().slice(0,10);
    }
    function fmt(value, short=false) { return value ? new Date(value+'T12:00:00Z').toLocaleDateString('en-GB',{day:'numeric',month:short?'short':'long',...(short?{}:{year:'numeric'}),timeZone:'UTC'}) : 'Date not set'; }
    function blocked(task, tasks=state.tasks) { return task.pred.some(id => !tasks.find(item=>item.id===id)?.completed); }
    function late(task) { const due=dateOf(task); return !task.completed && due && due<=TODAY; }
    function ownerText(task) { return task.ownerKind==='person' ? people[task.owner]?.name || 'Owner not available' : task.ownerKind==='role' ? `All ${task.owner === 'ExecMember' ? 'ExecMembers' : 'SponsorshipManagers'}` : 'Whole team'; }
    function ruleText(task) {
        if(task.type==='once') return `One-time date · ${fmt(task.fixed)}`;
        if(task.type==='annual') return `Annual · ${task.day} ${new Date(Date.UTC(2000, task.month-1, 1)).toLocaleDateString('en-GB',{month:'long',timeZone:'UTC'})}${Number(task.yearOffset||0)===-1?' · previous year':''}`;
        const label = milestoneLabels[task.milestone] || task.milestone;
        return task.type==='source' ? label : `${Math.abs(task.offset)} days ${task.offset<0?'before':'after'} ${label.toLowerCase()}`;
    }
    function badges(task) {
        if(task.completed) return '<span class="diary-status diary-preview-status-completed">Completed</span>';
        return `<span class="diary-status diary-status-${blocked(task)?'blocked':'ready'}">${blocked(task)?'Blocked':'Ready'}</span>${late(task)?'<span class="diary-status diary-status-late">Late</span>':''}${!dateOf(task)?'<span class="diary-status diary-preview-status-neutral">Date not set</span>':''}`;
    }
    function header(title, subtitle, actions='', eyebrow='Event calendar · 2027') {
        return `<p class="diary-preview-eyebrow">${esc(eyebrow)}</p><header class="diary-preview-header"><div class="diary-preview-header-text"><h1 class="diary-preview-title">${esc(title)}</h1><p class="diary-preview-subtitle">${esc(subtitle)}</p></div><div class="diary-preview-header-actions">${actions}</div></header>`;
    }
    function nav(page) {
        const items = [['mine','☑','My tasks'],['calendar','▦','Calendar'],...(officer()?[['template','▤','Template'],['milestones','◇','Milestones']]:[])];
        $('preview-nav').innerHTML=items.map(([key,icon,label])=>`<a class="diary-preview-nav-link" href="#${key}" ${page===key?'aria-current="page"':''}><span class="diary-preview-nav-icon" aria-hidden="true">${icon}</span><span class="diary-preview-nav-label">${label}</span></a>`).join('');
        $('preview-persona').value=state.persona;
        $('preview-persona-note').textContent=people[state.persona].groups.join(' · ');
    }
    function personal(task) { return (task.ownerKind==='person'&&task.owner===state.persona)||(task.ownerKind==='role'&&people[state.persona].groups.includes(task.owner))||(filters.team&&task.ownerKind==='team'); }
    function taskPage(mine) {
        lastList = mine ? 'mine' : 'calendar';
        const tasks=state.tasks.filter(task=>!mine||personal(task));
        const counts={ready:tasks.filter(t=>!t.completed&&!blocked(t)).length,blocked:tasks.filter(t=>!t.completed&&blocked(t)).length,late:tasks.filter(late).length,completed:tasks.filter(t=>t.completed).length};
        main.innerHTML=header(mine?'My tasks':'Event calendar',mine?`Tasks for ${people[state.persona].name} and their roles.`:`Event day: ${fmt(state.milestones.event_date)} · Calendar from template v1`, '<a class="diary-button diary-button-primary" href="#new">+ Add entry</a>')+
            `<div class="diary-preview-summary">${Object.entries(counts).map(([key,count])=>`<span class="diary-preview-summary-item"><strong class="diary-preview-summary-number">${count}</strong> ${key}</span>`).join('')}</div><div class="diary-preview-toolbar"><input aria-label="Search tasks" class="diary-preview-search" id="task-search" type="search" placeholder="Search tasks" value="${esc(filters.query)}"><select aria-label="Task status" class="diary-preview-filter" id="task-filter">${['open','ready','blocked','late','completed','all'].map(value=>`<option value="${value}" ${filters.state===value?'selected':''}>${value==='open'?'All open tasks':value[0].toUpperCase()+value.slice(1)}</option>`).join('')}</select></div>${mine?`<label class="diary-preview-check-label"><input class="diary-preview-checkbox" type="checkbox" id="include-team" ${filters.team?'checked':''}>Include whole-team tasks</label>`:''}<ul class="diary-preview-list" id="task-rows"></ul><p class="diary-preview-help">A task is late when its due date is today or earlier and it is not complete.</p>`;
        renderRows(mine);
        $('task-search').addEventListener('input', event=>{filters.query=event.target.value;renderRows(mine);});
        $('task-filter').addEventListener('change', event=>{filters.state=event.target.value;renderRows(mine);});
        if(mine) $('include-team').addEventListener('change', event=>{filters.team=event.target.checked;taskPage(true);});
    }
    function renderRows(mine) {
        const tasks=state.tasks.filter(task=>(!mine||personal(task))&&(!filters.query||`${task.name} ${ownerText(task)}`.toLowerCase().includes(filters.query.toLowerCase()))&&
            (filters.state==='all'||filters.state==='completed'&&task.completed||filters.state==='open'&&!task.completed||filters.state==='late'&&late(task)||filters.state==='ready'&&!task.completed&&!blocked(task)||filters.state==='blocked'&&!task.completed&&blocked(task)))
            .sort((a,b)=>Number(Boolean(late(b)))-Number(Boolean(late(a)))||(dateOf(a)||'9999').localeCompare(dateOf(b)||'9999')||a.name.localeCompare(b.name));
        $('task-rows').innerHTML=tasks.length?tasks.map(task=>`<li class="diary-preview-task-row"><div class="diary-preview-date"><span class="diary-preview-date-day">${esc(dateOf(task)?fmt(dateOf(task),true):'—')}</span><span class="diary-preview-date-year">${esc(dateOf(task)?dateOf(task).slice(0,4):'No date')}</span></div><div class="diary-preview-task-content"><a class="diary-preview-task-link" href="#task/${task.id}">${esc(task.name)}</a><p class="diary-preview-task-owner">${esc(ownerText(task))}</p><div class="diary-preview-badges">${badges(task)}</div></div><a class="diary-preview-row-arrow" href="#task/${task.id}" aria-label="Open ${esc(task.name)}">›</a></li>`).join(''):'<li class="diary-preview-empty">No tasks match this view.</li>';
    }
    function dependencyList(ids, tasks=state.tasks) {
        return ids.length?`<ul class="diary-preview-dependency-list">${ids.map(id=>{const task=tasks.find(t=>t.id===id);return `<li class="diary-preview-dependency-item"><a class="diary-preview-task-link" href="#task/${esc(id)}">${esc(task?.name||'Task not available')}</a>${task?`<div class="diary-preview-badges">${badges(task)}</div>`:''}</li>`;}).join('')}</ul>`:'<p class="diary-preview-help">None.</p>';
    }
    function details(id) {
        const task=state.tasks.find(t=>t.id===id);if(!task){main.innerHTML=header('Task not found','Return to the calendar to select a task.');return;}
        const canComplete=officer()||(task.ownerKind==='person'&&task.owner===state.persona)||(task.ownerKind==='role'&&people[state.persona].groups.includes(task.owner));
        const successors=state.tasks.filter(t=>t.pred.includes(id));
        main.innerHTML=`<a class="diary-preview-back" href="#${lastList}">← Back to ${lastList==='mine'?'my tasks':'calendar'}</a>`+header(task.name,ownerText(task),!task.completed&&(officer()||task.owner===state.persona)?`<a class="diary-button" href="#edit/${id}">Edit entry</a>`:'')+
            `<div class="diary-preview-badges">${badges(task)}</div><p class="diary-preview-detail-description">${esc(task.description)}</p><div class="diary-preview-columns"><div class="diary-preview-detail-main"><section class="diary-card"><h2 class="diary-preview-section-title">Task details</h2><dl class="diary-preview-facts"><dt class="diary-preview-fact-name">Due date</dt><dd class="diary-preview-fact-value">${esc(fmt(dateOf(task)))}</dd><dt class="diary-preview-fact-name">Date rule</dt><dd class="diary-preview-fact-value">${esc(ruleText(task))}</dd><dt class="diary-preview-fact-name">Owner</dt><dd class="diary-preview-fact-value">${esc(ownerText(task))}</dd></dl></section><section class="diary-card"><h2 class="diary-preview-section-title">${task.completed?'Completion record':'Complete this task'}</h2>${task.completed?`<p class="diary-preview-completion-record">Completed by ${esc(people[task.completedBy]?.name||'Team member')} on ${fmt(task.completedOn)}.</p><p class="diary-preview-completion-note">${esc(task.completionNote||'No note added.')}</p>`:blocked(task)?`<p class="diary-preview-note diary-preview-warning">This task is blocked. Complete its predecessors first.</p><button type="button" class="diary-button" disabled>Mark as complete</button>`:!canComplete?'<p class="diary-preview-note">This task belongs to another person or the whole team. Use the Officer preview to record completion.</p>':`<form class="diary-preview-completion-form" id="completion-form"><label class="diary-preview-field-label" for="completion-note">Completion note <span class="diary-preview-optional">(optional)</span></label><textarea class="diary-preview-control" id="completion-note" rows="3" placeholder="Record what was done"></textarea><div class="diary-actions"><button class="diary-button diary-button-primary" type="submit">Mark as complete</button></div><p class="diary-preview-help">Preview behavior only. Production completion permissions are still a design decision.</p></form>`}</section></div><aside class="diary-preview-detail-side"><section class="diary-card"><h2 class="diary-preview-section-title">Depends on</h2>${dependencyList(task.pred)}</section><section class="diary-card"><h2 class="diary-preview-section-title">Enables</h2>${dependencyList(successors.map(t=>t.id))}</section></aside></div>`;
        if($('completion-form')) $('completion-form').addEventListener('submit', event=>{event.preventDefault();task.completedDue=dateOf(task);task.completed=true;task.completedBy=state.persona;task.completedOn=TODAY;task.completionNote=$('completion-note').value.trim();persist();details(id);notify('Task completed in the preview. Successor readiness has been updated.');});
    }
    function ownerFields(spec, personalOnly=false) {
        if(personalOnly) return `<input type="hidden" class="diary-preview-hidden-field" name="ownerKind" value="person"><input type="hidden" class="diary-preview-hidden-field" name="owner" value="${state.persona}"><p class="diary-preview-note">Personal entry for ${esc(people[state.persona].name)}. It will not change the template.</p>`;
        return `<div class="diary-preview-field"><label class="diary-preview-field-label" for="owner-kind">Owner type</label><select class="diary-preview-control" id="owner-kind" name="ownerKind">${[['team','Whole team'],['person','Specific ExecMember'],['role','User role']].map(([value,label])=>`<option value="${value}" ${spec.ownerKind===value?'selected':''}>${label}</option>`).join('')}</select></div><div class="diary-preview-field" id="owner-target">${ownerTarget(spec.ownerKind,spec.owner)}</div>`;
    }
    function ownerTarget(kind, owner) {
        if(kind==='team') return '<p class="diary-preview-help">This task is for the whole team.</p>';
        const choices=kind==='person'?Object.entries(people).map(([key,p])=>[key,p.name]):roles.map(role=>[role,role==='ExecMember'?'All ExecMembers':'All SponsorshipManagers']);
        return `<label class="diary-preview-field-label" for="owner-target-select">${kind==='person'?'Person':'Role'}</label><select class="diary-preview-control" id="owner-target-select" name="owner">${choices.map(([key,label])=>`<option value="${key}" ${owner===key?'selected':''}>${esc(label)}</option>`).join('')}</select>`;
    }
    function ruleFields(type, spec) {
        if(type==='once') return `<label class="diary-preview-field-label" for="fixed-date">Due date</label><input class="diary-preview-control" type="date" id="fixed-date" name="fixed" value="${esc(spec.fixed||'2027-06-20')}" required>`;
        if(type==='annual') return `<div class="diary-preview-form-grid"><div class="diary-preview-field"><label class="diary-preview-field-label" for="annual-month">Month</label><select class="diary-preview-control" id="annual-month" name="month">${Array.from({length:12},(_,i)=>`<option value="${i+1}" ${Number(spec.month||6)===i+1?'selected':''}>${new Date(Date.UTC(2000,i,1)).toLocaleDateString('en-GB',{month:'long',timeZone:'UTC'})}</option>`).join('')}</select></div><div class="diary-preview-field"><label class="diary-preview-field-label" for="annual-day">Day</label><input class="diary-preview-control" type="number" id="annual-day" name="day" min="1" max="31" value="${spec.day||1}" required></div><div class="diary-preview-field-wide"><label class="diary-preview-field-label" for="annual-year">Year rule</label><select class="diary-preview-control" id="annual-year" name="yearOffset">${[[-1,'Previous year'],[0,'Event year'],[1,'Following year']].map(([value,label])=>`<option value="${value}" ${Number(spec.yearOffset||0)===value?'selected':''}>${label}</option>`).join('')}</select></div></div>`;
        return `<label class="diary-preview-field-label" for="source-milestone">Milestone</label><select class="diary-preview-control" id="source-milestone" name="milestone">${Object.entries(milestoneLabels).map(([key,label])=>`<option value="${key}" ${(spec.milestone||'event_date')===key?'selected':''}>${esc(label)}</option>`).join('')}</select>${type==='relative'?`<div class="diary-preview-form-grid"><div class="diary-preview-field"><label class="diary-preview-field-label" for="offset-days">Number of days</label><input class="diary-preview-control" type="number" name="days" id="offset-days" min="0" max="3650" value="${Math.abs(spec.offset||0)}" required></div><div class="diary-preview-field"><label class="diary-preview-field-label" for="offset-direction">Direction</label><select class="diary-preview-control" name="direction" id="offset-direction"><option value="after" ${spec.offset>=0?'selected':''}>After milestone</option><option value="before" ${spec.offset<0?'selected':''}>Before milestone</option></select></div></div>`:''}`;
    }
    function excludedIds(id, tasks) {
        const excluded=new Set([id]);let changed=true;
        while(changed){changed=false;for(const task of tasks)if(!excluded.has(task.id)&&task.pred.some(key=>excluded.has(key))){excluded.add(task.id);changed=true;}}
        return excluded;
    }
    function predecessors(spec,tasks) {
        const excluded=excludedIds(spec.id,tasks);const choices=tasks.filter(t=>!excluded.has(t.id));
        return `<label class="diary-preview-field-label" for="predecessor-search">Predecessors</label><input class="diary-preview-control" id="predecessor-search" type="search" placeholder="Find a predecessor"><p class="diary-preview-help">This task and its successors are excluded. Choose none, one, or several.</p><div class="diary-preview-predecessors" id="predecessor-list">${choices.length?choices.map(t=>`<label class="diary-preview-check-label diary-preview-predecessor-choice" data-search="${esc(t.name.toLowerCase())}"><input class="diary-preview-checkbox" type="checkbox" name="pred" value="${t.id}" ${spec.pred.includes(t.id)?'checked':''}><span class="diary-preview-predecessor-name">${esc(t.name)}</span></label>`).join(''):'<p class="diary-preview-help">No available predecessors.</p>'}</div>`;
    }
    function formMarkup(spec,tasks,{template=false,personalOnly=false,readOnly=false}={}) {
        return `<form class="diary-preview-entry-form" id="entry-form"><fieldset class="diary-preview-fieldset" ${readOnly?'disabled':''}><div class="diary-preview-form-grid"><div class="diary-preview-field-wide"><label class="diary-preview-field-label" for="entry-name">Task name</label><input class="diary-preview-control" id="entry-name" name="name" value="${esc(spec.name)}" maxlength="160" required></div><div class="diary-preview-field-wide"><label class="diary-preview-field-label" for="entry-description">Description</label><textarea class="diary-preview-control" id="entry-description" name="description" rows="2">${esc(spec.description)}</textarea></div>${ownerFields(spec,personalOnly)}<div class="diary-preview-field-wide"><label class="diary-preview-field-label" for="date-type">Date type</label><select class="diary-preview-control" id="date-type" name="type">${[['relative','Days before or after a milestone'],['source','On a milestone date'],['annual','Fixed annual date'],...(!template?[['once','One-time date']]:[])].map(([key,label])=>`<option value="${key}" ${spec.type===key?'selected':''}>${label}</option>`).join('')}</select><div class="diary-preview-rule-fields" id="rule-fields">${ruleFields(spec.type,spec)}</div></div>${!personalOnly?`<div class="diary-preview-field-wide">${predecessors(spec,tasks)}</div>`:''}${!template&&officer()&&!spec.existing?'<div class="diary-preview-field-wide"><label class="diary-preview-check-label"><input class="diary-preview-checkbox" type="checkbox" name="addTemplate">Also add to the template draft for future events</label></div>':''}</div><p class="diary-preview-error" id="form-error" role="alert" hidden></p><div class="diary-actions">${!readOnly?`<button type="submit" class="diary-button diary-button-primary">${template?'Save draft entry':'Save entry'}</button>`:''}<a class="diary-button" href="#${template?'template':lastList}">${readOnly?'Back':'Cancel'}</a></div></fieldset></form>`;
    }
    function readForm(form,spec) {
        const data=new FormData(form);const type=data.get('type');
        const result={id:spec.id,name:String(data.get('name')).trim(),description:String(data.get('description')).trim(),type,ownerKind:String(data.get('ownerKind')),owner:String(data.get('owner')||''),pred:data.getAll('pred')};
        if(result.ownerKind==='team')result.owner='';
        if(type==='once')result.fixed=String(data.get('fixed'));
        if(type==='annual'){result.month=Number(data.get('month'));result.day=Number(data.get('day'));result.yearOffset=Number(data.get('yearOffset'));const test=new Date(Date.UTC(2000,result.month-1,result.day));if(test.getUTCMonth()!==result.month-1)throw Error('Select a valid month and day.');}
        if(type==='source'||type==='relative')result.milestone=String(data.get('milestone'));
        if(type==='relative')result.offset=Number(data.get('days'))*(data.get('direction')==='before'?-1:1);
        return {result,addTemplate:data.get('addTemplate')==='on'};
    }
    function bindForm(spec,tasks,onSave) {
        const form=$('entry-form');const type=$('date-type');type.addEventListener('change',()=>{$('rule-fields').innerHTML=ruleFields(type.value,spec);});
        if($('owner-kind'))$('owner-kind').addEventListener('change',event=>{$('owner-target').innerHTML=ownerTarget(event.target.value,'');});
        if($('predecessor-search'))$('predecessor-search').addEventListener('input',event=>{document.querySelectorAll('.diary-preview-predecessor-choice').forEach(label=>{label.hidden=!label.querySelector('input').checked&&!label.dataset.search.includes(event.target.value.toLowerCase());});});
        form.addEventListener('submit',event=>{event.preventDefault();try{const {result,addTemplate}=readForm(form,spec);if(!result.name)throw Error('Enter a task name.');if(tasks.some(t=>t.id!==spec.id&&t.name.toLowerCase()===result.name.toLowerCase()))throw Error('Use a unique task name.');const excluded=excludedIds(spec.id,tasks);if(result.pred.some(id=>excluded.has(id)))throw Error('The predecessor list has changed. Select available tasks.');if(addTemplate&&result.type==='once')throw Error('Select an annual date or milestone rule before adding this task to the template.');onSave(result,addTemplate);}catch(error){$('form-error').textContent=error.message;$('form-error').hidden=false;}});
    }
    function editEntry(id) {
        const existing=id?state.tasks.find(t=>t.id===id):null;
        if(id&&!existing){go(lastList);return;}
        if(existing&&(existing.completed||(!officer()&&!(existing.ownerKind==='person'&&existing.owner===state.persona)))){main.innerHTML=header('Entry cannot be edited','Use the calendar to inspect this entry.');return;}
        const spec=existing?{...clone(existing),existing:true}:{id:`t${state.nextId}`,name:'',description:'',type:'relative',milestone:'event_date',offset:-7,ownerKind:officer()?'team':'person',owner:officer()?'':state.persona,pred:[]};
        main.innerHTML=`<a class="diary-preview-back" href="#${lastList}">← Back to ${lastList==='mine'?'my tasks':'calendar'}</a>`+header(existing?'Edit entry':officer()?'Add calendar entry':'Add personal entry','Changes apply to this preview only.')+`<div class="diary-card">${formMarkup(spec,state.tasks,{personalOnly:!officer()})}</div>`;
        bindForm(spec,state.tasks,(result,addTemplate)=>{if(addTemplate&&(state.draft||state.approved).some(t=>t.name.toLowerCase()===result.name.toLowerCase()))throw Error('That name already exists in the template draft.');if(addTemplate&&result.pred.some(id=>!(state.draft||state.approved).some(t=>t.id===id)))throw Error('A selected predecessor is not in the template. Add it to the template first, or save this entry without the template option.');if(!officer())result.pred=clone(spec.pred);if(existing)state.tasks[state.tasks.findIndex(t=>t.id===id)]=result;else{state.tasks.push(result);state.nextId++;}if(addTemplate){if(!state.draft)state.draft=clone(state.approved);state.draft.push({...clone(result),pred:result.pred.filter(id=>state.draft.some(t=>t.id===id))});}persist();go(`task/${result.id}`);notify(addTemplate?'Entry saved. The template draft also has a new entry.':'Entry saved in the preview.');});
    }
    function requireOfficer(){if(officer())return true;main.innerHTML=header('Officer view','This page is available to Officers. Switch the preview role to inspect it.');return false;}
    function templates() {
        if(!requireOfficer())return;
        if(versionSelection==='draft'&&!state.draft)versionSelection='approved';
        const tasks=versionSelection==='draft'?state.draft:state.approved;let selected=tasks.find(t=>t.id===templateSelection)||tasks[0];if(selected)templateSelection=selected.id;
        const readOnly=versionSelection==='approved';
        main.innerHTML=header('Calendar template','Standard event preparation · Changes to the template do not change the current event.',!readOnly?'<button class="diary-button diary-button-primary" type="button" data-action="approve">Approve draft</button>':'<button class="diary-button diary-button-primary" type="button" data-action="new-draft">Create new draft</button>','Officer workspace')+
            `<div class="diary-preview-toolbar"><label class="diary-preview-field-label" for="template-version">Version</label><select class="diary-preview-control diary-preview-template-switch" id="template-version"><option value="approved" ${readOnly?'selected':''}>Version ${state.approvedNumber} · Approved</option>${state.draft?`<option value="draft" ${!readOnly?'selected':''}>Version ${state.approvedNumber+1} · Draft</option>`:''}</select>${readOnly?'<span class="diary-status diary-preview-status-neutral">Read-only</span>':'<button type="button" class="diary-button" data-action="new-template-task">+ Add template entry</button>'}</div><p class="diary-preview-note">${readOnly?'This version is approved. Create a draft to make changes.':'This draft is for future calendars. Save each entry before selecting another task.'}</p><div class="diary-preview-editor"><aside class="diary-preview-template-list">${tasks.map(task=>`<button class="diary-preview-template-task" type="button" data-template-task="${task.id}" aria-pressed="${task.id===templateSelection}">${esc(task.name)}<span class="diary-preview-rule-caption">${esc(ruleText(task))}</span></button>`).join('')}</aside><section class="diary-card diary-preview-editor-card">${selected?`<h2 class="diary-preview-section-title">${readOnly?'Template entry':'Edit template entry'}</h2>${formMarkup(selected,tasks,{template:true,readOnly})}`:'<p class="diary-preview-empty">Add the first template entry.</p>'}</section></div><details class="diary-card"><summary class="diary-preview-graph-title">Inspect dependency connections</summary><div class="diary-preview-graph">${tasks.map(task=>`<div class="diary-preview-graph-row"><strong class="diary-preview-graph-task">${esc(task.name)}</strong><span class="diary-preview-graph-edge"> ← ${task.pred.length?esc(task.pred.map(id=>tasks.find(t=>t.id===id)?.name||'Missing task').join(' + ')):'No predecessors'}</span></div>`).join('')}</div></details>`;
        $('template-version').addEventListener('change',event=>{versionSelection=event.target.value;templates();});
        document.querySelectorAll('[data-template-task]').forEach(button=>button.addEventListener('click',()=>{templateSelection=button.dataset.templateTask;templates();}));
        if(selected&&!readOnly)bindForm(selected,tasks,result=>{state.draft[state.draft.findIndex(t=>t.id===result.id)]=result;persist();templates();notify('Template draft saved. The current event is unchanged.');});
    }
    function milestones() {
        if(!requireOfficer())return;
        const required=[...new Set(state.approved.filter(t=>t.type==='relative'||t.type==='source').map(t=>t.milestone))];
        main.innerHTML=header('Milestone dates','Set the dates that this event calendar needs.','', 'Officer workspace')+`<p class="diary-preview-note">The approved template uses ${required.length} named milestones. Tasks use these dates to calculate their due dates.</p><form class="diary-card diary-preview-milestone-form" id="milestone-form">${required.map(key=>`<div class="diary-preview-milestone-row"><div class="diary-preview-milestone-description"><label class="diary-preview-field-label" for="milestone-${key}">${esc(milestoneLabels[key]||key)}</label><code class="diary-preview-milestone-key">${esc(key)}</code><p class="diary-preview-help">Used by ${state.approved.filter(t=>t.milestone===key).length} template entries</p></div><input class="diary-preview-control" type="date" id="milestone-${key}" name="${key}" value="${esc(state.milestones[key]||'')}" ${key==='event_date'?'required':''}></div>`).join('')}<div class="diary-actions"><button type="submit" class="diary-button diary-button-primary">Save milestone dates</button><a class="diary-button" href="#calendar">Cancel</a></div></form>`;
        $('milestone-form').addEventListener('submit',event=>{event.preventDefault();const data=new FormData(event.target);for(const [key,value]of data)state.milestones[key]=String(value);persist();notify('Milestone dates saved. Open task dates have been recalculated.');});
    }
    function render() {
        const [requested,id]=(location.hash.slice(1)||'mine').split('/');const page=['mine','calendar','task','new','edit','template','milestones'].includes(requested)?requested:'mine';nav(page);document.title=`Diary · ${page==='mine'?'My tasks':page==='template'?'Template':page==='milestones'?'Milestones':page==='task'?'Task details':'Calendar'} preview`;
        if(page==='mine')taskPage(true);else if(page==='task')details(id);else if(page==='new')editEntry();else if(page==='edit')editEntry(id);else if(page==='template')templates();else if(page==='milestones')milestones();else taskPage(false);
    }
    $('preview-persona').addEventListener('change',event=>{state.persona=event.target.value;filters={query:'',state:'open',team:false};persist();go('mine');});
    document.addEventListener('click',event=>{
        const action=event.target.closest('[data-action]')?.dataset.action;if(!action)return;
        if(action==='reset'){state=initial();filters={query:'',state:'open',team:false};versionSelection='draft';templateSelection='t1';persist();go('mine');notify('Sample data reset.');}
        if(!officer()&&action!=='reset')return;
        if(action==='approve'&&state.draft){state.approved=clone(state.draft);state.approvedNumber++;state.draft=null;versionSelection='approved';persist();templates();notify('Template approved in the preview. Existing event tasks are unchanged.');}
        if(action==='new-draft'){state.draft=clone(state.approved);versionSelection='draft';persist();templates();}
        if(action==='new-template-task'&&state.draft){const task={id:`t${state.nextId++}`,name:`New template task ${state.nextId-1}`,description:'',type:'relative',milestone:'event_date',offset:0,ownerKind:'team',owner:'',pred:[]};state.draft.push(task);templateSelection=task.id;persist();templates();}
    });
    window.addEventListener('hashchange',()=>{render();main.focus({preventScroll:true});window.scrollTo(0,0);});
    render();
})();
