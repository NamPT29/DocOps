// C3b: tab "Việc của tôi" (frontend/js/my_work.js) trên index.html.
// Chạy bằng node thuần, không cần thư viện ngoài (gate chạy ở máy sạch).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('frontend/js/my_work.js', 'utf8');
const html = fs.readFileSync('frontend/index.html', 'utf8');

// --- kiểm tĩnh index.html: không dán trùng trang, không nạp script của trang Admin ---
assert.equal((html.match(/<\/html>/g) || []).length, 1, 'index.html chỉ có một </html>');
assert.match(html.trimEnd(), /<\/html>$/, 'Không có nội dung sau </html>');
const scripts = Array.from(html.matchAll(/<script src="([^"]+)"/g), match => match[1].split('?')[0]);
assert.equal(new Set(scripts).size, scripts.length, `Script bị nạp hai lần: ${scripts}`);
for (const adminOnly of ['admin-page.js', 'js/project_management.js', 'js/project_workflow.js']) {
    assert.ok(!scripts.includes(adminOnly), `index.html không được nạp ${adminOnly}`);
}
const authIndex = scripts.indexOf('auth.js');
const scanIndex = scripts.indexOf('js/project_scan_submit.js');
const entryQcIndex = scripts.indexOf('js/project_entry_qc.js');
const myWorkIndex = scripts.indexOf('js/my_work.js');
assert.ok(authIndex >= 0 && scanIndex > authIndex && entryQcIndex > scanIndex && myWorkIndex > entryQcIndex,
          'Thứ tự: auth.js, project_scan_submit.js, project_entry_qc.js, my_work.js');
assert.equal((html.match(/id="scanSubmitModal"/g) || []).length, 1, 'Có đúng một hộp thoại Nộp S');
for (const id of ['myWorkTabItem', 'myWorkProjectSelect', 'myWorkTable', 'btnRefreshMyWork']) {
    assert.equal((html.match(new RegExp(`id="${id}"`, 'g')) || []).length, 1, `Có đúng một #${id}`);
}
assert.match(html, /<li[^>]*class="[^"]*\bd-none\b[^"]*"[^>]*id="myWorkTabItem"|<li[^>]*id="myWorkTabItem"[^>]*class="[^"]*\bd-none\b/, 'Tab ẩn sẵn');
assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML|document\.write/, 'Hiển thị bằng textContent');
const authSource = fs.readFileSync('frontend/auth.js', 'utf8');
const capabilityUi = authSource.slice(authSource.indexOf('function configureCapabilityUI'), authSource.indexOf('async function refreshCurrentUserProfile'));
assert.match(capabilityUi, /typeof applyMyWorkVisibility === 'function'\) applyMyWorkVisibility\(\)/,
             'configureCapabilityUI phải gọi applyMyWorkVisibility (nó ẩn cả thanh tab với người chỉ làm quy trình)');

// index.html không có formatVietnamDateTime (của project_management.js): giờ Nộp S vẫn là giờ VN.
{
    const scanContext = { console, Intl, Date };
    vm.createContext(scanContext);
    vm.runInContext(fs.readFileSync('frontend/js/project_scan_submit.js', 'utf8'), scanContext);
    assert.equal(typeof scanContext.formatVietnamDateTime, 'undefined');
    assert.equal(vm.runInContext("scanSubmitTime('2026-10-05T17:30:00')", scanContext), '2026-10-06 00:30');
    assert.equal(vm.runInContext("scanSubmitTime('2026-10-05T03:00:00+00:00')", scanContext), '2026-10-05 10:00');
    assert.equal(vm.runInContext("scanSubmitTime('khong-phai-ngay')", scanContext), 'khong-phai-ngay');
}

// --- DOM giả tối thiểu ---
function element(tag) {
    const classes = new Set();
    return {
        tagName: String(tag).toUpperCase(),
        className: '',
        textContent: '',
        children: [],
        listeners: {},
        value: '',
        classList: {
            add: (...names) => names.forEach(name => classes.add(name)),
            remove: (...names) => names.forEach(name => classes.delete(name)),
            contains: name => classes.has(name),
            toggle: (name, force) => {
                const on = force === undefined ? !classes.has(name) : Boolean(force);
                if (on) classes.add(name); else classes.delete(name);
                return on;
            },
        },
        appendChild(child) { this.children.push(child); return child; },
        replaceChildren(...nodes) { this.children = nodes; },
        addEventListener(type, handler) { this.listeners[type] = handler; },
    };
}

