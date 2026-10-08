// Kế hoạch chuẩn hóa (lát G1): nút trong menu dự án tải Excel từ /api/projects/{id}/normalization-plan
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
    let ok = await withTimeout(sandbox.downloadNormalizationPlan({ id: 7, name: 'Bộ Y tế' }), 'tải kế hoạch');
    assert.equal(ok, true);
    assert.deepEqual(calls.fetch, ['/api/projects/7/normalization-plan']);
    assert.equal(calls.download.length, 1);
    assert.equal(calls.download[0].response, reply);
    assert.equal(calls.download[0].fallback, 'Ke_hoach_chuan_hoa_7.xlsx');
    assert.match(status.textContent, /Đã tải kế hoạch chuẩn hóa của “Bộ Y tế”/);
    assert.match(status.textContent, /Vấn đề/);
    assert.equal(calls.alerts.length, 0);

    // Lỗi từ máy chủ: báo lỗi rõ, không tải file
    reply = { ok: false, json: async () => ({ detail: 'Không tìm thấy dự án' }) };
    ok = await withTimeout(sandbox.downloadNormalizationPlan({ id: 8, name: 'X' }), 'lỗi máy chủ');
    assert.equal(ok, false);
    assert.equal(calls.download.length, 1, 'lỗi thì không tải file');
    assert.equal(status.className.includes('text-danger'), true);
    assert.deepEqual(calls.alerts, ['Lỗi lập kế hoạch chuẩn hóa: Không tìm thấy dự án']);

    // Dự án không hợp lệ: không gọi API
    ok = await withTimeout(sandbox.downloadNormalizationPlan({ id: 0 }), 'dự án rỗng');
    assert.equal(ok, false);
    assert.equal(calls.fetch.length, 2);

    // Menu dự án có mục gọi đúng hàm; admin.html nạp bản mới
    const menu = fs.readFileSync('frontend/js/project_management.js', 'utf8');
    assert.match(menu, /label: 'Kế hoạch chuẩn hóa \(Excel\)',\s*icon: 'fa-list-check',\s*handler: \(\) => downloadNormalizationPlan\(project\)/);
    const html = fs.readFileSync('frontend/admin.html', 'utf8');
    assert(html.includes('js/project_reports.js?v=1.02'), 'admin.html phải nạp project_reports.js?v=1.02');
    assert(html.includes('js/project_management.js?v=2.18'), 'admin.html phải nạp project_management.js?v=2.18');
    console.log('Normalization plan self-check: OK');
})().catch(error => {
    console.error(error);
    process.exit(1);
});
