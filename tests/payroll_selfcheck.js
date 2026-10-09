// Chi trả theo sản lượng (lát P1b, P2): đơn giá, kỳ, bảng tạm tính, tải Excel, chốt kỳ; lỗi trong modal.
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
        tagName: String(tag).toUpperCase(), children: [], dataset: {}, classList: fakeClassList(), textContent: '', value: '',
        innerHTMLWrites: [], listeners: {}, type: '', colSpan: 1,
        appendChild(child) { this.children.push(child); return child; },
        append(...nodes) { nodes.forEach(node => this.children.push(node)); },
        replaceChildren(...nodes) { this.children = nodes; },
        addEventListener(type, fn) { this.listeners[type] = fn; },
    };
    Object.defineProperty(element, 'className', {
        set(value) { element.classList = fakeClassList(String(value).split(/\s+/).filter(Boolean)); },
        get() { return ''; },
    });
    Object.defineProperty(element, 'innerHTML', { set(value) { element.innerHTMLWrites.push(value); }, get() { return ''; } });
    return element;
}
const walk = (node, out = []) => { out.push(node); (node.children || []).forEach(child => walk(child, out)); return out; };
const rowsOf = id => elements[id].children[1].children.map(row => row.children.map(cell => cell.textContent));

const ids = ['payrollModal', 'payrollTitle', 'payrollError', 'payrollRate-NL-1', 'payrollRate-CN-1', 'payrollRate-SC-A4-1',
    'payrollFactorNote', 'payrollFrom', 'payrollTo', 'payrollWarnings', 'payrollPeopleTable', 'payrollLinesTable', 'payrollPeriodsTable'];
const elements = Object.fromEntries(ids.map(id => [id, fakeElement('div')]));
elements.payrollError.classList.add('d-none');
const requests = [];
let replies = [];
const downloads = [];
const alerts = [];
const confirms = [];
let confirmAnswer = true;
const reply = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