function select() {
    const node = element('select');
    Object.defineProperty(node, 'value', {
        get() { return node.children.length ? node.children[0].value : ''; },
    });
    return node;
}

function setup() {
    const nodes = {
        myWorkTabItem: element('li'),
        myWorkProjectSelect: select(),
        btnRefreshMyWork: element('button'),
        tbody: element('tbody'),
        employeeTabs: element('ul'),
        noAssignmentNotice: element('div'),
        inputTabItem: element('li'),
        dataTabItem: element('li'),
        reviewTabItem: element('li'),
        'my-work-pane': element('div'),
        'my-work-tab': element('button'),
        'form-pane': element('div'),
        'form-tab': element('button'),
    };
    nodes.myWorkTabItem.classList.add('d-none');
    // Mặc định: người chỉ làm quy trình -> auth.js đã ẩn thanh tab và các tab nhập/kiểm tra.
    for (const id of ['employeeTabs', 'inputTabItem', 'dataTabItem', 'reviewTabItem']) nodes[id].classList.add('d-none');
    const panes = [nodes['my-work-pane'], nodes['form-pane']];
    const links = [nodes['my-work-tab'], nodes['form-tab']];
    const requests = [];
    const routes = {};
    const calls = { alert: [], openScanSubmit: [], openScanMatch: [], openEntryQc: [] };
    const answers = { confirm: true, prompt: null };
    const context = {
        console,
        document: {
            getElementById: id => nodes[id] || null,
            querySelector: selector => (selector === '#myWorkTable tbody' ? nodes.tbody : null),
            querySelectorAll: selector => ({
                '#appTabsContent > .tab-pane': panes,
                '#employeeTabs .nav-link': links,
            }[selector] || []),
            createElement: tag => element(tag),
            addEventListener: () => {},
        },
        localStorage: { getItem: () => null },
        authFetch: async (url, options = {}) => {
            const method = options.method || 'GET';
            const body = options.body ? JSON.parse(options.body) : undefined;
            requests.push({ method, url, body });
            const handler = routes[`${method} ${url}`];
            const reply = handler ? handler(body) : { status: 200, json: { status: 'ok', data: [] } };
            return {
                ok: reply.status >= 200 && reply.status < 300,
                status: reply.status,
                json: async () => reply.json,
            };
        },
        alert: message => calls.alert.push(message),
        confirm: () => answers.confirm,
        prompt: () => answers.prompt,
        openScanSubmit: (caseId, name) => calls.openScanSubmit.push([caseId, name, context.projectWorkflowProjectId]),
        openScanMatch: (caseId, name) => calls.openScanMatch.push([caseId, name, context.projectWorkflowProjectId]),
        openEntryQc: (caseId, name) => calls.openEntryQc.push([caseId, name, context.projectWorkflowProjectId]),
    };
    vm.createContext(context);
    vm.runInContext(source, context);
    const run = code => vm.runInContext(code, context);
    return { nodes, requests, routes, calls, answers, context, run };
}

function rows(tbody) {
    return tbody.children.map(tr => ({
        cells: tr.children.map(td => td.textContent),
        buttons: tr.children[3] ? tr.children[3].children : [],
    }));
}

function button(row, text) {
    const found = row.buttons.find(node => node.textContent === text);
    assert.ok(found, `Thiếu nút "${text}" (có: ${row.buttons.map(node => node.textContent)})`);
    return found;
}

const PROJECTS = [{ project_id: 7, name: 'Dự án A', stages: ['scan', 'scan_qc'], is_reviewer: true },
                  { project_id: 9, name: 'Dự án B', stages: ['arrangement'], is_reviewer: false }];
const ITEMS = [
    { case_id: 1, case_key: '0001', display_name: 'Hộp 1', stage_key: 'arrangement', status: 'pending' },
    { case_id: 2, case_key: '0002', display_name: 'Hộp 2', stage_key: 'arrangement', status: 'in_progress' },
    { case_id: 3, case_key: '0003', display_name: 'Hộp 3', stage_key: 'scan', status: 'rejected' },
    { case_id: 4, case_key: '0004', display_name: 'Hộp 4', stage_key: 'scan', status: 'in_progress' },
    { case_id: 5, case_key: '0005', display_name: 'Hộp 5', stage_key: 'scan_qc', status: 'pending' },
    { case_id: 6, case_key: '0006', display_name: 'Hộp 6', stage_key: 'scan_qc', status: 'in_progress' },
    { case_id: 8, case_key: '0008', display_name: 'Hộp 8', stage_key: 'entry_qc', status: 'in_progress',
      gate_code: 'entry_qc_not_finalized' },
];
const EXPECTED_BUTTONS = [
    ['Bắt đầu'],
    ['Hoàn tất'],
    ['Nộp S'],
    ['Nộp S', 'Hoàn tất scan'],
    ['Xem so khớp', 'Bắt đầu'],
    ['Xem so khớp', 'Duyệt', 'Trả lại'],
    ['Check nhập'],
];
const TRANSITION = (caseId, stage) => `POST /api/projects/7/workflow/cases/${caseId}/stages/${stage}/transition`;

