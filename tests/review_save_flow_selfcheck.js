const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const draftButton = { disabled: false };
const submitButton = { disabled: false };
let nextStatus = 'completed';
let requestedUrl = '';
let requestedPayload = null;
let reopenedSubmissionId = null;
const alerts = [];
const formInput = { name: 'col_8', value: 'Nội dung kiểm tra' };

const sandbox = {
    console,
    currentEditingId: 71,
    iframeCurrentIndex: -1,
    uploadedFilesQueue: [],
    isEditingFromList: true,
    window: {
        reviewEditMode: true,
        reviewApproved: false,
        pdfLinkState: { isLinked: () => false },
        activeTemplateConfig: {},
    },
    document: {
        getElementById(id) {
            if (id === 'draftBtn') return draftButton;
            if (id === 'submitBtn') return submitButton;
            return null;
        },
        querySelectorAll(selector) {
            return selector.startsWith('#dataForm') ? [formInput] : [];
        },
    },
    submissionLeaseHeaders: headers => ({ ...headers, 'X-Submission-Lease-Token': 'lease' }),
    async authFetch(url, options) {
        requestedUrl = url;
        requestedPayload = JSON.parse(options.body);
        return {
            ok: true,
            async json() {
                return { status: 'ok', submission_status: nextStatus, is_checked: true };
            },
        };
    },
    updateReviewConfirmationStatus() {},
    async editSubmission(id) { reopenedSubmissionId = id; },
    formatApiErrorDetail: value => String(value),
    alert(message) { alerts.push(message); },
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/submission.js', 'utf8'), sandbox);

(async () => {
    await sandbox.submitData('draft');
    assert.equal(requestedUrl, '/api/submissions/71/confirm-review');
    assert.deepEqual(requestedPayload, { data: { col_8: 'Nội dung kiểm tra' } });
    assert.equal(sandbox.window.reviewApproved, true);
    assert.equal(sandbox.window.reviewEditMode, false);
    assert.equal(reopenedSubmissionId, 71);
    assert.match(alerts.at(-1), /không có thay đổi và đã hoàn thành/);

    nextStatus = 'pending_input_confirmation';
    sandbox.window.reviewEditMode = true;
    sandbox.window.reviewApproved = false;
    await sandbox.submitData('draft');
    assert.equal(requestedUrl, '/api/submissions/71/confirm-review');
    assert.equal(sandbox.window.reviewApproved, true);
    assert.equal(sandbox.window.reviewEditMode, false);
    assert.match(alerts.at(-1), /chuyển cho người nhập kiểm tra lại/);

    console.log('Review save flow self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
