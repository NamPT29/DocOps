// Bảng tiến độ dự án (lát D2): 3 ô số, bảng hạng mục, thanh 14 ngày, bảng người; lỗi hiện trong modal.
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
// Giống DOM thật: chỉ có tagName viết hoa (bản trước dùng thuộc tính "tag" nên selfcheck đạt mà trình duyệt hỏng).
function fakeElement(tag) {
    const element = {
        tagName: String(tag).toUpperCase(), children: [], dataset: {}, style: {}, classList: fakeClassList(), textContent: '', innerHTMLWrites: [],
        appendChild(child) { this.children.push(child); return child; },
        append(...nodes) { nodes.forEach(node => this.children.push(node)); },
        replaceChildren(...nodes) { this.children = nodes; },
        addEventListener() {},
    };
    Object.defineProperty(element, 'className', {
        set(value) { element.classList = fakeClassList(String(value).split(/\s+/).filter(Boolean)); },
        get() { return ''; },
    });
    Object.defineProperty(element, 'innerHTML', { set(value) { element.innerHTMLWrites.push(value); }, get() { return ''; } });
    return element;
}
const walk = (node, out = []) => { out.push(node); (node.children || []).forEach(child => walk(child, out)); return out; };
const texts = node => walk(node).map(item => item.textContent).filter(Boolean);
const section = name => elements.projectDashboardBody.children.find(child => child.dataset.section === name);
const bodyRows = table => table.children[1].children;

const elements = Object.fromEntries(['projectDashboardModal', 'projectDashboardTitle', 'projectDashboardError', 'projectDashboardBody']
    .map(id => [id, fakeElement('div')]));
elements.projectDashboardError.classList.add('d-none');
const requests = [];
let replies = [];
const alerts = [];
let shown = 0;
const reply = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

