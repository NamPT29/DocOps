const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const indexHtml = fs.readFileSync('frontend/index.html', 'utf8');
const adminHtml = fs.readFileSync('frontend/admin.html', 'utf8');
const templateConfigSource = fs.readFileSync('frontend/js/template_config.js', 'utf8');
const pdfHandlerSource = fs.readFileSync('frontend/js/pdf_handler.js', 'utf8');
const adminPanelSource = fs.readFileSync('frontend/js/admin_panel.js', 'utf8');
const appSource = fs.readFileSync('frontend/app.js', 'utf8');
const pdfIframe = indexHtml.match(/<iframe\b[^>]*\bid=["']pdfIframe["'][^>]*>/i);
assert.ok(pdfIframe, 'Không tìm thấy iframe hiển thị PDF');
assert.ok(!/\bsandbox\s*=/.test(pdfIframe[0]), 'iframe PDF không được sandbox vì Chrome sẽ chặn trình xem PDF tích hợp');
assert.ok(/\breferrerpolicy=["']no-referrer["']/.test(pdfIframe[0]), 'iframe PDF phải giữ chính sách no-referrer');
assert.ok(indexHtml.includes('id="queueExplorerBreadcrumb"'));
assert.ok(indexHtml.includes('id="folderLinkText"'));
assert.ok(adminHtml.includes('id="linkedPdfPathEnabled"'));
assert.ok(adminHtml.includes('id="linkedPdfPathCol"'));
assert.ok(adminHtml.includes('id="linkedPdfPathFolderLevels"'));
assert.ok(templateConfigSource.includes('currentConfigObj.linked_pdf_path'));
assert.ok(!pdfHandlerSource.includes('resetFormData(true)'));
assert.ok(appSource.includes("fileSidebar.classList.remove('d-none')"));
assert.ok(!appSource.includes("fileSidebar.classList.add('d-none')"));
const expectedCompletedSubmissionHeaders = [
    'STT',
    'Tên biểu mẫu',
    'Ngày giờ',
    'Đường dẫn PDF liên kết',
    'Người nhập',
    'Trạng thái',
    'Thao tác',
];
const expectedReviewHeaders = expectedCompletedSubmissionHeaders.slice(1);
const expectedEmployeeSubmissionHeaders = [
    'Chọn',
    ...expectedCompletedSubmissionHeaders.slice(0, 5),
    'Người kiểm duyệt',
    ...expectedCompletedSubmissionHeaders.slice(5),
];
function headersBeforeBody(html, bodyId) {
    const bodyIndex = html.indexOf(`id="${bodyId}"`);
    const headStart = html.lastIndexOf('<thead', bodyIndex);
    const headEnd = html.indexOf('</thead>', headStart);
    return Array.from(html.slice(headStart, headEnd).matchAll(/<th[^>]*>(.*?)<\/th>/gs))
        .map(match => match[1].replace(/<[^>]+>/g, '').trim());
}
assert.deepEqual(headersBeforeBody(indexHtml, 'submissionsTableBody'), expectedEmployeeSubmissionHeaders);
assert.deepEqual(headersBeforeBody(adminHtml, 'reviewTableBody'), expectedReviewHeaders);
assert.deepEqual(headersBeforeBody(adminHtml, 'submissionsTableBody'), expectedCompletedSubmissionHeaders);
assert.ok(indexHtml.includes('id="submissionsPagination"'));
assert.ok(adminHtml.includes('id="submissionsPagination"'));
assert.ok(adminPanelSource.includes('sub.serial_number'));
assert.ok(adminPanelSource.includes('renderSubmissionsPagination'));
assert.ok(indexHtml.includes('selectAllSubmissionsOnPage()'));
assert.ok(indexHtml.includes('id="selectAllSubmissionsBtn"'));
assert.ok(indexHtml.includes('clearSubmissionSelection()'));
assert.ok(indexHtml.includes('bulkSubmitSelectedSubmissions()'));
assert.ok(indexHtml.includes('bulkDeleteSelectedSubmissions()'));
assert.ok(adminPanelSource.includes('/api/submissions/bulk-action'));
assert.ok(adminPanelSource.includes("row.classList.toggle('table-success', checked)"));
assert.ok(adminPanelSource.includes("sub.pdf_relative_path || sub.pdf_filename || ''"));
assert.ok(adminPanelSource.includes("escapeHTML(sub.reviewer_name || 'Chưa phân công')"));

global.currentUser = { username: 'tester' };
global.window = { activeTemplateConfig: {} };
global.savedQueueState = {};
global.localStorage = { setItem(key, value) { savedQueueState[key] = value; } };
global.document = {};
global.alert = message => { throw new Error(message); };
global.assert = assert;

const source = fs.readFileSync('frontend/js/pdf_handler.js', 'utf8') + `
uploadedFilesQueue = [
    { name: 'duoc-giao.pdf', uuid: 'uuid-queue.pdf' },
    { name: 'xem-lai.pdf', uuid: 'uuid-temporary.pdf', temporary_view: true },
];
iframeCurrentIndex = 1;
saveQueueState();
assert.deepEqual(JSON.parse(savedQueueState.pdfQueue_tester).map(file => file.uuid), ['uuid-queue.pdf']);
assert.equal(savedQueueState.pdfIndex_tester, '-1');

renderFileQueue = () => {};
saveQueueState = () => {};
selectFileFromQueue = index => { iframeCurrentIndex = index; };
updatePdfLinkUI = () => {};
uploadedFilesQueue = [{
    name: 'CT 909101-GCN.pdf',
    url: '/uploads/CT%20909101-GCN.pdf',
}];

addFileToQueueAndSelect(
    'CT 909101-GCN.pdf',
    'abc_CT 909101-GCN.pdf',
    '/uploads/abc_CT%20909101-GCN.pdf',
);

assert.equal(uploadedFilesQueue.length, 1);
assert.equal(uploadedFilesQueue[0].uuid, 'abc_CT 909101-GCN.pdf');
assert.equal(uploadedFilesQueue[0].url, '/uploads/abc_CT%20909101-GCN.pdf');
assert.equal(iframeCurrentIndex, 0);

uploadedFilesQueue = [
    { name: 'Trùng tên.pdf', uuid: 'u1_Trùng tên.pdf', url: '/api/files/u1' },
    { name: 'Trùng tên.pdf', uuid: 'u2_Trùng tên.pdf', url: '/api/files/u2' },
];
addFileToQueueAndSelect('Trùng tên.pdf', 'u3_Trùng tên.pdf', '/api/files/u3');
assert.equal(uploadedFilesQueue.length, 3);
assert.deepEqual(uploadedFilesQueue.map(file => file.uuid), [
    'u1_Trùng tên.pdf',
    'u2_Trùng tên.pdf',
    'u3_Trùng tên.pdf',
]);

uploadedFilesQueue = [
    {
        name: '001.pdf',
        url: '/uploads/legacy-a.pdf',
        relative_path: 'tlm/001/0001/001.pdf',
        folder_group: 'tlm/001/0001',
    },
    {
        name: '001.pdf',
        url: '/uploads/legacy-b.pdf',
        relative_path: 'tlm/001/0002/001.pdf',
        folder_group: 'tlm/001/0002',
    },
];
addFileToQueueAndSelect(
    '001.pdf',
    'uuid-folder-0002.pdf',
    '/api/files/uuid-folder-0002.pdf',
    {
        relative_path: 'tlm/001/0002/001.pdf',
        folder_group: 'tlm/001/0002',
    },
);
assert.equal(uploadedFilesQueue.length, 2, 'Xem lại hồ sơ không được tạo thêm PDF đã có trong folder');
assert.equal(uploadedFilesQueue[1].uuid, 'uuid-folder-0002.pdf');
assert.equal(iframeCurrentIndex, 1);

uploadedFilesQueue = [];
addFileToQueueAndSelect(
    'xem-lai.pdf',
    'uuid-xem-lai.pdf',
    '/api/files/uuid-xem-lai.pdf',
    { temporary_view: true },
);
assert.equal(uploadedFilesQueue[0].temporary_view, true, 'PDF mở từ Xem/Sửa phải là tài liệu tạm');

uploadedFilesQueue = [
    {
        name: '001.pdf',
        url: '/uploads/legacy-a.pdf',
        relative_path: 'tlm/001/0001/001.pdf',
        folder_group: 'tlm/001/0001',
    },
    {
        name: '001.pdf',
        url: '/uploads/legacy-b.pdf',
        relative_path: 'tlm/001/0002/001.pdf',
        folder_group: 'tlm/001/0002',
    },
    {
        name: '001.pdf',
        uuid: 'uuid-folder-0002.pdf',
        url: '/api/files/uuid-folder-0002.pdf',
        relative_path: 'tlm/001/0002/001.pdf',
        folder_group: 'tlm/001/0002',
    },
];
addFileToQueueAndSelect(
    '001.pdf',
    'uuid-folder-0002.pdf',
    '/api/files/uuid-folder-0002.pdf',
    {
        relative_path: 'tlm/001/0002/001.pdf',
        folder_group: 'tlm/001/0002',
    },
);
assert.equal(uploadedFilesQueue.length, 2, 'Xem lại hồ sơ phải gộp bản PDF trùng đã lưu từ phiên cũ');
assert.equal(uploadedFilesQueue[1].relative_path, 'tlm/001/0002/001.pdf');
assert.equal(iframeCurrentIndex, 1);

const pathInput = {
    value: '',
    dispatchEvent() {},
};
document.getElementById = id => id === 'col_38' ? pathInput : null;

setActiveDocumentRelativePath('tlm/HOANHMO/001/0001/1.pdf');
assert.equal(pathInput.value, '', 'Template chưa cấu hình không được tự điền Path');

window.activeTemplateConfig = {
    linked_pdf_path: { enabled: true, col: 39, folder_levels: 1 },
};
setActiveDocumentRelativePath('tlm/HOANHMO/001/0001/1.pdf');
assert.equal(pathInput.value, '0001/1.pdf');

window.activeTemplateConfig.linked_pdf_path.folder_levels = 0;
setActiveDocumentRelativePath('tlm/HOANHMO/001/0001/1.pdf');
assert.equal(pathInput.value, 'tlm/HOANHMO/001/0001/1.pdf');

assert.equal(getQueuePathTail('tlm/HOANHMO/001/0001'), '0001');
assert.equal(getQueueDocumentName({ name: '001.pdf', relative_path: 'tlm/001/0001/001.pdf' }), '001.pdf');
assert.equal(getQueueDocumentName({ name: 'tlm/001/0001/001.pdf' }), '001.pdf');
assert.equal(getQueueFolderKey({ folder_group: '__ROOT__', template_id: 1 }), null);
assert.equal(getQueueFolderKey({ folder_group: 'tlm/HOANHMO/001/0001', template_id: 1 }), '1::tlm/HOANHMO/001/0001');

uploadedFilesQueue = [{
    name: 'cong-viec-cua-toi.pdf',
    uuid: 'uuid-own-queue.pdf',
    url: '/api/files/uuid-own-queue.pdf',
    relative_path: '001/0001/cong-viec-cua-toi.pdf',
    folder_group: '001/0001',
    template_id: 1,
}];
loadReviewFolderFiles([
    {
        name: 'bia.pdf',
        uuid: 'uuid-bia.pdf',
        url: '/api/files/uuid-bia.pdf',
        relative_path: '001/0001/bia.pdf',
        folder_group: '001/0001',
        template_id: 1,
    },
    {
        name: 'form-1.pdf',
        uuid: 'uuid-form-1.pdf',
        url: '/api/files/uuid-form-1.pdf',
        relative_path: '001/0001/form-1.pdf',
        folder_group: '001/0001',
        template_id: 1,
    },
], 'uuid-form-1.pdf');
assert.deepEqual(uploadedFilesQueue.map(file => file.name), ['bia.pdf', 'cong-viec-cua-toi.pdf', 'form-1.pdf']);
const ownQueueFile = uploadedFilesQueue.find(file => file.uuid === 'uuid-own-queue.pdf');
assert.equal(ownQueueFile.temporary_view, undefined, 'Xem folder kiểm tra không được xóa queue nhập của chính người dùng');
assert(uploadedFilesQueue.filter(file => file.uuid !== 'uuid-own-queue.pdf').every(file => file.temporary_view === true));
assert.equal(iframeCurrentIndex, 2, 'Há»“ sÆ¡ Ä‘ang duyá»‡t pháº£i chá»n Ä‘Ãºng PDF liÃªn káº¿t');
assert.equal(activeQueueFolderKey, '1::001/0001', 'Báº¥m kiá»ƒm duyá»‡t pháº£i má»Ÿ ngay danh sÃ¡ch file trong folder');
`;

vm.runInThisContext(source, { filename: 'pdf_handler.js' });
console.log('PDF reference self-check: OK');
