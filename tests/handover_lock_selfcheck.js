// Khóa sửa hồ sơ sau bàn giao (lát K1b): menu Khóa/Mở khóa theo trạng thái, nhãn "Đã bàn giao", hỏi lý do mở khóa.
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

function fakeElement(tag) {
    const element = {
        tagName: String(tag).toUpperCase(), children: [], dataset: {}, style: {}, listeners: {}, textContent: '',
        className: '', innerHTML: '', value: '', selected: false,
        appendChild(child) { this.children.push(child); return child; },
        append(...nodes) { nodes.forEach(node => this.children.push(node)); },
        replaceChildren(...nodes) { this.children = nodes; },
        addEventListener(type, fn) { this.listeners[type] = fn; },
        setAttribute() {},
    };
    return element;
}
const walk = (node, out = []) => { out.push(node); (node.children || []).forEach(child => walk(child, out)); return out; };

const listBody = fakeElement('tbody');
const status = { textContent: '', className: '' };
const requests = [];
let replies = [];
const alerts = [];
let confirmAnswer = true;
let promptAnswers = [];
const reply = (code, body) => ({ ok: code >= 200 && code < 300, status: code, json: async () => body });
let projects = [];

const sandbox = {
    console, setTimeout, clearTimeout, Number, String, JSON,
    document: {
        getElementById: id => ({ projectListBody: listBody, projectExportStatus: status }[id] || null),
        createElement: fakeElement,
    },
    async apiCall(url) { requests.push({ url, method: 'GET' }); return { status: 'ok', data: projects }; },
    async authFetch(url, options = {}) {
        requests.push({ url, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null });
        return replies.shift();
    },
    formatApiErrorDetail: detail => String(detail),
    alert: message => alerts.push(message),
    confirm: () => confirmAnswer,
    prompt: () => promptAnswers.shift(),
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/project_reports.js', 'utf8'), sandbox);
vm.runInContext(fs.readFileSync('frontend/js/project_management.js', 'utf8'), sandbox);

const project = (id, name, lockedAt) => ({ id, name, template_name: 'T', status: 'ongoing', metrics: {}, handover_locked_at: lockedAt });
const rowOf = name => listBody.children.find(row => walk(row).some(node => node.tagName === 'STRONG' && node.textContent === name));
const menuLabels = row => walk(row).filter(node => node.tagName === 'BUTTON' && node.className.includes('dropdown-item'))
    .map(node => node.innerHTML.replace(/<[^>]+>/g, ''));
const menuButton = (row, label) => walk(row).find(node => node.tagName === 'BUTTON' && node.innerHTML.endsWith(label));

(async () => {
    // Danh sách dự án: nhãn "Đã bàn giao" và mục menu theo trạng thái khóa
    projects = [project(1, 'Đang làm', null), project(2, 'Đã giao', '2026-10-08T02:00:00Z')];
    await withTimeout(sandbox.loadProjectList(), 'nạp danh sách');
    const open = rowOf('Đang làm');
    const locked = rowOf('Đã giao');
    const badge = row => walk(row).filter(node => node.dataset.handoverLocked === 'true').map(node => node.textContent);
    assert.deepEqual(badge(open), []);
    assert.deepEqual(badge(locked), ['Đã bàn giao']);
    assert(menuLabels(open).includes('Khóa bàn giao') && !menuLabels(open).includes('Mở khóa bàn giao'));
    assert(menuLabels(locked).includes('Mở khóa bàn giao') && !menuLabels(locked).includes('Khóa bàn giao'));

    // Khóa: xác nhận + ghi chú -> POST, xong nạp lại danh sách
    requests.length = 0;
    promptAnswers = ['  Biên bản số 12  '];
    replies = [reply(200, { status: 'ok', data: {} })];
    menuButton(open, 'Khóa bàn giao').listeners.click();
    await withTimeout(new Promise(resolve => setTimeout(resolve, 0)), 'chờ khóa');
    assert.deepEqual(requests.map(r => `${r.method} ${r.url}`), ['POST /api/projects/1/handover-lock', 'GET /api/projects']);
    assert.deepEqual(requests[0].body, { note: 'Biên bản số 12' });
    assert.equal(status.textContent, 'Đã khóa bàn giao dự án “Đang làm”.');

    // Bấm Hủy ở hộp xác nhận hoặc ở ô ghi chú: không gửi
    requests.length = 0;
    confirmAnswer = false;
    assert.equal(await withTimeout(sandbox.lockProjectHandover(projects[0]), 'hủy xác nhận'), false);
    confirmAnswer = true;
    promptAnswers = [null];
    assert.equal(await withTimeout(sandbox.lockProjectHandover(projects[0]), 'hủy ghi chú'), false);
    assert.equal(requests.length, 0);

    // Chưa đóng gói: 409 package_required -> hiện message
    promptAnswers = [''];
    replies = [reply(409, { status: 'error', detail: { code: 'package_required', message: 'Chưa có lần đóng gói bàn giao nào xong.' } })];
    assert.equal(await withTimeout(sandbox.lockProjectHandover(projects[0]), 'khóa 409'), false);
    assert.deepEqual(requests[0].body, { note: null });
    assert.deepEqual(alerts, ['Chưa có lần đóng gói bàn giao nào xong.']);
    assert(status.className.includes('text-danger'));

    // Mở khóa: lý do trống thì KHÔNG gọi API
    requests.length = 0; alerts.length = 0;
    promptAnswers = ['   '];
    assert.equal(await withTimeout(sandbox.unlockProjectHandover(projects[1]), 'lý do trống'), false);
    promptAnswers = [null];
    assert.equal(await withTimeout(sandbox.unlockProjectHandover(projects[1]), 'hủy lý do'), false);
    assert.equal(requests.length, 0);
    assert.deepEqual(alerts, ['Cần nhập lý do mở khóa.']);

    // Mở khóa có lý do -> DELETE kèm lý do
    promptAnswers = ['Khách yêu cầu sửa trích yếu'];
    replies = [reply(200, { status: 'ok', data: {} })];
    menuButton(locked, 'Mở khóa bàn giao').listeners.click();
    await withTimeout(new Promise(resolve => setTimeout(resolve, 0)), 'chờ mở khóa');
    assert.deepEqual(requests.map(r => `${r.method} ${r.url}`), ['DELETE /api/projects/2/handover-lock', 'GET /api/projects']);
    assert.deepEqual(requests[0].body, { reason: 'Khách yêu cầu sửa trích yếu' });

    // Trang nhập liệu dùng formatApiErrorDetail của auth.js: lỗi 423 {code, message} phải hiện message, không hiện JSON
    const authSource = fs.readFileSync('frontend/auth.js', 'utf8');
    const formatter = vm.runInNewContext(`${authSource.match(/function formatApiErrorDetail[\s\S]*?\n\}/)[0]}; formatApiErrorDetail`);
    const lockedError = { code: 'project_handed_over', message: 'Dự án đã bàn giao, không sửa được hồ sơ. Admin mở khóa nếu cần sửa.' };
    assert.equal(formatter(lockedError), lockedError.message);
    assert.equal(formatter([{ loc: ['body', 'x'], msg: 'Thiếu' }]), 'x: Thiếu');
    assert.equal(formatter('Lỗi chuỗi'), 'Lỗi chuỗi');
    for (const page of ['frontend/admin.html', 'frontend/index.html']) {
        assert(fs.readFileSync(page, 'utf8').includes('auth.js?v=102.06'), `${page} nạp auth.js?v=102.06`);
    }

    assert(fs.readFileSync('frontend/admin.html', 'utf8').includes('js/project_reports.js?v=1.05'));
    assert(fs.readFileSync('frontend/admin.html', 'utf8').includes('js/project_management.js?v=2.23'));
    console.log('Handover lock self-check: OK');
})().catch(error => {
    console.error(error);
    process.exit(1);
});