const sandbox = {
    console, setTimeout, clearTimeout, Math, Number, String,
    document: { getElementById: id => elements[id] || null, createElement: fakeElement },
    bootstrap: { Modal: { getOrCreateInstance: () => ({ show: () => { shown += 1; } }) } },
    async authFetch(url, options = {}) { requests.push({ url, method: options.method || 'GET' }); return replies.shift(); },
    formatApiErrorDetail: detail => String(detail),
    alert: message => alerts.push(message),
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/project_dashboard.js', 'utf8'), sandbox);

const day = (date, entered, approved, scan) => ({ date, entered, approved, scan_pages: scan });
const DATA = {
    stages: [
        { key: 'arrangement', label: 'Chỉnh lý', boxes_total: 4, boxes_done: 2, boxes_in_progress: 1, boxes_rejected: 1,
          boxes_pending: 0, percent_done: 50.0, unit: 'hồ sơ', volume_done: 5 },
        { key: 'scan', label: 'Scan', boxes_total: 4, boxes_done: 1, boxes_in_progress: 1, boxes_rejected: 0,
          boxes_pending: 2, percent_done: 25.0, unit: 'trang A4', volume_done: 12345 },
    ],
    documents: { total: 200, entered: 120, completed: 50, remaining: 150 },
    daily: [day('2026-09-25', 0, 0, 0), ...Array.from({ length: 11 }, (_, i) => day(`2026-09-${26 + i}`.replace('-09-31', '-10-01'), 10, 5, 0)),
        day('2026-10-07', 40, 20, 300), day('2026-10-08', 20, 10, 0)],
    forecast: { avg_entered_per_day_7d: 17.1, avg_approved_per_day_7d: 8.6, estimated_finish_date: '2026-10-26' },
    people: [{ user_id: 3, name: '<i>An</i>', entered: 7, approved: 0, scan_pages: 1500 }],
    norms: [],
};

(async () => {
    replies = [reply(200, { status: 'ok', data: DATA })];
    assert.equal(await withTimeout(sandbox.openProjectDashboard({ id: 7, name: 'Bộ Y tế' }), 'mở bảng tiến độ'), true);
    assert.equal(shown, 1);
    assert.equal(elements.projectDashboardTitle.textContent, 'Bộ Y tế');
    assert.deepEqual(requests.map(r => r.url), ['/api/projects/7/dashboard']);

    // 3 ô số
    const tiles = texts(section('tiles'));
    assert.deepEqual(tiles, [
        'Văn bản hoàn thành', '50 / 200', '25.0%',
        'Còn lại', '150', 'Đã nhập: 120',
        'Dự kiến xong', '26/10/2026', 'Duyệt TB 7 ngày: 8,6 văn bản/ngày',
    ]);

    // Bảng hạng mục: mỗi bước một dòng
    const stageRows = bodyRows(section('stages'));
    assert.equal(stageRows.length, 2);
    assert.deepEqual(texts(stageRows[1]), ['Scan', '1 / 4', '25%', '12.345 trang A4', '1', '0']);

    // Thanh 14 ngày: tỷ lệ với ngày lớn nhất
    const dailyRows = bodyRows(section('daily'));
    assert.equal(dailyRows.length, 14);
    const widths = row => walk(row).filter(node => node.dataset.metric).map(node => `${node.dataset.metric}:${node.style.width}`);
    assert.deepEqual(widths(dailyRows[0]), ['entered:0%', 'approved:0%'], 'ngày 0 là 0%');
    assert.deepEqual(widths(dailyRows[12]), ['entered:100%', 'approved:50%'], 'ngày lớn nhất 100%');
    assert.deepEqual(widths(dailyRows[13]), ['entered:50%', 'approved:25%']);
    assert.equal(dailyRows[12].children[1].tagName, 'TD', 'ô thanh là phần tử, không phải chữ');
    assert.equal(dailyRows[12].children[1].children.length, 2);
    assert.equal(dailyRows[12].children[0].textContent, '07/10');
    assert.equal(dailyRows[12].children[2].textContent, '40 / 20 / 300');

    // Bảng người: tên chứa thẻ hiện nguyên chữ
    assert.deepEqual(texts(bodyRows(section('people'))[0]), ['<i>An</i>', '7', '0', '1.500']);
    assert.deepEqual(walk(elements.projectDashboardBody).flatMap(node => node.innerHTMLWrites), []);

    // Chưa đủ số liệu dự kiến
    replies = [reply(200, { status: 'ok', data: { ...DATA, forecast: { ...DATA.forecast, estimated_finish_date: null } } })];
    assert.equal(await withTimeout(sandbox.loadProjectDashboard(), 'làm mới'), true);
    assert(texts(section('tiles')).includes('Chưa đủ số liệu'));
    assert.equal(sandbox.dashboardBarWidth(0, 0), '0%');

    // Lỗi 403/404: hiện chữ trong modal, không alert, giữ nội dung cũ
    replies = [reply(404, { status: 'error', message: 'Không tìm thấy dự án', detail: { code: 'project_not_found', message: 'Không tìm thấy dự án' } })];
    assert.equal(await withTimeout(sandbox.loadProjectDashboard(), 'lỗi 404'), false);
    assert.equal(elements.projectDashboardError.textContent, 'Không tìm thấy dự án');
    assert.equal(elements.projectDashboardError.classList.contains('d-none'), false);
    assert.deepEqual(alerts, []);
    replies = [reply(403, { status: 'error', message: 'Access denied', detail: 'Access denied' })];
    assert.equal(await withTimeout(sandbox.loadProjectDashboard(), 'lỗi 403'), false);
    assert.equal(elements.projectDashboardError.textContent, 'Access denied');
    replies = [reply(200, { status: 'ok', data: DATA })];
    await withTimeout(sandbox.loadProjectDashboard(), 'hết lỗi');
    assert.equal(elements.projectDashboardError.classList.contains('d-none'), true);

    // Trang, menu, nút Làm mới
    const admin = fs.readFileSync('frontend/admin.html', 'utf8');
    assert.equal(admin.split('js/project_dashboard.js?v=1.00').length - 1, 1, 'admin.html nạp đúng 1 lần');
    assert(!fs.readFileSync('frontend/index.html', 'utf8').includes('project_dashboard.js'));
    assert(admin.includes('data-admin-action="reload-project-dashboard"'));
    assert(fs.readFileSync('frontend/admin-page.js', 'utf8').includes("'reload-project-dashboard': () => loadProjectDashboard()"));
    const menu = fs.readFileSync('frontend/js/project_management.js', 'utf8');
    assert.match(menu, /label: 'Bảng tiến độ',\s*icon: 'fa-gauge-high',\s*handler: \(\) => openProjectDashboard\(project\)/);
    console.log('project_dashboard self-check: OK');
})().catch(error => {
    console.error(error);
    process.exit(1);
});
