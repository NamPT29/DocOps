// FR-ARR-01: arrangement catalogue dialog and projects created before scanning.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const catalogSource = fs.readFileSync('frontend/js/arrangement_catalog.js', 'utf8');
const uploadSource = fs.readFileSync('frontend/js/project_upload.js', 'utf8');
const html = fs.readFileSync('frontend/admin.html', 'utf8');
const management = fs.readFileSync('frontend/js/project_management.js', 'utf8');
const adminPage = fs.readFileSync('frontend/admin-page.js', 'utf8');

assert.doesNotMatch(catalogSource, /innerHTML|insertAdjacentHTML|document\.write/, 'Render with textContent only.');
assert.match(html, /id="arrangementCatalogModal"/);
assert.match(html, /<input type="file" class="form-control" id="arrangementCatalogFile" accept="\.xlsx/);
assert.match(html, /id="arrangementImportButton" data-admin-action="import-arrangement-catalog" disabled/);
assert.match(html, /data-admin-action="preview-arrangement-catalog"/);
assert.match(html, /src="js\/arrangement_catalog\.js\?v=[\d.]+"/);
assert.match(html, /id="projectRootFolderInput"[^>]*data-admin-change="update-project-level-options"/);
assert.match(adminPage, /'preview-arrangement-catalog': \(\) => previewArrangementCatalog\(\)/);
assert.match(adminPage, /'import-arrangement-catalog': \(\) => importArrangementCatalog\(\)/);
assert.match(management, /label: 'Mục lục chỉnh lý',[\s\S]*?openArrangementCatalog\(project\.id\)/);

// --- a tiny DOM -----------------------------------------------------------------
function element(tag) {
    const node = {
        tagName: String(tag).toUpperCase(),
        className: '',
        textContent: '',
        children: [],
        listeners: {},
        disabled: false,
        value: '',
        append(...items) { items.forEach(item => this.children.push(item)); },
        appendChild(item) { this.children.push(item); return item; },
        replaceChildren() { this.children = []; },
        addEventListener(type, handler) { this.listeners[type] = handler; },
    };
    return node;
}

function allText(node) {
    return [node.textContent, ...node.children.map(allText)].join(' ');
}

function findAll(node, predicate, found = []) {
    if (predicate(node)) found.push(node);
    node.children.forEach(child => findAll(child, predicate, found));
    return found;
}

// --- catalogue dialog ---------------------------------------------------------
const elements = {
    arrangementCatalogTitle: element('span'),
    arrangementCatalogFile: Object.assign(element('input'), { files: [] }),
    arrangementImportButton: Object.assign(element('button'), { disabled: true }),
    arrangementPreview: element('div'),
    arrangementBoxesBody: element('tbody'),
    arrangementCatalogTotals: element('span'),
    arrangementBoxDetail: element('div'),
    arrangementImportHistory: element('ul'),
    arrangementCatalogModal: element('div'),
};
const requests = [];
const alerts = [];
const responses = [];
const catalogData = {
    boxes: [
        { box_number: 1, folder: null, awaiting_scan: true, dossier_count: 2, bad_paper_dossiers: 1, bad_paper_proposed: true, missing_count: 0 },
        { box_number: 2, folder: '0002', awaiting_scan: false, dossier_count: 1, bad_paper_dossiers: 0, bad_paper_proposed: false, missing_count: 1 },
    ],
    dossier_total: 3,
    imports: [{ created_at: '2026-10-04T03:00:00+00:00', imported_by: 'pm', file_name: 'muc_luc.xlsx', added: 3, updated: 0, removed: 0, kept: 0 }],
};
const sandbox = {
    console,
    FormData,
    alert(message) { alerts.push(message); },
    projectManagementProjects: [{ id: 7, name: 'Bộ Y tế' }],
    bootstrap: { Modal: class { show() { requests.push({ url: 'modal:show' }); } } },
    document: {
        getElementById: id => elements[id] || null,
        createElement: tag => element(tag),
    },
    async apiCall(url, options = {}) {
        requests.push({ url, method: options.method || 'GET', body: options.body });
        if (url.endsWith('/arrangement/catalog')) return { data: catalogData };
        return responses.shift();
    },
};
vm.createContext(sandbox);
vm.runInContext(catalogSource, sandbox);

(async () => {
    await sandbox.openArrangementCatalog(7);
    assert.equal(elements.arrangementCatalogTitle.textContent, 'Bộ Y tế');
    assert.equal(elements.arrangementCatalogTotals.textContent, '(2 hộp, 3 hồ sơ)');
    const boxesText = allText(elements.arrangementBoxesBody);
    assert.match(boxesText, /Chờ scan/);
    assert.match(boxesText, /Đề xuất \(1 hồ sơ đánh x\)/);
    assert.match(boxesText, /1 hồ sơ không còn trong mục lục mới/);
    assert.match(allText(elements.arrangementImportHistory), /pm: muc_luc\.xlsx \(thêm 3/);
    assert.ok(requests.some(request => request.url === 'modal:show'));

    // No file chosen: nothing is sent.
    await sandbox.previewArrangementCatalog();
    assert.match(alerts.pop(), /chọn file mục lục/);

    // A file with errors keeps "Xác nhận ghi" locked and lists Excel rows.
    elements.arrangementCatalogFile.files = [new Blob(['PK'], { type: 'application/zip' })];
    responses.push({ data: {
        file_name: 'muc_luc.xlsx', row_count: 2, box_count: 1, file_errors: [],
        errors: [{ row: 3, column: 'Thời gian bắt đầu', message: '<b>Ngày</b> sai' }], error_count: 1,
        summary: null, removed: [], kept: [], plan_token: null, can_import: false,
    } });
    await sandbox.previewArrangementCatalog();
    assert.equal(elements.arrangementImportButton.disabled, true);
    const previewText = allText(elements.arrangementPreview);
    assert.match(previewText, /1 lỗi\. Sửa file/);
    assert.match(previewText, /3 Thời gian bắt đầu <b>Ngày<\/b> sai/, 'Messages stay plain text.');

    // A clean preview unlocks the import, which sends the previewed token once.
    responses.push({ data: {
        file_name: 'muc_luc.xlsx', row_count: 3, box_count: 2, file_errors: [], errors: [], error_count: 0,
        summary: { added: 1, updated: 1, unchanged: 0, removed: 1, kept: 0, new_boxes: 1 },
        removed: [{ box: 1, dossier: '3', title: 'Hồ sơ 3' }], kept: [], plan_token: 'tok-1', can_import: true,
    } });
    await sandbox.previewArrangementCatalog();
    assert.equal(elements.arrangementImportButton.disabled, false);
    assert.match(allText(elements.arrangementPreview), /Xóa: 1/);
    assert.match(allText(elements.arrangementPreview), /Hộp 1 \/ Hồ sơ 3 – Hồ sơ 3/);

    responses.push({ data: { import_id: 4, summary: { added: 1, updated: 1, removed: 1, kept: 0, new_boxes: 1 } } });
    await sandbox.importArrangementCatalog();
    const sent = requests.find(request => request.url.endsWith('/catalog/import'));
    assert.equal(sent.method, 'POST');
    assert.equal(sent.body.get('plan_token'), 'tok-1');
    assert.equal(elements.arrangementImportButton.disabled, true, 'A token is used once.');
    assert.match(alerts.pop(), /Đã ghi mục lục: thêm 1/);

    // Each box opens its dossiers.
    responses.push({ data: [
        { dossier: '12', title: 'A', start_date: '05/01/2020', end_date: '28/12/2020', maintenance_code: '01', sheet_count: 5, bad_paper: false, note: null, missing_from_last_import: false },
        { dossier: '12a', title: 'B', start_date: '00/00/2020', end_date: '00/00/2020', maintenance_code: '02', sheet_count: 3, bad_paper: true, note: null, missing_from_last_import: true },
    ] });
    const viewButton = findAll(elements.arrangementBoxesBody, node => node.tagName === 'BUTTON')[0];
    await viewButton.listeners.click();
    const detail = allText(elements.arrangementBoxDetail);
    assert.match(detail, /Hộp 1/);
    assert.match(detail, /B \(không còn trong mục lục mới\)/);

    // --- a project created before any PDF ---------------------------------------
    const form = {
        projectRootFolderInput: { value: '' },
        projectTemplateSelect: { value: '3' },
        projectCaseLevel: Object.assign(element('select'), { value: '' }),
        projectReportLevel: Object.assign(element('select'), { options: [] }),
        projectReportMode: { value: 'pdf' },
        projectNameInput: { value: '' },
        projectStartDate: { value: '' },
        projectEndDate: { value: '' },
        createProjectButton: { disabled: false },
        projectUploadStatus: { textContent: '', className: '' },
        projectReportLevelGroup: { classList: { toggle() {} } },
    };
    form.projectReportLevel.appendChild = function appendChild(item) {
        this.children.push(item);
        this.options.push(item);
        return item;
    };
    form.projectReportLevel.replaceChildren = function replaceChildren() {
        this.children = [];
        this.options = [];
    };
    const uploadRequests = [];
    const uploadAlerts = [];
    const page = {
        console,
        alert(message) { uploadAlerts.push(message); },
        document: {
            getElementById: id => form[id] || null,
            createElement: tag => element(tag),
        },
        async apiCall(url, options = {}) {
            uploadRequests.push({ url, method: options.method, body: options.body });
            return { project_id: 12 };
        },
        async loadProjectList() { uploadRequests.push({ url: 'reload' }); },
    };
    vm.createContext(page);
    vm.runInContext(uploadSource, page);

    await page.createAndUploadProject();
    assert.match(uploadAlerts.pop(), /nhập tên folder gốc/);
    assert.equal(uploadRequests.length, 0);

    form.projectRootFolderInput.value = 'Phong01';
    page.updateProjectLevelOptions();
    assert.deepEqual(form.projectCaseLevel.children.map(option => option.value), ['1', '2', '3']);
    form.projectCaseLevel.value = '1';

    await page.createAndUploadProject();
    const created = uploadRequests.find(request => request.url === '/api/projects');
    const body = JSON.parse(created.body);
    assert.equal(body.root_folder_name, 'Phong01');
    assert.equal(body.name, 'Phong01');
    assert.equal(body.case_level, 1);
    assert.equal(body.report_level, null);
    assert.ok(!uploadRequests.some(request => String(request.url).includes('upload-sessions')), 'No upload without PDFs.');
    assert.match(form.projectUploadStatus.textContent, /Đã tạo dự án chưa có PDF/);
    assert.match(form.projectUploadStatus.textContent, /“Phong01”/);

    console.log('Arrangement catalogue self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
