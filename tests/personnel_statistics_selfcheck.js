const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('frontend/admin.html', 'utf8');
const source = fs.readFileSync('frontend/auth.js', 'utf8');
const requests = [];
const userTable = { innerHTML: '' };
const statsTable = { innerHTML: '' };
const listeners = {};

assert(html.includes('id="personnelStatsTableBody"'));
assert(html.includes('Dự án đang tham gia'));
assert(html.includes('Báo cáo đã gửi'));
assert(html.includes('Báo cáo đã kiểm duyệt'));
assert(html.includes('Báo cáo lỗi nhập liệu'));
assert(html.includes('Trường lỗi kiểm tra'));
assert(!/<(?:style|script)\b(?![^>]*\bsrc=)/i.test(html));
assert(!/\bon[a-z]+\s*=/i.test(html));

const sandbox = {
    console,
    alert() {},
    escapeHTML: value => String(value),
    URL,
    URLSearchParams,
    document: {
        addEventListener(type, handler) { listeners[type] = handler; },
        getElementById(id) {
            if (id === 'adminUsersTableBody') return userTable;
            if (id === 'personnelStatsTableBody') return statsTable;
            return null;
        },
    },
    localStorage: {
        getItem(key) {
            if (key === 'token') return 'admin-token';
            if (key === 'user') return JSON.stringify({ id: 1, username: 'admin', role: 'admin' });
            return null;
        },
        setItem() {},
        removeItem() {},
    },
    window: { location: { pathname: '/admin.html', search: '', hash: '' } },
    async fetch(url) {
        requests.push(String(url));
        const payload = String(url) === '/api/users/personnel-stats'
            ? {
                status: 'ok',
                data: [{
                    user_id: 2,
                    username: 'worker',
                    full_name: 'Nguyễn Văn A',
                    active_project_count: 3,
                    submitted_report_count: 12,
                    reviewed_report_count: 8,
                    input_error_report_count: 2,
                    reviewer_error_field_count: 4,
                }],
            }
            : { status: 'ok', data: [] };
        return { status: 200, async json() { return payload; } };
    },
};

vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: 'frontend/auth.js' });
sandbox.checkAuth();

(async () => {
    await sandbox.fetchAdminData();
    assert(requests.includes('/api/users'));
    assert(requests.includes('/api/users/personnel-stats'));
    assert(statsTable.innerHTML.includes('Nguyễn Văn A'));
    assert(statsTable.innerHTML.includes('>3<'));
    assert(statsTable.innerHTML.includes('>12<'));
    assert(statsTable.innerHTML.includes('>8<'));
    assert(statsTable.innerHTML.includes('>2<'));
    assert(statsTable.innerHTML.includes('>4<'));

    requests.length = 0;
    sandbox.localStorage.getItem = key => {
        if (key === 'token') return 'user-token';
        if (key === 'user') return JSON.stringify({ id: 3, username: 'worker', role: 'user' });
        return null;
    };
    sandbox.checkAuth();
    await sandbox.fetchAdminData();
    assert.equal(requests.length, 0, 'Non-admin users must not request personnel statistics.');
    console.log('Personnel statistics self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
