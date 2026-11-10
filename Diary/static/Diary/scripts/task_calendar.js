/* DFUT-018: Dialogs enhance server-rendered calendar links; no task data is cached. */
(() => {
    'use strict';
    for (const root of document.querySelectorAll('.diary-task-calendar')) {
        const help = root.querySelector('#diary-calendar-help-dialog');
        if (!help || typeof help.showModal !== 'function') continue;
        for (const [contentSelector, dialogSelector, buttonSelector] of [
            ['.diary-calendar-filters-content', '#diary-calendar-filter-dialog', '.diary-calendar-filters-open'],
            ['.diary-calendar-help-content', '#diary-calendar-help-dialog', '.diary-calendar-help-open'],
        ]) {
            const content = root.querySelector(contentSelector), dialog = root.querySelector(dialogSelector);
            const button = root.querySelector(buttonSelector);
            dialog.append(content); button.hidden = false;
            let values = [];
            button.addEventListener('click', () => {
                values = Array.from(dialog.querySelectorAll('input, select'), input => [input, input.value, input.checked]);
                dialog.showModal();
            });
            dialog.addEventListener('close', () => {
                for (const [input, value, checked] of values) { input.value = value; input.checked = checked; }
                button.focus();
            });
        }
        for (const button of root.querySelectorAll('[data-calendar-close]')) {
            button.hidden = false;
            button.addEventListener('click', () => button.closest('dialog').close());
        }
        const panel = root.querySelector('.diary-calendar-day-panel');
        if (panel) {
            const dialog = root.querySelector('.diary-calendar-task-day-dialog');
            dialog.append(panel);
            const heading = panel.querySelector('h2');
            dialog.setAttribute('aria-labelledby', heading.id);
            const close = panel.querySelector('[data-calendar-close-link]');
            dialog.addEventListener('cancel', event => { event.preventDefault(); window.location.assign(close.href); });
            dialog.showModal();
        }
    }
})();
