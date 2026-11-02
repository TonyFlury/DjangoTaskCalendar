'use strict';
(() => {
    const fixture=window.DiaryPreviewData;
    const $=id=>document.getElementById(id);
    const esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    function diaryLink(person,filter='open') {
        return `../ui/index.html?previewAs=${encodeURIComponent(person)}&taskStatus=${encodeURIComponent(filter)}#mine`;
    }
    function render() {
        const person=$('dashboard-preview-person').value;
        const enabled=$('dashboard-preview-enabled').checked;
        const panel=$('diary-dashboard-panel');
        $('dashboard-preview-user-label').textContent=fixture.people[person].name;
        $('dashboard-preview-diary-nav').href=diaryLink(person);
        $('dashboard-preview-diary-nav').hidden=!enabled;
        panel.hidden=!enabled;
        if(!enabled){panel.replaceChildren();return;}
        const state=fixture.load();
        const member=fixture.people[person];
        const tasks=state.tasks.filter(task=>!task.completed&&(
            task.ownerKind==='person'&&task.owner===person||task.ownerKind==='role'&&member.groups.includes(task.owner)));
        const ready=tasks.filter(task=>task.pred.every(id=>state.tasks.find(item=>item.id===id)?.completed)).length;
        const late=tasks.filter(task=>{const due=fixture.dueDate(task,state);return due&&due<=fixture.TODAY;}).length;
        panel.innerHTML=`<div class="diary-dashboard-header"><div class="diary-dashboard-heading"><div class="diary-dashboard-eyebrow">Your tasks</div><h2 class="diary-dashboard-title" id="diary-dashboard-title">My Diary</h2><p class="diary-dashboard-user">${esc(member.name)} · Personal and role-owned tasks</p></div><a class="diary-dashboard-open" href="${diaryLink(person)}">Open My tasks ↗</a></div><div class="diary-dashboard-counts"><a class="diary-dashboard-counter diary-dashboard-counter-late" href="${diaryLink(person,'late')}" aria-label="${late} late tasks for ${esc(member.name)}"><span class="diary-dashboard-counter-value">${late}</span><span class="diary-dashboard-counter-label">Late</span><span class="diary-dashboard-counter-description">Due today or earlier</span><span class="diary-dashboard-counter-arrow" aria-hidden="true">↗</span></a><a class="diary-dashboard-counter diary-dashboard-counter-ready" href="${diaryLink(person,'ready')}" aria-label="${ready} ready tasks for ${esc(member.name)}"><span class="diary-dashboard-counter-value">${ready}</span><span class="diary-dashboard-counter-label">Ready</span><span class="diary-dashboard-counter-description">No unfinished predecessors</span><span class="diary-dashboard-counter-arrow" aria-hidden="true">↗</span></a></div><p class="diary-dashboard-footer">A ready task can also be late. Completed and whole-team tasks are not included.</p>`;
    }
    $('dashboard-preview-person').addEventListener('change',render);
    $('dashboard-preview-enabled').addEventListener('change',render);
    $('dashboard-preview-event-form').addEventListener('submit',event=>event.preventDefault());
    window.addEventListener('pageshow',render);
    render();
})();
