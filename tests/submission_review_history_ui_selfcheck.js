const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('frontend/index.html', 'utf8');
const css = fs.readFileSync('frontend/index-page.css', 'utf8');
const rendererSource = fs.readFileSync('frontend/js/form_renderer.js', 'utf8');
const submissionSource = fs.readFileSync('frontend/js/submission.js', 'utf8');

assert(html.includes('id="submissionUnreadBadge"'));
assert(html.includes('id="submissionQualityLegend"'));
assert(!/id="submissionUnreadBadge"[^>]+onclick=/i.test(html));
assert(css.includes('.review-history-changed-field .form-control'));
assert(css.includes('border-color: #dc3545'));
assert(css.includes('.review-history-corrected-field .form-control'));
assert(css.includes('border-color: #198754'));
assert(submissionSource.includes('response.unread_review_count'));
assert(submissionSource.includes('/input-confirmation'));
assert(submissionSource.includes("window.addEventListener('load'"));

function classList(initial = []) {
    const values = new Set(initial);
    return {
        add(...names) { names.forEach(name => values.add(name)); },
        remove(...names) { names.forEach(name => values.delete(name)); },
        toggle(name, force) {
            if (force === true) values.add(name);
            else if (force === false) values.delete(name);
            else if (values.has(name)) values.delete(name);
            else values.add(name);
        },
        contains(name) { return values.has(name); },
    };
}

const redGroup = { classList: classList() };
const greenGroup = { classList: classList() };
const legend = { classList: classList(['d-none']) };
const rendererSandbox = {
    console,
    currentUser: { id: 2 },
    localStorage: { getItem() { return null; }, removeItem() {} },
    window: { activeTemplateId: 1 },
    document: {
        querySelectorAll(selector) {
            return selector.includes('review-history-') ? [redGroup, greenGroup] : [];
        },
        getElementById(id) {
            if (id === 'col_0') return { closest: () => redGroup };
            if (id === 'col_1') return { closest: () => greenGroup };
            if (id === 'submissionQualityLegend') return legend;
            return null;
        },
    },
};
vm.createContext(rendererSandbox);
vm.runInContext(rendererSource, rendererSandbox);
rendererSandbox.applySubmissionQualityFieldStyles({
    reviewed_changes: ['col_0', 'col_1'],
    corrected_fields: ['col_1'],
});
assert(redGroup.classList.contains('review-history-changed-field'));
assert(!greenGroup.classList.contains('review-history-changed-field'));
assert(greenGroup.classList.contains('review-history-corrected-field'));
assert(!legend.classList.contains('d-none'));

let requestedUrl = '';
let requestedBody = null;
let reopenedId = null;
const alerts = [];
const draftButton = { disabled: false };
const correctionInput = { value: 'đã sửa' };
const submissionSandbox = {
    console,
    currentEditingId: 44,
    document: {
        getElementById(id) {
            if (id === 'draftBtn') return draftButton;
            if (id === 'col_0') return correctionInput;
            return null;
        },
    },
    alert(message) { alerts.push(message); },
    formatApiErrorDetail: String,
    async authFetch(url, options) {
        requestedUrl = url;
        requestedBody = JSON.parse(options.body);
        return { ok: true, async json() { return { status: 'ok' }; } };
    },
};
submissionSandbox.window = submissionSandbox;
submissionSandbox.window.inputCorrectionFields = ['col_0'];
submissionSandbox.window.editSubmission = async id => { reopenedId = id; };
vm.createContext(submissionSandbox);
vm.runInContext(submissionSource, submissionSandbox);

(async () => {
    await submissionSandbox.submitInputCorrection();
    assert.equal(requestedUrl, '/api/submissions/44/input-confirmation');
    assert.deepEqual(requestedBody, { data: { col_0: 'đã sửa' } });
    assert.equal(reopenedId, 44);
    assert.equal(draftButton.disabled, false);
    assert(alerts.some(message => message.includes('hoàn thành')));
    console.log('submission review history UI self-check passed');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
