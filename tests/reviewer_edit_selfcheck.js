const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const formInputs = [{ name: 'col_8', value: 'Nội dung đã sửa' }];
const errorCheckboxes = [
    { checked: true, dataset: { field: 'col_8' } },
    { checked: false, dataset: { field: 'col_9' } },
];
let requestedUrl = '';
let requestedPayload = null;
let requestStarted = false;
let releaseErrorSave;

const sandbox = {
    console,
    window: {
        reviewEditMode: true,
        activeTemplateId: 1,
        reviewErrorSavePromise: new Promise(resolve => {
            releaseErrorSave = resolve;
        }),
    },
    currentEditingId: 71,
    isEditingFromList: true,
    iframeCurrentIndex: -1,
    uploadedFilesQueue: [],
    document: {
        querySelectorAll(selector) {
            if (selector === '#dataForm input[type="text"], #dataForm textarea, #dataForm select') return formInputs;
            if (selector === '.field-error-checkbox') return errorCheckboxes;
            if (selector === '.field-error-checkbox:checked') {
                return errorCheckboxes.filter(checkbox => checkbox.checked);
            }
            return [];
        },
        getElementById() { return null; },
    },
    async authFetch(url, options) {
        requestStarted = true;
        requestedUrl = url;
        requestedPayload = JSON.parse(options.body);
        return { ok: true, async json() { return { status: 'ok' }; } };
    },
    formatApiErrorDetail: value => String(value),
    alert() {},
    async editSubmission() {},
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/pdf_link_state.js', 'utf8'), sandbox);
vm.runInContext(fs.readFileSync('frontend/js/submission.js', 'utf8'), sandbox);

(async () => {
    const savePromise = vm.runInContext("submitData('draft')", sandbox);
    await Promise.resolve();
    assert.equal(
        requestStarted,
        false,
        'Lưu nội dung phải chờ thao tác tự lưu dấu lỗi đang chạy để tránh ghi đè dữ liệu',
    );

    releaseErrorSave();
    await savePromise;

    assert.equal(requestedUrl, '/api/submissions/71/review-content');
    assert.deepEqual(requestedPayload, {
        data: { col_8: 'Nội dung đã sửa' },
        wrong_fields: ['col_8'],
    });

    const panelSource = fs.readFileSync('frontend/js/admin_panel.js', 'utf8');
    const rendererSource = fs.readFileSync('frontend/js/form_renderer.js', 'utf8');
    assert(panelSource.includes('window.reviewErrorSavePromise'));
    assert(panelSource.includes('Lưu nội dung đã sửa'));
    assert(rendererSource.includes('review-field-error-check'));
    assert(rendererSource.includes('field-error-checkbox'));
    assert(rendererSource.includes('checkbox.dataset.field = field.name'));
    assert(!rendererSource.includes('error_cat_'), 'Không còn checkbox lỗi chung cho cả nhóm');
    console.log('Reviewer edit self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
