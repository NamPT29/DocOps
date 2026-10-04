// Nhiệm vụ 1c: lock / unlock accounts from the admin user list.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const authSource = fs.readFileSync('frontend/auth.js', 'utf8');
const adminHtml = fs.readFileSync('frontend/admin.html', 'utf8');
const formRenderer = fs.readFileSync('frontend/js/form_renderer.js', 'utf8');

assert.match(adminHtml, /<ul id="editUserLockHistory"[^>]*>/);
assert.match(authSource, /'lock-user': trigger => lockUser\(/);
assert.match(authSource, /'unlock-user': trigger => unlockUser\(/);
const historyRenderer = authSource.match(/function renderUserLockHistory[\s\S]*?\n\}/)[0];
assert.doesNotMatch(historyRenderer, /innerHTML/, 'Lock reasons are user text: render with textContent.');

const users = [
    { id: 1, username: 'admin', role: 'admin', account_type: 'staff', is_locked: false, active_session_count: 1 },
    { id: 2, username: 'nv1', role: 'user', account_type: 'staff', is_locked: false, active_session_count: 0 },
    { id: 3, username: 'nv2', role: 'user', account_type: 'staff', is_locked: true, active_session_count: 0 },
];
const tableBody = { innerHTML: '' };
const historyList = {
    children: [],
    replaceChildren() { this.children = []; },
    appendChild(child) { this.children.push(child); },
};
const prompts = [];
const alerts = [];
const requests = [];
const sandbox = {
    console,
    alert(message) { alerts.push(message); },
    confirm() { return true; },
    document: {
        addEventListener() {},
        getElementById(id) {
            if (id === 'adminUsersTableBody') return tableBody;
            if (id === 'editUserLockHistory') return historyList;
            return null;
        },
        createElement() { return { className: '', textContent: '' }; },
    },
    localStorage: {
        getItem(key) {
            if (key === 'token') return 'token';
            if (key === 'user') return JSON.stringify({ id: 1, username: 'admin', role: 'admin' });
            return null;
        },
        setItem() {},
        removeItem() {},
    },
    window: {
        location: { pathname: '/admin.html' },
        addEventListener() {},
        setInterval() { return 1; },
        prompt(message) { return prompts.shift(); },
    },
    async fetch(url, options = {}) {
        requests.push({ url, method: options.method || 'GET', body: options.body });
        const data = url === '/api/users' ? users : [];
        return { status: 200, async json() { return { status: 'ok', data, revoked_sessions: 2 }; } };
    },
};
vm.createContext(sandbox);
vm.runInContext(formRenderer.match(/function escapeHTML\(str\) \{[\s\S]*?\n\}/)[0], sandbox);
vm.runInContext(authSource, sandbox);
sandbox.checkAuth();

// Session heartbeats also POST; only user-management calls matter here.
const posted = () => requests.filter(
    item => item.method === 'POST' && item.url.startsWith('/api/users/'),
);

(async () => {
    // The list offers Khóa / Mở khóa for others, never for the signed-in admin.
    await sandbox.fetchAdminData();
    assert.doesNotMatch(tableBody.innerHTML, /data-auth-action="(un)?lock-user" data-user-id="1"/);
    assert.match(tableBody.innerHTML, /data-auth-action="lock-user" data-user-id="2"/);
    assert.match(tableBody.innerHTML, /data-auth-action="unlock-user" data-user-id="3"/);
    assert.match(tableBody.innerHTML, /Đã khóa/);

    // Locking needs a reason; cancelling or a blank reason sends nothing.
    prompts.push(null, '   ', 'Nghỉ việc');
    await sandbox.lockUser(2, 'nv1');
    await sandbox.lockUser(2, 'nv1');
    assert.equal(posted().length, 0);
    assert.match(alerts.pop(), /Cần nêu lý do/);
    await sandbox.lockUser(2, 'nv1');
    assert.deepEqual(posted().map(item => [item.url, JSON.parse(item.body)]), [
        ['/api/users/2/lock', { reason: 'Nghỉ việc' }],
    ]);
    assert.match(alerts.pop(), /thu hồi 2 phiên/);

    // Unlocking accepts an empty reason (sent as null) and can be cancelled.
    requests.length = 0;
    prompts.push(null, '');
    await sandbox.unlockUser(3, 'nv2');
    await sandbox.unlockUser(3, 'nv2');
    assert.deepEqual(posted().map(item => [item.url, JSON.parse(item.body)]), [
        ['/api/users/3/unlock', { reason: null }],
    ]);

    sandbox.renderUserLockHistory([
        { action: 'unlock', actor: 'admin', reason: null, created_at: '2026-10-04T03:00:00+00:00' },
        { action: 'lock', actor: 'admin', reason: '<b>Nghỉ việc</b>', created_at: '2026-10-04T02:00:00+00:00' },
    ]);
    const lines = historyList.children.map(item => item.textContent);
    assert.equal(lines.length, 2);
    assert.match(lines[0], /Mở khóa bởi admin$/);
    assert.match(lines[1], /Khóa bởi admin – Lý do: <b>Nghỉ việc<\/b>$/, 'Reasons stay plain text.');
    sandbox.renderUserLockHistory([]);
    assert.match(historyList.children[0].textContent, /Chưa có lần khóa/);

    console.log('Account lock self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
