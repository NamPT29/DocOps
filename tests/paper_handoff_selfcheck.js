// Sổ giao nhận hồ sơ giấy (lát H1b): bảng mốc, form Ghi/Sửa, Xóa mốc cuối, giờ Việt Nam, lỗi hiện trong modal.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function withTimeout(promise, message, ms = 1500) {
    let timer;
    return Promise.race([
        promise,
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`Treo: ${message}`)), ms); }),
    ]).finally(() => clearTimeout(timer));
}

// ---------- DOM giả ----------
function fakeClassList(initial = []) {
    const set = new Set(initial);
    return {
        add: (...names) => names.forEach(name => set.add(name)),
        remove: (...names) => names.forEach(name => set.delete(name)),
        contains: name => set.has(name),
    };
}
function fakeElement(tag) {
    const element = {
        tag, children: [], dataset: {}, listeners: {}, classList: fakeClassList(), value: '', type: '', colSpan: 1,
        textContent: '', innerHTMLWrites: [],
        appendChild(child) { this.children.push(child); return child; },
        append(...nodes) { nodes.forEach(node => this.children.push(node)); },
        replaceChildren(...nodes) { this.children = nodes; },
        addEventListener(type, fn) { this.listeners[type] = fn; },
        setAttribute() {},
    };
    Object.defineProperty(element, 'className', {
        set(value) { element.classList = fakeClassList(String(value).split(/\s+/).filter(Boolean)); },
        get() { return ''; },
    });
    Object.defineProperty(element, 'innerHTML', {
        set(value) { element.innerHTMLWrites.push(value); },
        get() { return ''; },
    });
    return element;
}
const walk = (node, out = []) => { out.push(node); (node.children || []).forEach(child => walk(child, out)); return out; };
const texts = node => walk(node).map(item => item.textContent).filter(Boolean);
const buttons = (node, label) => walk(node).filter(item => item.tag === 'button' && item.textContent === label);

const ids = ['paperHandoffModal', 'paperHandoffTitle', 'paperHandoffError', 'paperHandoffForm', 'paperHandoffFormTitle',
    'paperHandoffTime', 'paperHandoffHandedBy', 'paperHandoffReceivedBy', 'paperHandoffNote', 'paperHandoffTable'];
const elements = Object.fromEntries(ids.map(id => [id, fakeElement('div')]));
elements.paperHandoffError.classList.add('d-none');
elements.paperHandoffForm.classList.add('d-none');

const requests = [];
let replies = [];
const alerts = [];
const confirms = [];
const downloads = [];
let modalShown = 0;
const reply = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

