const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const indexHtml = fs.readFileSync('frontend/index.html', 'utf8');
const pdfIframe = indexHtml.match(/<iframe\b[^>]*\bid=["']pdfIframe["'][^>]*>/i);
assert.ok(pdfIframe, 'Không tìm thấy iframe hiển thị PDF');
assert.ok(!/\bsandbox\s*=/.test(pdfIframe[0]), 'iframe PDF không được sandbox vì Chrome sẽ chặn trình xem PDF tích hợp');
assert.ok(/\breferrerpolicy=["']no-referrer["']/.test(pdfIframe[0]), 'iframe PDF phải giữ chính sách no-referrer');

global.currentUser = { username: 'tester' };
global.localStorage = { setItem() {} };
global.document = {};
global.alert = message => { throw new Error(message); };
global.assert = assert;

const source = fs.readFileSync('frontend/js/pdf_handler.js', 'utf8') + `
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
`;

vm.runInThisContext(source, { filename: 'pdf_handler.js' });
console.log('PDF reference self-check: OK');