const sandbox = {
    console, setTimeout, clearTimeout, Number, String, JSON, Date,
    document: { getElementById: id => elements[id] || null, createElement: fakeElement },
    bootstrap: { Modal: { getOrCreateInstance: () => ({ show() {} }) } },
    async authFetch(url, options = {}) {
        requests.push({ url, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null });
        return replies.shift();
    },
    async downloadExportResponse(response, fallback) { downloads.push({ response, fallback }); },
    formatApiErrorDetail: detail => String(detail),
    alert: message => alerts.push(message),
    confirm: message => { confirms.push(message); return confirmAnswer; },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/payroll.js', 'utf8'), sandbox);

const RATES = { rates: [
    { code: 'NL-1', unit_price: 1000 }, { code: 'CN-1', unit_price: null }, { code: 'SC-A4-1', unit_price: 50 },
], bad_paper_factor: 1.3 };
const PREVIEW = {
    lines: [
        { name: '<b>An</b>', work_code: 'NL-2', work: 'Nhập liệu', unit: 'văn bản', quantity: 1200, unit_price: 1000, factor: 1.3, amount: 1560000 },
        { name: 'Bùi Duyệt', work_code: 'CN-1', work: 'Check nhập liệu', unit: 'văn bản', quantity: 3, unit_price: null, factor: 1, amount: null },
    ],
    people: [{ name: '<b>An</b>', amount: 1560000, complete: true }, { name: 'Bùi Duyệt', amount: 0, complete: false }],
    total: 1560000,
    warnings: ['Chưa có đơn giá CN-1'],
};

(async () => {
    // Mở: GET đơn giá, điền ô, kỳ mặc định từ ngày 1 tháng này tới hôm nay (giờ VN)
    const PERIODS = [
        { id: 5, from: '2026-10-08', to: '2026-10-09', total: 2500000, lines: 3, created_at: '2026-10-09T02:00:00Z', created_by: '<i>Quản trị</i>' },
        { id: 4, from: '2026-10-01', to: '2026-10-07', total: 108220, lines: 7, created_at: '2026-10-07T17:30:00Z', created_by: 'Quản trị' },
    ];
    replies = [reply(200, { status: 'ok', data: RATES }), reply(200, { status: 'ok', data: PERIODS })];
    const now = Date.UTC(2026, 9, 7, 18, 0);  // 01:00 ngày 08/10 giờ VN
    assert.equal(await withTimeout(sandbox.openPayroll({ id: 7, name: 'Bộ Y tế' }, now), 'mở modal'), true);
    assert.deepEqual(requests.map(r => `${r.method} ${r.url}`), ['GET /api/projects/7/work-rates', 'GET /api/projects/7/payroll-periods']);
    const periodRows = () => elements.payrollPeriodsTable.children[1].children;
    const periodButtons = (row, label) => walk(row).filter(node => node.tagName === 'BUTTON' && node.textContent === label);
    assert.deepEqual(periodRows()[0].children.slice(0, 5).map(cell => cell.textContent),
        ['08/10/2026 – 09/10/2026', '2.500.000', '3', '09/10/2026 09:00', '<i>Quản trị</i>']);
    assert.equal(periodRows()[1].children[3].textContent, '08/10/2026 00:30', 'giờ chốt theo giờ VN');
    assert.equal(periodButtons(periodRows()[0], 'Xóa').length, 1, 'kỳ mới nhất có nút Xóa');
    assert.equal(periodButtons(periodRows()[1], 'Xóa').length, 0, 'kỳ cũ không có nút Xóa');
    assert.equal(periodButtons(periodRows()[1], 'Tải Excel').length, 1);
    assert.deepEqual(['NL-1', 'CN-1', 'SC-A4-1'].map(code => elements[`payrollRate-${code}`].value), ['1000', '', '50']);
    assert.equal(elements.payrollFactorNote.textContent, 'Loại 2 (giấy xấu) = đơn giá loại 1 × 1,3 (Chính sách dự án).');
    assert.deepEqual([elements.payrollFrom.value, elements.payrollTo.value], ['2026-10-01', '2026-10-08']);

    // Lưu đơn giá: PUT số (không phải chuỗi), ô trống -> null
    requests.length = 0;
    elements['payrollRate-NL-1'].value = '1250.5';
    elements['payrollRate-CN-1'].value = '';
    replies = [reply(200, { status: 'ok', data: RATES })];
    assert.equal(await withTimeout(sandbox.savePayrollRates(), 'lưu đơn giá'), true);
    assert.deepEqual(requests[0], { url: '/api/projects/7/work-rates', method: 'PUT', body: { rates: { 'NL-1': 1250.5, 'CN-1': null, 'SC-A4-1': 50 } } });

    // Đơn giá âm: máy chủ 400 -> message trong modal, không alert
    replies = [reply(400, { status: 'error', detail: { code: 'negative_rate', message: 'Đơn giá NL-1 không được âm' } })];
    elements['payrollRate-NL-1'].value = '-5';
    assert.equal(await withTimeout(sandbox.savePayrollRates(), 'giá âm'), false);
    assert.equal(elements.payrollError.textContent, 'Đơn giá NL-1 không được âm');
    assert.equal(elements.payrollError.classList.contains('d-none'), false);
    elements['payrollRate-NL-1'].value = 'abc';
    requests.length = 0;
    assert.equal(await withTimeout(sandbox.savePayrollRates(), 'giá chữ'), false);
    assert.equal(requests.length, 0);

    // Xem tạm tính: GET đúng kỳ YYYY-MM-DD, bảng người + chi tiết, tiền vi-VN, cảnh báo, tên hiện nguyên chữ
    elements.payrollFrom.value = '2026-10-01';
    elements.payrollTo.value = '2026-10-07';
    replies = [reply(200, { status: 'ok', data: PREVIEW })];
    assert.equal(await withTimeout(sandbox.previewPayroll(), 'xem tạm tính'), true);
    assert.equal(requests[0].url, '/api/projects/7/payroll-preview?from=2026-10-01&to=2026-10-07');
    assert.deepEqual(rowsOf('payrollPeopleTable'), [
        ['<b>An</b>', '1.560.000', ''], ['Bùi Duyệt', '0', 'Thiếu đơn giá một số dòng'], ['Tổng', '1.560.000', ''],
    ]);
    assert.deepEqual(rowsOf('payrollLinesTable')[0], ['<b>An</b>', 'NL-2', 'Nhập liệu', 'văn bản', '1.200', '1.000', '1,3', '1.560.000']);
    assert.deepEqual(rowsOf('payrollLinesTable')[1].slice(5), ['', '1', '']);
    assert.deepEqual(walk(elements.payrollWarnings).map(node => node.textContent).filter(Boolean), ['Chưa có đơn giá CN-1']);
    assert.equal(elements.payrollWarnings.classList.contains('d-none'), false);
    assert.equal(elements.payrollError.classList.contains('d-none'), true, 'thành công thì ẩn lỗi cũ');
    assert.deepEqual(['payrollPeopleTable', 'payrollLinesTable'].flatMap(id => walk(elements[id]).flatMap(node => node.innerHTMLWrites)), []);

    // Kỳ sai: lỗi máy chủ hiện trong modal
    requests.length = 0;
    replies = [reply(400, { status: 'error', detail: { code: 'period_too_long', message: 'Mỗi kỳ tối đa 92 ngày' } })];
    assert.equal(await withTimeout(sandbox.previewPayroll(), 'kỳ quá dài'), false);
    assert.equal(elements.payrollError.textContent, 'Mỗi kỳ tối đa 92 ngày');
    elements.payrollTo.value = '';
    assert.equal(await withTimeout(sandbox.previewPayroll(), 'thiếu ngày'), false);
    assert.equal(requests.length, 1);

    // Tải Excel
    elements.payrollTo.value = '2026-10-07';
    requests.length = 0;
    const file = reply(200, {});
    replies = [file];
    assert.equal(await withTimeout(sandbox.downloadPayroll(), 'tải Excel'), true);
    assert.equal(requests[0].url, '/api/projects/7/payroll-preview?from=2026-10-01&to=2026-10-07&format=xlsx');
    assert.deepEqual(downloads, [{ response: file, fallback: 'Tam_tinh_chi_tra_7.xlsx' }]);
    assert.deepEqual(alerts, []);

    // P2: chốt kỳ đang chọn -> POST {from, to}, nạp lại danh sách
    requests.length = 0;
    replies = [reply(200, { status: 'ok', data: {} }), reply(200, { status: 'ok', data: PERIODS })];
    assert.equal(await withTimeout(sandbox.closePayrollPeriod(), 'chốt kỳ'), true);
    assert.deepEqual(requests.map(r => `${r.method} ${r.url}`), ['POST /api/projects/7/payroll-periods', 'GET /api/projects/7/payroll-periods']);
    assert.deepEqual(requests[0].body, { from: '2026-10-01', to: '2026-10-07' });
    assert.match(confirms[confirms.length - 1], /Chốt kỳ chi trả 01\/10\/2026 – 07\/10\/2026/);

    // Chồng kỳ: 409 -> message trong modal, không nạp lại
    requests.length = 0;
    replies = [reply(409, { status: 'error', detail: { code: 'period_overlap', message: 'Khoảng ngày chồng kỳ đã chốt 2026-10-01 – 2026-10-07' } })];
    assert.equal(await withTimeout(sandbox.closePayrollPeriod(), 'chồng kỳ'), false);
    assert.equal(requests.length, 1);
    assert.equal(elements.payrollError.textContent, 'Khoảng ngày chồng kỳ đã chốt 2026-10-01 – 2026-10-07');
    confirmAnswer = false;
    requests.length = 0;
    assert.equal(await withTimeout(sandbox.closePayrollPeriod(), 'hủy chốt'), false);
    assert.equal(requests.length, 0, 'bấm Hủy thì không gửi');
    confirmAnswer = true;

    // Tải Excel từng kỳ, xóa kỳ mới nhất
    downloads.length = 0;
    const periodFile = reply(200, {});
    replies = [periodFile];
    periodButtons(periodRows()[1], 'Tải Excel')[0].listeners.click();
    await withTimeout(new Promise(resolve => setTimeout(resolve, 0)), 'chờ tải kỳ');
    assert.equal(requests[0].url, '/api/projects/7/payroll-periods/4.xlsx');
    assert.deepEqual(downloads, [{ response: periodFile, fallback: 'Chi_tra_7_2026-10-01_2026-10-07.xlsx' }]);
    requests.length = 0;
    replies = [reply(200, { status: 'ok', data: {} }), reply(200, { status: 'ok', data: PERIODS.slice(1) })];
    periodButtons(periodRows()[0], 'Xóa')[0].listeners.click();
    await withTimeout(new Promise(resolve => setTimeout(resolve, 0)), 'chờ xóa kỳ');
    assert.deepEqual(requests.map(r => `${r.method} ${r.url}`), ['DELETE /api/projects/7/payroll-periods/5', 'GET /api/projects/7/payroll-periods']);
    assert.equal(periodRows().length, 1);
    assert.deepEqual(walk(elements.payrollPeriodsTable).flatMap(node => node.innerHTMLWrites), []);

    const admin = fs.readFileSync('frontend/admin.html', 'utf8');
    assert.equal(admin.split('js/payroll.js?v=1.01').length - 1, 1, 'admin.html nạp payroll.js đúng 1 lần');
    assert(!fs.readFileSync('frontend/index.html', 'utf8').includes('payroll.js'));
    const page = fs.readFileSync('frontend/admin-page.js', 'utf8');
    for (const action of ['save-payroll-rates', 'preview-payroll', 'download-payroll', 'close-payroll-period']) {
        assert(admin.includes(`data-admin-action="${action}"`) && page.includes(`'${action}'`), action);
    }
    assert.match(fs.readFileSync('frontend/js/project_management.js', 'utf8'),
        /label: 'Chi trả sản lượng',\s*icon: 'fa-money-bill-wave',\s*handler: \(\) => openPayroll\(project\)/);
    console.log('Payroll self-check: OK');
})().catch(error => {
    console.error(error);
    process.exit(1);
});
