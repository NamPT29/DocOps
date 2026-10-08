// F2: bộ nhớ đệm GET của apiCall phải bị xóa sau lệnh ghi (tạo từ điển, tải biểu mẫu, lưu cấu hình...)
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

const authSource = fs.readFileSync('frontend/auth.js', 'utf8');
const formRenderer = fs.readFileSync('frontend/js/form_renderer.js', 'utf8');
const gets = [];
let dictionaries = ['DM_A'];
let failNext = false;
const sandbox = {
    console, setTimeout, clearTimeout,
    alert() {},
    document: { addEventListener() {}, getElementById() { return null; } },
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    window: { location: { pathname: '/admin.html' }, addEventListener() {}, setInterval() { return 1; } },
    async fetch(url, options = {}) {
        const method = options.method || 'GET';
        if (method === 'GET') gets.push(url);
        if (method === 'POST' && url.endsWith('/dictionaries')) {
            if (failNext) { failNext = false; return { status: 400, async json() { return { status: 'error', message: 'trùng tên' }; } }; }
            dictionaries = [...dictionaries, JSON.parse(options.body).name];
        }
        return { status: 200, async json() { return { status: 'ok', data: [...dictionaries] }; } };
    },
};
vm.createContext(sandbox);
vm.runInContext(formRenderer.match(/function escapeHTML\(str\) \{[\s\S]*?\n\}/)[0], sandbox);
vm.runInContext(authSource, sandbox);
const call = (url, options) => withTimeout(sandbox.apiCall(url, options), url);
const count = url => gets.filter(item => item === url).length;

(async () => {
    const list = '/api/templates/5/dictionaries';
    // GET trong 5 giây vẫn dùng bộ nhớ đệm như cũ
    assert.deepEqual((await call(list)).data, ['DM_A']);
    assert.deepEqual((await call(list)).data, ['DM_A']);
    assert.equal(count(list), 1, 'đọc lặp lại trong 5 giây dùng bộ nhớ đệm');
    await call('/api/templates');
    await call('/api/users');

    // Tạo từ điển (POST) rồi đọc lại ngay: phải thấy từ điển mới
    await call(list, { method: 'POST', headers: {}, body: JSON.stringify({ name: 'DM_TheLoaiVanBan' }) });
    assert.deepEqual((await call(list)).data, ['DM_A', 'DM_TheLoaiVanBan'], 'danh sách sau khi tạo phải có từ điển mới');
    assert.equal(count(list), 2);
    await call('/api/templates');
    await call('/api/users');
    assert.equal(count('/api/templates'), 2, 'lệnh ghi xóa cả bộ nhớ đệm danh sách biểu mẫu');
    assert.equal(count('/api/users'), 2, 'lệnh ghi xóa cả bộ nhớ đệm người dùng');

    // Lệnh ghi bị lỗi cũng xóa bộ nhớ đệm (máy chủ có thể đã đổi một phần)
    failNext = true;
    assert.equal(await call(list, { method: 'POST', headers: {}, body: JSON.stringify({ name: 'X' }) }), null);
    await call(list);
    assert.equal(count(list), 3);

    // PUT cấu hình rồi mở lại ngay: không được đọc cấu hình cũ trong bộ nhớ đệm
    const config = '/api/templates/5';
    await call(config);
    await call(config, { method: 'PUT', headers: {}, body: '{}' });
    await call(config);
    assert.equal(count(config), 2, 'mở lại cấu hình ngay sau khi lưu phải đọc bản mới');

    for (const page of ['frontend/admin.html', 'frontend/index.html']) {
        assert(fs.readFileSync(page, 'utf8').includes('auth.js?v=102.05'), `${page} phải nạp auth.js?v=102.05`);
    }
    console.log('API cache self-check: OK');
})().catch(error => {
    console.error(error);
    process.exit(1);
});
