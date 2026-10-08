// Đóng gói bàn giao (lát G2): menu dự án gửi lệnh, theo dõi tiến độ tới khi xong hoặc lỗi.
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

const status = { textContent: '', className: '' };
const history = [];
let requests = [];
let replies = [];
let alerts = [];
let confirmAnswer = true;
const downloads = [];
const reply = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

const sandbox = {
    console, setTimeout, clearTimeout,
    document: { getElementById: id => (id === 'projectExportStatus' ? status : null) },
    async authFetch(url, options = {}) {
        requests.push({ url, method: options.method || 'GET' });
        return replies.shift();
    },
    formatApiErrorDetail: detail => String(detail),
    async downloadExportResponse(response, fallback) { downloads.push({ response, fallback }); },
    alert: message => alerts.push(message),
    confirm: () => confirmAnswer,
};
Object.defineProperty(status, 'text', { get() { return this.textContent; } });
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/project_reports.js', 'utf8'), sandbox);
const watch = () => { const original = sandbox.setProjectExportStatus; sandbox.setProjectExportStatus = (m, e) => { history.push(m); original(m, e); }; };
watch();
const project = { id: 7, name: 'Bộ Y tế' };
const start = () => withTimeout(sandbox.startHandoverPackage(project, { pollMs: 0, maxPolls: 10 }), 'đóng gói');

(async () => {
    // Chạy tới xong: POST rồi GET đến khi done; hiện tiến độ và thông báo cuối
    replies = [
        reply(200, { status: 'ok', data: { state: 'queued' } }),
        reply(200, { data: { state: 'running', files_done: 5, files_total: 10 } }),
        reply(200, { data: { state: 'done', message: 'Đã đóng gói 2 hồ sơ vào D:/ban_giao/X.' } }),
    ];
    let job = await start();
    assert.equal(job.state, 'done');
    assert.deepEqual(requests.map(r => `${r.method} ${r.url}`), [
        'POST /api/projects/7/handover-package', 'GET /api/projects/7/handover-package', 'GET /api/projects/7/handover-package',
    ]);
    assert(history.includes('Đang đóng gói “Bộ Y tế”: 5/10 file (50%).'), 'phải hiện tiến độ');
    assert.equal(status.textContent, 'Đã đóng gói 2 hồ sơ vào D:/ban_giao/X.');
    assert.equal(alerts.length, 0);

    // Đang có lần đóng gói khác (409 "đang được đóng gói"): theo dõi tiếp, không báo lỗi
    requests = []; history.length = 0;
    replies = [
        reply(409, { detail: 'Dự án đang được đóng gói, hãy đợi lần đóng gói này xong.' }),
        reply(200, { data: { state: 'done', message: 'Xong' } }),
    ];
    job = await start();
    assert.equal(job.message, 'Xong');
    assert.equal(alerts.length, 0);

    // Chưa có hồ sơ sẵn sàng (409 khác): báo lỗi, không theo dõi
    requests = [];
    replies = [reply(409, { detail: 'Chưa có hồ sơ nào sẵn sàng đóng gói.' })];
    assert.equal(await start(), null);
    assert.equal(requests.length, 1);
    assert.deepEqual(alerts, ['Lỗi đóng gói: Chưa có hồ sơ nào sẵn sàng đóng gói.']);
    assert(status.className.includes('text-danger'));

    // Máy chủ báo lỗi giữa chừng
    alerts = [];
    replies = [reply(200, { data: { state: 'queued' } }), reply(200, { data: { state: 'error', message: 'Đóng gói thất bại: đĩa đầy' } })];
    assert.equal(await start(), null);
    assert.deepEqual(alerts, ['Lỗi đóng gói: Đóng gói thất bại: đĩa đầy']);

    // Bấm Hủy ở hộp xác nhận: không gửi gì
    requests = []; confirmAnswer = false;
    assert.equal(await start(), null);
    assert.equal(requests.length, 0);
    confirmAnswer = true;

    // Chạy quá số lần hỏi: báo còn chạy trên máy chủ
    alerts = [];
    replies = [reply(200, {}), ...Array.from({ length: 10 }, () => reply(200, { data: { state: 'running', files_done: 1, files_total: 9 } }))];
    assert.equal(await start(), null);
    assert.match(alerts[0], /vẫn đang chạy trên máy chủ/);

    // Tải biên bản (G3): gọi đúng API, đưa phản hồi cho hàm tải file; chưa đóng gói thì báo lỗi
    requests = []; alerts = [];
    const report = reply(200, {});
    replies = [report];
    assert.equal(await withTimeout(sandbox.downloadHandoverReport(project), 'tải biên bản'), true);
    assert.deepEqual(requests.map(r => `${r.method} ${r.url}`), ['GET /api/projects/7/handover-package/report']);
    assert.deepEqual(downloads, [{ response: report, fallback: 'Bien_ban_ban_giao_du_an_7.docx' }]);
    assert.equal(status.textContent, 'Đã tải biên bản bàn giao của “Bộ Y tế”.');
    replies = [reply(404, { detail: 'Chưa có lần đóng gói nào xong cho dự án này' })];
    assert.equal(await withTimeout(sandbox.downloadHandoverReport(project), 'biên bản 404'), false);
    assert.equal(downloads.length, 1);
    assert.deepEqual(alerts, ['Lỗi tải biên bản: Chưa có lần đóng gói nào xong cho dự án này']);

    const menu = fs.readFileSync('frontend/js/project_management.js', 'utf8');
    assert.match(menu, /label: 'Tải biên bản bàn giao',\s*icon: 'fa-file-signature',\s*handler: \(\) => downloadHandoverReport\(project\)/);
    assert.match(menu, /label: 'Đóng gói bàn giao',\s*icon: 'fa-box',\s*handler: \(\) => startHandoverPackage\(project\)/);
    assert(fs.readFileSync('frontend/admin.html', 'utf8').includes('js/project_reports.js?v=1.04'));
    console.log('Handover package self-check: OK');
})().catch(error => {
    console.error(error);
    process.exit(1);
});