async function loaded() {
    const page = setup();
    page.routes['GET /api/workflow/my-projects'] = () => ({ status: 200, json: { status: 'ok', data: PROJECTS } });
    page.routes['GET /api/projects/7/workflow/my-work'] = () => ({ status: 200, json: { status: 'ok', data: ITEMS } });
    await page.run('fetchMyProjects()');
    return page;
}

async function runTests() {
    // a) Không có dự án -> tab vẫn ẩn, không tải việc.
    {
        const page = setup();
        page.routes['GET /api/workflow/my-projects'] = () => ({ status: 200, json: { status: 'ok', data: [] } });
        await page.run('fetchMyProjects()');
        assert.ok(page.nodes.myWorkTabItem.classList.contains('d-none'));
        assert.deepEqual(page.requests.map(r => r.url), ['/api/workflow/my-projects']);
    }
    // a) Có dự án -> tab hiện, đủ dự án trong ô chọn, tải việc của dự án đầu tiên.
    {
        const page = await loaded();
        assert.ok(!page.nodes.myWorkTabItem.classList.contains('d-none'));
        assert.deepEqual(page.nodes.myWorkProjectSelect.children.map(o => [Number(o.value), o.textContent]),
                         [[7, 'Dự án A'], [9, 'Dự án B']]);
        assert.equal(page.requests.at(-1).url, '/api/projects/7/workflow/my-work');

        // b) nút theo bước/trạng thái; f) dòng entry_qc có nhãn cổng và nút Check nhập (C3c).
        const table = rows(page.nodes.tbody);
        assert.deepEqual(table.map(row => row.buttons.map(node => node.textContent)), EXPECTED_BUTTONS);
        assert.deepEqual(table[0].cells.slice(0, 3), ['Hộp 1', 'Chỉnh lý', 'Chờ']);
        assert.deepEqual(table[2].cells.slice(0, 3), ['Hộp 3', 'Scan', 'Bị trả lại']);
        assert.deepEqual(table[5].cells.slice(0, 3), ['Hộp 6', 'Check scan', 'Đang làm']);
        assert.deepEqual(table[6].cells.slice(0, 3), ['Hộp 8', 'Check nhập', 'Chưa chốt vòng 1']);
    }
    // Người chỉ làm quy trình: hiện lại thanh tab, ẩn thông báo "chưa phân công", mở luôn tab này;
    // auth.js ẩn lại thanh tab sau đó thì applyMyWorkVisibility hiện lại.
    {
        const page = await loaded();
        assert.ok(!page.nodes.employeeTabs.classList.contains('d-none'), 'Hiện thanh tab');
        assert.ok(page.nodes.noAssignmentNotice.classList.contains('d-none'), 'Ẩn thông báo chưa phân công');
        assert.ok(page.nodes['my-work-pane'].classList.contains('active') && page.nodes['my-work-pane'].classList.contains('show'));
        assert.ok(page.nodes['my-work-tab'].classList.contains('active'));
        page.nodes.employeeTabs.classList.add('d-none');
        page.run('applyMyWorkVisibility()');
        assert.ok(!page.nodes.employeeTabs.classList.contains('d-none'), 'Gọi lại sau configureCapabilityUI vẫn hiện');
    }
    // Người vừa nhập liệu vừa làm quy trình: không giành tab đang mở.
    {
        const page = setup();
        page.nodes.inputTabItem.classList.remove('d-none');
        page.nodes.employeeTabs.classList.remove('d-none');
        page.nodes['form-pane'].classList.add('show', 'active');
        page.routes['GET /api/workflow/my-projects'] = () => ({ status: 200, json: { status: 'ok', data: PROJECTS } });
        await page.run('fetchMyProjects()');
        assert.ok(!page.nodes.myWorkTabItem.classList.contains('d-none'));
        assert.ok(page.nodes['form-pane'].classList.contains('active'), 'Giữ tab Nhập hồ sơ');
        assert.ok(!page.nodes['my-work-pane'].classList.contains('active'));
    }
    // c) Trả lại: Hủy hoặc toàn dấu cách -> không gửi; có lý do -> gửi đúng URL và body.
    {
        const page = await loaded();
        const reject = button(rows(page.nodes.tbody)[5], 'Trả lại');
        const before = page.requests.length;
        page.answers.prompt = null;
        await reject.listeners.click();
        page.answers.prompt = '   ';
        await reject.listeners.click();
        assert.equal(page.requests.length, before, 'Không gửi khi chưa nhập lý do');
        page.answers.prompt = 'Thiếu trang';
        page.routes[TRANSITION(6, 'scan_qc')] = () => ({ status: 200, json: { status: 'ok' } });
        await reject.listeners.click();
        await new Promise(resolve => setImmediate(resolve));
        const sent = page.requests.find(r => `${r.method} ${r.url}` === TRANSITION(6, 'scan_qc'));
        assert.deepEqual(sent.body, { action: 'reject', reason: 'Thiếu trang' });
    }
    // d) Duyệt: không xác nhận -> không gửi; lỗi 409 -> báo đúng message; thành công -> tải lại.
    {
        const page = await loaded();
        const approve = button(rows(page.nodes.tbody)[5], 'Duyệt');
        const before = page.requests.length;
        page.answers.confirm = false;
        await approve.listeners.click();
        assert.equal(page.requests.length, before);

        page.answers.confirm = true;
        page.routes[TRANSITION(6, 'scan_qc')] = () => ({
            status: 409,
            json: { detail: { code: 'scan_catalog_mismatch', message: 'Hồ sơ scan lệch với mục lục. Chỉ Admin được duyệt.' } },
        });
        await approve.listeners.click();
        await new Promise(resolve => setImmediate(resolve));
        assert.deepEqual(page.calls.alert, ['Hồ sơ scan lệch với mục lục. Chỉ Admin được duyệt.']);
        assert.deepEqual(page.requests.at(-1).body, { action: 'complete' });

        page.routes[TRANSITION(6, 'scan_qc')] = () => ({ status: 200, json: { status: 'ok' } });
        await approve.listeners.click();
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(page.requests.at(-1).url, '/api/projects/7/workflow/my-work', 'Tải lại bảng sau khi duyệt');
        assert.equal(page.calls.alert.length, 1);

        // Bắt đầu / Hoàn tất gửi đúng hành động.
        await button(rows(page.nodes.tbody)[0], 'Bắt đầu').listeners.click();
        await new Promise(resolve => setImmediate(resolve));
        assert.ok(page.requests.some(r => `${r.method} ${r.url}` === TRANSITION(1, 'arrangement') && r.body.action === 'start'));
    }
    // e) Nộp S / Xem so khớp: gán dự án đang chọn trước khi mở hộp thoại dùng chung.
    {
        const page = await loaded();
        button(rows(page.nodes.tbody)[3], 'Nộp S').listeners.click();
        button(rows(page.nodes.tbody)[4], 'Xem so khớp').listeners.click();
        assert.deepEqual(page.calls.openScanSubmit.map(([id, name, pid]) => [id, name, Number(pid)]), [[4, 'Hộp 4', 7]]);
        assert.deepEqual(page.calls.openScanMatch.map(([id, name, pid]) => [id, name, Number(pid)]), [[5, 'Hộp 5', 7]]);
        page.run('projectWorkflowProjectId = null');
        button(rows(page.nodes.tbody)[6], 'Check nhập').listeners.click();
        assert.deepEqual(page.calls.openEntryQc.map(([id, name, pid]) => [id, name, Number(pid)]), [[8, 'Hộp 8', 7]]);
        // project_scan_submit.js gọi refreshProjectWorkflow() sau khi nộp: phải tải lại bảng.
        const before = page.requests.length;
        await page.run('refreshProjectWorkflow()');
        assert.deepEqual(page.requests.slice(before).map(r => r.url), ['/api/projects/7/workflow/my-work']);
    }
    // Lỗi tải việc -> dòng báo lỗi hiển thị bằng textContent.
    {
        const page = await loaded();
        page.routes['GET /api/projects/7/workflow/my-work'] = () => ({ status: 500, json: {} });
        await page.run('fetchMyWork()');
        assert.match(rows(page.nodes.tbody)[0].cells[0], /^Lỗi: /);
    }
    console.log('My work self-check: OK');
}

runTests().catch(error => { console.error(error); process.exitCode = 1; });
