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
    const clone = value => JSON.parse(JSON.stringify(value));
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
    function dueDate(task, state) {
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

    /** Return one status category for a sample task under DV1-020 and DV1-049. */
    function taskBucket(task, state) {

        // Completed tasks cannot contribute to open-task counts.
        if(task.completed) return 'completed';
        const due = dueDate(task, state);

        // Late has priority even when an unfinished predecessor also blocks the task.
        if(due && due <= TODAY) return 'late';

        // An unfinished or missing predecessor prevents the remaining task from being ready.
        return task.pred.some(id => !state.tasks.find(item => item.id === id)?.completed) ? 'blocked' : 'ready';
    }
    function taskHighlight(task, state) {
        if(task.completed) return '';
        const due = dueDate(task, state);
        if(due && due <= TODAY) return 'late';
        return task.pred.some(id => {
            const predecessor = state.tasks.find(item => item.id === id);
            const predecessorDue = predecessor && dueDate(predecessor, state);
            return predecessor && !predecessor.completed && predecessorDue && predecessorDue <= TODAY;
        }) ? 'blocked-late' : task.pred.some(id => !state.tasks.find(item => item.id === id)?.completed) ? 'blocked' : '';
    }
    function load() { try { return JSON.parse(sessionStorage.getItem(STORE)) || initial(); } catch { return initial(); } }
    function persist(state) { try { sessionStorage.setItem(STORE, JSON.stringify(state)); } catch { /* Use memory when storage is unavailable. */ } }
    window.DiaryPreviewData = Object.freeze({TODAY, people, roles, milestoneLabels, initial, dueDate, taskBucket, taskHighlight, load, persist});
})();
