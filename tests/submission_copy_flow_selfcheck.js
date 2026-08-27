const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const adminSandbox = {
    console,
    window: {},
    uploadedFilesQueue: [],
    normalizeQueuePath(value) { return String(value || '').replace(/\\/g, '/'); },
    confirm() { return true; },
    document: { getElementById() { return null; }, querySelectorAll() { return []; } },
};
vm.createContext(adminSandbox);
vm.runInContext(fs.readFileSync('frontend/js/admin_panel.js', 'utf8'), adminSandbox);

const queue = [
    { uuid: 'first', relative_path: 'A/001.pdf', project_id: 1, case_id: 10, template_id: 5, completed: true },
    { uuid: 'other-project', relative_path: 'A/000.pdf', project_id: 2, case_id: 10, template_id: 5, completed: false },
    { uuid: 'eligible', relative_path: 'B/002.pdf', project_id: 1, case_id: 10, template_id: 5, completed: false },
    { uuid: 'other-case', relative_path: 'C/001.pdf', project_id: 1, case_id: 11, template_id: 5, completed: false },
    { uuid: 'source', relative_path: 'Z/999.pdf', project_id: 1, case_id: 10, template_id: 5, completed: true },
];
const sourceSubmission = { template_id: 5, data: { _pdf_uuid: 'source' } };
assert.equal(
    vm.runInContext('findNextCopyPdfQueueIndex', adminSandbox)(sourceSubmission, queue),
    2,
    'PDF cuối phải quay về đầu, bỏ PDF đã nhập và bỏ tài liệu ngoài phạm vi',
);
assert.equal(
    vm.runInContext('findNextCopyPdfQueueIndex', adminSandbox)(
        sourceSubmission,
        queue.map(file => ({ ...file, completed: true })),
    ),
    -1,
    'Không có PDF chưa nhập phù hợp phải trả về -1',
);

let copiedId = null;
let copyApiCalls = 0;
adminSandbox.apiCall = async () => { copyApiCalls++; return {}; };
adminSandbox.editSubmission = async (id, copied) => { copiedId = [id, copied]; };
vm.runInContext('copySubmission(41)', adminSandbox).then(() => {
    assert.deepEqual(copiedId, [41, true]);
    assert.equal(copyApiCalls, 0, 'Nhấn nhân bản không được tạo báo cáo qua API /copy');
}).catch(error => {
    console.error(error);
    process.exitCode = 1;
});

const inputs = [
    { name: 'col_0', value: 'case-a/target.pdf' },
    { name: 'col_1', value: 'Nội dung nguồn' },
];
let requestedPayload = null;
const alerts = [];
const submissionSandbox = {
    console,
    window: {
        activeTemplateId: 5,
        activeTemplateConfig: { linked_pdf_path: { enabled: true, col: 1, folder_levels: 1 } },
        isCopiedSubmissionEdit: true,
        originalEditingData: { col_0: 'case-a/source.pdf', col_1: 'Nội dung nguồn' },
        copySourceSubmissionId: 41,
        reviewEditMode: false,
        pdfLinkState: { isLinked() { return true; } },
    },
    currentEditingId: null,
    isEditingFromList: false,
    iframeCurrentIndex: 0,
    uploadedFilesQueue: [{
        name: 'target.pdf',
        uuid: 'target-uuid',
        url: '/api/files/target-uuid',
        relative_path: 'case-a/target.pdf',
        folder_group: 'project/1/case-a',
    }],
    document: {
        querySelectorAll(selector) {
            if (selector === '#dataForm input[type="text"], #dataForm textarea, #dataForm select') return inputs;
            return [];
        },
        getElementById() { return null; },
    },
    getLinkedPdfPathConfig() { return { col: 1, folderLevels: 1 }; },
    alert(message) { alerts.push(message); },
    async authFetch(_url, options) {
        requestedPayload = JSON.parse(options.body);
        return { ok: true, async json() { return { status: 'ok' }; } };
    },
    formatApiErrorDetail(value) { return String(value); },
    fetchSubmissions() {},
    saveQueueState() {},
    renderFileQueue() {},
    removeCurrentFormDraft() {},
};
vm.createContext(submissionSandbox);
vm.runInContext(fs.readFileSync('frontend/js/submission.js', 'utf8'), submissionSandbox);

(async () => {
    await vm.runInContext("submitData('draft')", submissionSandbox);
    assert.equal(requestedPayload, null, 'Chỉ đổi đường dẫn phải bị chặn trước khi gọi API');
    assert(alerts.some(message => message.includes('phải sửa ít nhất một trường dữ liệu')));

    inputs[1].value = 'Nội dung đã sửa';
    await vm.runInContext("submitData('draft')", submissionSandbox);
    assert.equal(requestedPayload.copy_source_submission_id, 41);
    assert.equal(requestedPayload.data.col_1, 'Nội dung đã sửa');
    assert.equal(requestedPayload.data._pdf_uuid, 'target-uuid');
    console.log('Submission copy flow self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
