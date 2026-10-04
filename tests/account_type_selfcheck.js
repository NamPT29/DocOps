// FR-AUT-02/03: account type (Hành chính/CTV) and CTV expiry in the admin UI.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const authSource = fs.readFileSync('frontend/auth.js', 'utf8');
const adminHtml = fs.readFileSync('frontend/admin.html', 'utf8');
const adminPage = fs.readFileSync('frontend/admin-page.js', 'utf8');
const management = fs.readFileSync('frontend/js/project_management.js', 'utf8');
const workflow = fs.readFileSync('frontend/js/project_workflow.js', 'utf8');

// Markup: CSP-safe toggles, and the form offers only Hành chính / CTV.
for (const prefix of ['new', 'edit']) {
    const select = adminHtml.match(new RegExp(`<select id="${prefix}AccountType"[^>]*>([\\s\\S]*?)</select>`));
    assert.ok(select, `${prefix}AccountType select must exist`);
    assert.match(select[0], new RegExp(`data-admin-change="sync-${prefix}-account-expiry"`));
    assert.doesNotMatch(select[0], /\son[a-z]+=/i, 'No inline event handlers (CSP).');
    const values = Array.from(select[1].matchAll(/value="([^"]+)"/g), match => match[1]);
    assert.deepEqual(values, ['staff', 'ctv'], 'Admin is not selectable as an account type.');
    assert.match(adminHtml, new RegExp(`id="${prefix}ExpiresOnGroup" class="d-none"`));
    assert.match(adminHtml, new RegExp(`<input type="date" id="${prefix}ExpiresOn"`));
    assert.match(adminPage, new RegExp(`'sync-${prefix}-account-expiry': \\(\\) => syncAccountExpiryField\\('${prefix}'\\)`));
}
assert.match(adminHtml, /<th>Loại tài khoản<\/th>/);
assert.match(adminHtml, /<td colspan="8" class="text-center">Đang tải\.\.\.<\/td>/);

function classList(initial) {
    const names = new Set(initial);
    return {
        contains: name => names.has(name),
        toggle(name, force) {
            const on = force === undefined ? !names.has(name) : Boolean(force);
            if (on) names.add(name); else names.delete(name);
            return on;
        },
    };
}

const fields = {
    newUsername: { value: 'ctv01' },
    newPassword: { value: 'password123' },
    newFullName: { value: '' },
    newPhoneNumber: { value: '' },
    newMaxConcurrentSessions: { value: '1' },
    newAccountType: { value: 'ctv', disabled: false },
    newExpiresOn: { value: '' },
    newExpiresOnGroup: { classList: classList(['d-none']) },
};
const alerts = [];
const requests = [];
const sandbox = {
    console,
    alert(message) { alerts.push(message); },
    document: {
        addEventListener() {},
        getElementById(id) { return fields[id] || null; },
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
    window: { location: { pathname: '/admin.html' }, addEventListener() {}, setInterval() { return 1; } },
    async fetch(url, options) {
        requests.push({ url, options });
        return { status: 200, async json() { return { status: 'ok', data: [] }; } };
    },
};
vm.createContext(sandbox);
// escapeHTML comes from form_renderer.js, which admin.html loads alongside auth.js.
const formRenderer = fs.readFileSync('frontend/js/form_renderer.js', 'utf8');
vm.runInContext(formRenderer.match(/function escapeHTML\(str\) \{[\s\S]*?\n\}/)[0], sandbox);
vm.runInContext(authSource, sandbox);
sandbox.checkAuth();

(async () => {
    // The expiry field shows only for CTV.
    sandbox.syncAccountExpiryField('new');
    assert.equal(fields.newExpiresOnGroup.classList.contains('d-none'), false);
    fields.newAccountType.value = 'staff';
    sandbox.syncAccountExpiryField('new');
    assert.equal(fields.newExpiresOnGroup.classList.contains('d-none'), true);

    // A CTV needs an expiry date before anything is sent.
    fields.newAccountType.value = 'ctv';
    await sandbox.createUser();
    assert.equal(requests.filter(item => item.url === '/api/users').length, 0);
    assert.match(alerts.pop(), /ngày hết hạn/);

    fields.newExpiresOn.value = '2026-10-31';
    await sandbox.createUser();
    const created = requests.find(item => item.url === '/api/users');
    const body = JSON.parse(created.options.body);
    assert.equal(body.account_type, 'ctv');
    assert.equal(body.expires_on, '2026-10-31');
    assert.equal(fields.newAccountType.value, 'staff', 'The form resets to Hành chính.');

    const expired = sandbox.accountTypeCellHtml({
        role: 'user', account_type: 'ctv', expires_on: '2026-10-31', is_expired: true,
    });
    assert.match(expired, />CTV</);
    assert.match(expired, /HSD 31\/10\/2026/);
    assert.match(expired, /Hết hạn/);
    assert.match(sandbox.accountTypeCellHtml({ role: 'admin', account_type: 'staff' }), />Admin</);
    assert.match(sandbox.accountTypeCellHtml({ role: 'user', account_type: 'staff' }), />Hành chính</);

    // Reviewer pickers never list CTV accounts (BA 3.3: check nhập liệu).
    const pm = { console, document: { getElementById() { return null; } } };
    vm.createContext(pm);
    vm.runInContext(`${management}\nthis.__api = { projectReviewerCandidates, projectUserLabel };`, pm);
    const users = [
        { id: 1, username: 'boss', role: 'admin', account_type: 'staff' },
        { id: 2, username: 'staff1', role: 'user', account_type: 'staff' },
        { id: 3, username: 'ctv1', role: 'user', account_type: 'ctv' },
    ];
    assert.deepEqual(Array.from(pm.__api.projectReviewerCandidates(users), user => user.id), [1, 2]);
    assert.equal(pm.__api.projectUserLabel(users[2]), 'ctv1 (CTV)');

    // Workflow stage pickers follow allowed_roles by account type.
    const wf = { console, projectManagementUsers: [], projectManagementProjects: [] };
    vm.createContext(wf);
    vm.runInContext(`${workflow}\nthis.__api = { workflowAccountType };`, wf);
    assert.deepEqual(users.map(user => wf.__api.workflowAccountType(user)), ['admin', 'staff', 'ctv']);
    assert.match(workflow, /allowed\.includes\(workflowAccountType\(user\)\)/);

    console.log('Account type self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
