const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const inputs = [{ name: 'col_0', value: 'Dữ liệu' }];
const classList = { add() {}, remove() {}, contains() { return false; } };
const elements = {
    'data-tab': { click() {} },
    cancelEditBtn: { classList },
    pdfPlaceholder: { style: {}, innerHTML: '' },
    pdfIframe: { style: {} },
};
let requestedUrl = '';
let selectedIndex = null;
let queueSaved = 0;
let queueRendered = 0;

const sandbox = {
    console,
    window: { reviewEditMode: false, activeTemplateId: 1 },
    currentEditingId: 44,
    isEditingFromList: true,
    isPdfLinked: true,
    iframeCurrentIndex: 0,
    uploadedFilesQueue: [
        { name: 'da-nop.pdf', uuid: 'uuid-da-nop.pdf', url: '/api/files/uuid-da-nop.pdf', temporary_view: true },
        { name: 'tiep-theo.pdf', uuid: 'uuid-tiep-theo.pdf', url: '/api/files/uuid-tiep-theo.pdf' },
    ],
    document: {
        querySelectorAll(selector) {
            if (selector === '#dataForm input[type="text"], #dataForm textarea, #dataForm select') return inputs;
            return [];
        },
        getElementById(id) { return elements[id] || null; },
    },
    async authFetch(url) {
        requestedUrl = url;
        return { ok: true, async json() { return { status: 'ok' }; } };
    },
    formatApiErrorDetail: value => String(value),
    alert() {},
    fetchSubmissions() {},
    saveQueueState() { queueSaved++; },
    renderFileQueue() { queueRendered++; },
    selectFileFromQueue(index) { selectedIndex = index; },
    updatePdfLinkUI() {},
    clearTemporaryPdfView() {
        this.uploadedFilesQueue = this.uploadedFilesQueue.filter(file => file.temporary_view !== true);
        this.iframeCurrentIndex = -1;
        queueSaved++;
        queueRendered++;
    },
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/submission.js', 'utf8'), sandbox);
vm.runInContext(`
    clearTemporaryPdfView = function() {
        uploadedFilesQueue = uploadedFilesQueue.filter(file => file.temporary_view !== true);
        iframeCurrentIndex = -1;
        saveQueueState();
        renderFileQueue();
    };
`, sandbox);

(async () => {
    await vm.runInContext("submitData('pending_review')", sandbox);

    assert.equal(requestedUrl, '/api/submissions/44');
    assert.deepEqual(
        Array.from(sandbox.uploadedFilesQueue, file => file.uuid),
        ['uuid-tiep-theo.pdf'],
        'PDF của hồ sơ nháp vừa nộp duyệt phải biến mất khỏi queue local',
    );
    assert.equal(queueSaved, 1);
    assert.equal(queueRendered, 1);
    assert.equal(selectedIndex, null, 'Thoát Xem/Sửa không được tự thêm PDF hồ sơ vào queue');

    sandbox.uploadedFilesQueue = [{ name: 'cuoi-cung.pdf', uuid: 'uuid-cuoi-cung.pdf' }];
    sandbox.iframeCurrentIndex = 0;
    sandbox.isPdfLinked = true;
    vm.runInContext('removeLinkedPdfFromQueue(0)', sandbox);
    assert.equal(sandbox.uploadedFilesQueue.length, 0);
    assert.equal(sandbox.iframeCurrentIndex, -1);
    assert.equal(elements.pdfPlaceholder.style.display, 'block');
    assert.equal(elements.pdfIframe.style.display, 'none');

    const employeeHtml = fs.readFileSync('frontend/index.html', 'utf8');
    const adminHtml = fs.readFileSync('frontend/admin.html', 'utf8');
    assert(employeeHtml.includes('js/submission.js?v=7.7'));
    assert(adminHtml.includes('js/submission.js?v=7.7'));
    console.log('Submission queue after save self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
