const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const alerts = [];
let fetchCalls = 0;
const authSource = fs.readFileSync('frontend/auth.js', 'utf8');
const fields = {
    newUsername: { value: 'new-user' },
    newPassword: { value: '123' },
    newFullName: { value: '' },
    newPhoneNumber: { value: '' },
    newMaxConcurrentSessions: { value: '1' },
};
const sandbox = {
    console,
    alert(message) { alerts.push(message); },
    document: {
        addEventListener() {},
        getElementById(id) { return fields[id] || null; },
    },
    localStorage: {
        getItem() { return null; },
        setItem() {},
        removeItem() {},
    },
    window: { location: { pathname: '/admin.html' } },
    async fetch() {
        fetchCalls++;
        return {
            status: 422,
            async json() {
                return {
                    detail: [{
                        loc: ['body', 'password'],
                        msg: 'String should have at least 8 characters',
                    }],
                };
            },
        };
    },
};

vm.createContext(sandbox);
assert.ok(!authSource.includes('can_input: true'));
assert.ok(!authSource.includes('can_review: false'));
vm.runInContext(authSource, sandbox);

(async () => {
    await sandbox.createUser();
    assert.equal(fetchCalls, 0);
    assert.deepEqual(alerts, ['Mật khẩu phải có ít nhất 8 ký tự']);

    alerts.length = 0;
    await sandbox.apiCall('/api/users', { method: 'POST' });
    assert.deepEqual(alerts, [
        'Lỗi: password: String should have at least 8 characters',
    ]);

    console.log('Auth user self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
