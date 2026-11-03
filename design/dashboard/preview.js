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
        const counts=Object.fromEntries(['late','ready','blocked'].map(bucket=>[bucket,tasks.filter(task=>fixture.taskBucket(task,state)===bucket).length]));
        const descriptions={late:'Incomplete and due today or earlier, including blocked tasks',ready:'Not late and no unfinished predecessors',blocked:'Not late and waiting for predecessors'};
        panel.innerHTML=`<div class="diary-dashboard-header"><h2 class="diary-dashboard-title" id="diary-dashboard-title">My Diary</h2><span class="diary-dashboard-user">${esc(member.name)}</span></div><div class="diary-dashboard-counts">${Object.entries(counts).map(([bucket,count])=>`<a class="diary-dashboard-counter diary-dashboard-counter-${bucket}" href="${diaryLink(person,bucket)}" title="${descriptions[bucket]}" aria-label="${count} ${bucket} tasks for ${esc(member.name)}. ${descriptions[bucket]}"><span class="diary-dashboard-counter-value">${count}</span><span class="diary-dashboard-counter-label">${bucket[0].toUpperCase()+bucket.slice(1)}</span></a>`).join('')}</div><a class="diary-dashboard-open" href="${diaryLink(person)}" aria-label="Open all my Diary tasks">Open Diary ↗</a>`;

    }
    $('dashboard-preview-person').addEventListener('change',render);
    $('dashboard-preview-enabled').addEventListener('change',render);
    $('dashboard-preview-event-form').addEventListener('submit',event=>event.preventDefault());
    window.addEventListener('pageshow',render);
    render();
})();
