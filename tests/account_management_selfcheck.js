const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('frontend/auth.js', 'utf8');
const adminHtml = fs.readFileSync('frontend/admin.html', 'utf8');
const indexHtml = fs.readFileSync('frontend/index.html', 'utf8');
const fields = {
    newUsername: { value: 'worker' },
    newPassword: { value: 'password123' },
    newFullName: { value: '' },
    newPhoneNumber: { value: '0909' },
};
const requests = [];
const sandbox = {
    console,
    alert() {},
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
    window: { location: { pathname: '/admin.html' } },
    async fetch(url, options) {
        requests.push({ url, options });
        return { status: 200, async json() { return { status: 'ok', data: [] }; } };
    },
};

vm.createContext(sandbox);
vm.runInContext(source, sandbox);
sandbox.checkAuth();

(async () => {
    assert.equal(sandbox.userDisplayName({ full_name: 'Nguyễn Văn A', username: 'worker' }), 'Nguyễn Văn A');
    assert.equal(sandbox.userDisplayName({ full_name: ' ', username: 'worker' }), 'worker');

    await sandbox.createUser();
    const request = requests.find(item => item.options.method === 'POST');
    assert.equal(request.url, '/api/users');
    assert.equal(request.options.headers['Content-Type'], 'application/json');
    assert.deepEqual(JSON.parse(request.options.body), {
        username: 'worker',
        password: 'password123',
        full_name: '',
        phone_number: '0909',
    });

    assert.ok(adminHtml.includes('class="col-12 collapse" id="createUserPanel"'));
    assert.ok(adminHtml.includes('id="changePasswordModal"'));
    assert.ok(adminHtml.includes('id="editUserModal"'));
    assert.ok(adminHtml.includes('<th>Họ và tên</th>'));
    assert.ok(indexHtml.includes('id="userNameText"'));
    console.log('Account management self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