const sandbox = {
    console, setTimeout, clearTimeout, Date,
    currentUser: { id: 1, username: 'admin', role: 'admin' },
    document: { getElementById: id => elements[id] || null, createElement: fakeElement },
    bootstrap: { Modal: { getOrCreateInstance: () => ({ show: () => { modalShown += 1; } }) } },
    async authFetch(url, options = {}) {
        requests.push({ url, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null });
        const next = replies.shift();
        if (!next) throw new Error(`Không có phản hồi giả cho ${url}`);
        return next;
    },
    formatApiErrorDetail: detail => (Array.isArray(detail) ? detail.map(item => item.msg).join('\n') : String(detail)),
    async downloadExportResponse(response, fallback) { downloads.push({ response, fallback }); },
    alert: message => alerts.push(message),
    confirm: message => { confirms.push(message); return true; },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/paper_handoff.js', 'utf8'), sandbox);

const MILESTONES = [
    { key: 'received_from_client', label: 'Nhận từ khách hàng', order: 1 },
    { key: 'to_arrangement', label: 'Giao chỉnh lý', order: 2 },
    { key: 'to_scan', label: 'Giao scan', order: 3 },
    { key: 'returned_to_storage', label: 'Trả kho', order: 4 },
    { key: 'returned_to_client', label: 'Trả khách hàng', order: 5 },
];
const event = (iso, received) => ({ happened_at: iso, handed_by: 'Người giao', received_by: received, note: null, recorded_by: 'Ad Min', updated_at: iso });
const DATA = {
    milestones: MILESTONES,
    cases: [
        { case_id: 11, case_name: 'Hộp A', box_number: 1, events: {
            received_from_client: event('2026-10-08T01:30:00Z', 'Kho nhận'),
            to_arrangement: event('2026-10-08T17:30:00Z', '<b>X</b>'),
        } },
        { case_id: 12, case_name: 'Hộp B', box_number: 2, events: {} },
        { case_id: 13, case_name: 'Hộp C', box_number: null, events: {} },
    ],
};
const listReply = () => reply(200, { status: 'ok', data: DATA });
const rows = () => elements.paperHandoffTable.children[1].children;
const cell = (row, key) => rows()[row].children.find(item => item.dataset.milestone === key);

(async () => {
    // a. Mở modal: GET đúng API, bảng đủ cột, ô đã ghi hiện giờ VN + người nhận, chỉ mốc kế tiếp có nút Ghi
    replies = [listReply()];
    assert.equal(await withTimeout(sandbox.openPaperHandoffModal({ id: 7, name: 'Bộ Y tế' }), 'mở modal'), true);
    assert.equal(modalShown, 1);
    assert.equal(elements.paperHandoffTitle.textContent, 'Bộ Y tế');
    assert.deepEqual(requests.map(r => `${r.method} ${r.url}`), ['GET /api/projects/7/paper-handoffs']);
    assert.deepEqual(texts(elements.paperHandoffTable.children[0]), ['Hộp', 'Tên hộp', ...MILESTONES.map(m => m.label)]);
    assert.equal(rows().length, 3);
    assert.deepEqual(texts(cell(0, 'received_from_client')).slice(0, 2), ['08/10/2026 08:30', 'Kho nhận']);
    assert.deepEqual(texts(cell(0, 'to_arrangement')).slice(0, 2), ['09/10/2026 00:30', '<b>X</b>']);
    const ghi = row => MILESTONES.filter(m => buttons(cell(row, m.key), 'Ghi').length).map(m => m.key);
    assert.deepEqual(ghi(0), ['to_scan'], 'hộp A: chỉ mốc 3 có nút Ghi');
    assert.deepEqual(ghi(1), ['received_from_client'], 'hộp B: chỉ mốc 1 có nút Ghi');
    assert.equal(rows()[2].children[0].textContent, '—', 'hộp C không có số hộp');

    // b. Nút Xóa chỉ ở mốc cuối đã ghi; Sửa ở mọi mốc đã ghi
    const xoa = row => MILESTONES.filter(m => buttons(cell(row, m.key), 'Xóa').length).map(m => m.key);
    assert.deepEqual(xoa(0), ['to_arrangement']);
    assert.deepEqual(xoa(1), []);
    assert.equal(buttons(cell(0, 'received_from_client'), 'Sửa').length, 1);

    // f. Chữ từ dữ liệu hiện bằng textContent, không innerHTML
    assert.deepEqual(walk(elements.paperHandoffTable).flatMap(node => node.innerHTMLWrites), []);

    // c. Hàm giờ không phụ thuộc múi giờ máy
    assert.equal(sandbox.formatPaperHandoffTime('2026-10-08T17:30:00Z'), '09/10/2026 00:30');
    assert.equal(sandbox.formatPaperHandoffTime('2026-10-08T01:30:00.123456Z'), '08/10/2026 08:30');
    assert.equal(sandbox.paperHandoffToVnInput('2026-10-08T01:30:00Z'), '2026-10-08T08:30');
    assert.equal(sandbox.paperHandoffToVnInput('2026-12-31T20:00:00Z'), '2027-01-01T03:00');
    assert.equal(sandbox.paperHandoffFromVnInput('2026-10-08T08:30'), '2026-10-08T08:30:00+07:00');
    assert.equal(sandbox.paperHandoffFromVnInput(''), null);
    assert.equal(sandbox.formatPaperHandoffTime(''), '');

    // Sửa: form điền sẵn giá trị đã ghi (giờ VN)
    buttons(cell(0, 'received_from_client'), 'Sửa')[0].listeners.click();
    assert.equal(elements.paperHandoffForm.classList.contains('d-none'), false);
    assert.equal(elements.paperHandoffFormTitle.textContent, 'Hộp A – Nhận từ khách hàng');
    assert.equal(elements.paperHandoffTime.value, '2026-10-08T08:30');
    assert.equal(elements.paperHandoffReceivedBy.value, 'Kho nhận');

    // d. Ghi mốc 3: PUT đúng URL, body kèm +07:00, xong ẩn form và nạp lại bảng
    buttons(cell(0, 'to_scan'), 'Ghi')[0].listeners.click();
    assert.equal(elements.paperHandoffFormTitle.textContent, 'Hộp A – Giao scan');
    assert.match(elements.paperHandoffTime.value, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/, 'mặc định giờ hiện tại');
    elements.paperHandoffTime.value = '2026-10-09T09:15';
    elements.paperHandoffHandedBy.value = 'Tổ chỉnh lý';
    elements.paperHandoffReceivedBy.value = 'Tổ scan';
    elements.paperHandoffNote.value = '  ';
    requests.length = 0;
    replies = [reply(200, { status: 'ok', data: {} }), listReply()];
    assert.equal(await withTimeout(sandbox.savePaperHandoff(), 'lưu mốc'), true);
    assert.deepEqual(requests.map(r => `${r.method} ${r.url}`), [
        'PUT /api/projects/7/cases/11/paper-handoffs/to_scan', 'GET /api/projects/7/paper-handoffs',
    ]);
    assert.deepEqual(requests[0].body, {
        happened_at: '2026-10-09T09:15:00+07:00', handed_by: 'Tổ chỉnh lý', received_by: 'Tổ scan', note: null,
    });
    assert.equal(elements.paperHandoffForm.classList.contains('d-none'), true);

    // e. 409: message trong #paperHandoffError, form còn hiện, không alert
    buttons(cell(0, 'to_scan'), 'Ghi')[0].listeners.click();
    elements.paperHandoffTime.value = '2026-10-07T09:15';
    elements.paperHandoffHandedBy.value = 'A';
    elements.paperHandoffReceivedBy.value = 'B';
    requests.length = 0;
    replies = [reply(409, { status: 'error', message: 'Thời gian sớm hơn mốc trước đó',
        detail: { code: 'milestone_before_previous', message: 'Thời gian sớm hơn mốc trước đó' } })];
    assert.equal(await withTimeout(sandbox.savePaperHandoff(), 'lưu 409'), false);
    assert.equal(requests.length, 1, 'lỗi thì không nạp lại');
    assert.equal(elements.paperHandoffError.textContent, 'Thời gian sớm hơn mốc trước đó');
    assert.equal(elements.paperHandoffError.classList.contains('d-none'), false);
    assert.equal(elements.paperHandoffForm.classList.contains('d-none'), false);
    assert.equal(elements.paperHandoffReceivedBy.value, 'B', 'giữ dữ liệu đã nhập');
    assert.deepEqual(alerts, []);

    // 422 (sai kiểu): ghép thông báo kiểm dữ liệu
    replies = [reply(422, { status: 'error', message: 'Dữ liệu không hợp lệ', detail: [{ loc: ['body', 'handed_by'], msg: 'Input should be a valid string' }] })];
    assert.equal(await withTimeout(sandbox.savePaperHandoff(), 'lưu 422'), false);
    assert.equal(elements.paperHandoffError.textContent, 'Input should be a valid string');

    // Thiếu thời gian: không gửi
    elements.paperHandoffTime.value = '';
    requests.length = 0;
    assert.equal(await withTimeout(sandbox.savePaperHandoff(), 'thiếu giờ'), false);
    assert.equal(requests.length, 0);
    assert.equal(elements.paperHandoffError.textContent, 'Nhập thời gian.');

    // Xóa mốc cuối: hỏi xác nhận, DELETE đúng URL, nạp lại
    replies = [reply(200, { status: 'ok' }), listReply()];
    buttons(cell(0, 'to_arrangement'), 'Xóa')[0].listeners.click();
    await withTimeout(new Promise(resolve => setTimeout(resolve, 0)), 'chờ xóa');
    assert.deepEqual(confirms, ['Xóa mốc «Giao chỉnh lý» của Hộp A?']);
    assert.deepEqual(requests.map(r => `${r.method} ${r.url}`), [
        'DELETE /api/projects/7/cases/11/paper-handoffs/to_arrangement', 'GET /api/projects/7/paper-handoffs',
    ]);

    // Tải Excel
    requests.length = 0;
    const file = reply(200, {});
    replies = [file];
    assert.equal(await withTimeout(sandbox.downloadPaperHandoffs(), 'tải Excel'), true);
    assert.deepEqual(requests.map(r => r.url), ['/api/projects/7/paper-handoffs.xlsx']);
    assert.deepEqual(downloads, [{ response: file, fallback: 'So_giao_nhan_7.xlsx' }]);

    // Không phải Admin: không có nút Xóa
    sandbox.currentUser = { id: 2, username: 'b', role: 'user' };
    vm.runInContext('renderPaperHandoffTable(paperHandoffData)', sandbox);
    assert.deepEqual(xoa(0), []);

    // g, h. Trang nạp script đúng chỗ, menu dự án có mục, nút tĩnh đăng ký hành động
    const admin = fs.readFileSync('frontend/admin.html', 'utf8');
    assert.equal(admin.split('js/paper_handoff.js?v=1.00').length - 1, 1, 'admin.html nạp paper_handoff.js đúng 1 lần');
    assert(!fs.readFileSync('frontend/index.html', 'utf8').includes('paper_handoff.js'), 'index.html không nạp');
    assert(admin.includes('id="paperHandoffModal"'));
    const menu = fs.readFileSync('frontend/js/project_management.js', 'utf8');
    assert.match(menu, /label: 'Sổ giao nhận hồ sơ giấy',\s*icon: 'fa-truck-ramp-box',\s*handler: \(\) => openPaperHandoffModal\(project\)/);
    const page = fs.readFileSync('frontend/admin-page.js', 'utf8');
    for (const action of ['save-paper-handoff', 'cancel-paper-handoff', 'download-paper-handoffs']) {
        assert(admin.includes(`data-admin-action="${action}"`) && page.includes(`'${action}'`), action);
    }
    console.log('paper_handoff self-check: OK');
})().catch(error => {
    console.error(error);
    process.exit(1);
});
