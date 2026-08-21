const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const authSource = fs.readFileSync('frontend/auth.js', 'utf8');
const totalElement = { innerText: '0' };
const sandbox = {
    console,
    alert() {},
    document: {
        addEventListener() {},
        getElementById(id) {
            return id === 'dashTotalDocs' ? totalElement : null;
        },
    },
    localStorage: {
        getItem() { return null; },
        setItem() {},
        removeItem() {},
    },
    window: { location: { pathname: '/admin.html' } },
    async fetch() {
        throw new Error('fetch should be replaced before dashboard loading');
    },
};

vm.createContext(sandbox);
vm.runInContext(authSource, sandbox);
vm.runInContext(`
    currentUser = { role: 'admin' };
    apiCall = async (url) => {
        if (url === '/api/submissions') {
            return {
                status: 'ok',
                data: Array.from({ length: 20 }, (_, index) => ({ id: index + 1 })),
                pagination: { page: 1, page_size: 20, total: 1069 },
            };
        }
        return { status: 'ok', data: [] };
    };
    populateTemplatesDropdown = async () => {};
`, sandbox);

(async () => {
    await sandbox.fetchDashboardStats();
    assert.equal(
        totalElement.innerText,
        1069,
        'Dashboard must display pagination.total, not the 20 rows in the current page',
    );
    console.log('Dashboard total self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
