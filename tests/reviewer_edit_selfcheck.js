const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const reviewCheckbox = { checked: true, disabled: false };
const statusBadge = { className: '', textContent: '' };
const statusHelp = { textContent: '' };
let requestedUrl = '';
let requestedPayload = null;
let requestStarted = false;
let reopenedSubmissionId = null;
let nextSubmissionStatus = 'pending_input_confirmation';
const alerts = [];

const sandbox = {
    console,
    URL,
    URLSearchParams,
    window: {
        location: { origin: 'http://localhost', pathname: '/index.html', search: '' },
        reviewEditMode: true,
        reviewApproved: false,
    },
    currentEditingId: 71,
    document: {
        querySelectorAll() { return []; },
        getElementById(id) {
            if (id === 'reviewConfirmCheckbox') return reviewCheckbox;
            if (id === 'reviewConfirmationStatusBadge') return statusBadge;
            if (id === 'reviewConfirmationHelp') return statusHelp;
            return null;
        },
    },
    collectSubmissionFormData: () => ({ col_8: 'Nội dung đã sửa' }),
    async authFetch(url, options) {
        requestStarted = true;
        requestedUrl = url;
        requestedPayload = JSON.parse(options.body);
        return {
            ok: true,
            async json() {
                return { status: 'ok', submission_status: nextSubmissionStatus, is_checked: true };
            },
        };
    },
    formatApiErrorDetail: value => String(value),
    alert(message) { alerts.push(message); },
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/admin_panel.js', 'utf8'), sandbox);
sandbox.editSubmission = async id => { reopenedSubmissionId = id; };

(async () => {
    sandbox.updateReviewConfirmationStatus('pending', true);
    assert.equal(statusBadge.textContent, 'Chưa kiểm duyệt');
    assert.equal(reviewCheckbox.checked, false);
    assert.equal(reviewCheckbox.disabled, false);

    reviewCheckbox.checked = true;
    const confirmPromise = sandbox.confirmReviewSubmission(reviewCheckbox);
    await Promise.resolve();
    assert.equal(requestStarted, true);
    assert.equal(statusBadge.textContent, 'Đang lưu...');
    await confirmPromise;

    assert.equal(requestedUrl, '/api/submissions/71/confirm-review');
    assert.deepEqual(requestedPayload, {
        data: { col_8: 'Nội dung đã sửa' },
    });
    assert.equal(sandbox.window.reviewApproved, true);
    assert.equal(sandbox.window.reviewEditMode, false);
    assert.equal(reopenedSubmissionId, 71);
    assert.match(alerts.at(-1), /chuyển cho người nhập xác nhận/);

    sandbox.updateReviewConfirmationStatus('confirmed', false);
    assert.equal(statusBadge.textContent, 'Đã kiểm duyệt');
    assert.equal(reviewCheckbox.checked, true);
    assert.equal(reviewCheckbox.disabled, true);

    nextSubmissionStatus = 'completed';
    reviewCheckbox.checked = true;
    await sandbox.confirmReviewSubmission(reviewCheckbox);
    assert.equal(statusBadge.textContent, 'Hoàn thành');
    assert.match(statusHelp.textContent, /không thay đổi nội dung/);
    assert.match(alerts.at(-1), /không có thay đổi và đã hoàn thành/);

    const indexHtml = fs.readFileSync('frontend/index.html', 'utf8');
    const panelSource = fs.readFileSync('frontend/js/admin_panel.js', 'utf8');
    const rendererSource = fs.readFileSync('frontend/js/form_renderer.js', 'utf8');
    assert(indexHtml.includes('id="reviewConfirmCheckbox"'));
    assert(indexHtml.includes('id="reviewConfirmationStatusBadge"'));
    assert(!indexHtml.includes('id="adminFormCheckToggle"'));
    assert(!panelSource.includes('toggleFormCheck'));
    assert(!panelSource.includes('Lưu nội dung đã sửa'));
    assert(!panelSource.includes('window.reviewErrorSavePromise'));
    assert(!rendererSource.includes('review-field-error-check'));
    assert(!rendererSource.includes('field-error-checkbox'));
    assert(!rendererSource.includes('error_cat_'), 'Không còn checkbox lỗi chung cho cả nhóm');
    console.log('Reviewer confirmation self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
