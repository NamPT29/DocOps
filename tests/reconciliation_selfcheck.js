// Đối soát R1–R4 (lát R1): nút trong menu dự án tải Excel từ /api/projects/{id}/reconciliation
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
const calls = { fetch: [], download: [], alerts: [] };
let reply = { ok: true, json: async () => ({}) };

const sandbox = {
    console, setTimeout, clearTimeout,
    document: { getElementById: id => (id === 'projectExportStatus' ? status : null) },
    async authFetch(url) { calls.fetch.push(url); return reply; },
    async downloadExportResponse(response, fallback) { calls.download.push({ response, fallback }); },
    formatApiErrorDetail: detail => String(detail),
    alert: message => calls.alerts.push(message),
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/project_reports.js', 'utf8'), sandbox);

(async () => {
    // Tải thành công: gọi đúng API, đưa phản hồi cho hàm tải file, báo xong
    let ok = await withTimeout(sandbox.downloadReconciliation({ id: 7, name: 'Bộ Y tế' }), 'tải đối soát');
    assert.equal(ok, true);
    assert.deepEqual(calls.fetch, ['/api/projects/7/reconciliation']);
    assert.deepEqual(calls.download, [{ response: reply, fallback: 'Doi_soat_7.xlsx' }]);
    assert.match(status.textContent, /Đã tải đối soát R1–R4 của “Bộ Y tế”/);
    assert.equal(calls.alerts.length, 0);

    // Lỗi dạng {code, message}: báo đúng message, không tải file
    reply = { ok: false, json: async () => ({ detail: { code: 'project_not_found', message: 'Không tìm thấy dự án' } }) };
    ok = await withTimeout(sandbox.downloadReconciliation({ id: 8, name: 'X' }), 'lỗi 404');
    assert.equal(ok, false);
    assert.equal(calls.download.length, 1);
    assert.deepEqual(calls.alerts, ['Lỗi đối soát: Không tìm thấy dự án']);
    assert(status.className.includes('text-danger'));

    // Lỗi chuỗi (403)
    reply = { ok: false, json: async () => ({ detail: 'Access denied' }) };
    ok = await withTimeout(sandbox.downloadReconciliation({ id: 8, name: 'X' }), 'lỗi 403');
    assert.equal(calls.alerts[1], 'Lỗi đối soát: Access denied');

    // Dự án không hợp lệ: không gọi API
    assert.equal(await withTimeout(sandbox.downloadReconciliation({ id: 0 }), 'dự án rỗng'), false);
    assert.equal(calls.fetch.length, 3);

    const menu = fs.readFileSync('frontend/js/project_management.js', 'utf8');
    assert.match(menu, /label: 'Đối soát R1–R4 \(Excel\)',\s*icon: 'fa-scale-balanced',\s*handler: \(\) => downloadReconciliation\(project\)/);
    assert(fs.readFileSync('frontend/admin.html', 'utf8').includes('js/project_reports.js?v=1.04'));
    console.log('Reconciliation self-check: OK');
})().catch(error => {
    console.error(error);
    process.exit(1);
});
