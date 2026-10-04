// BA 3.3: admins may enter data from the input page; BR-04 is enforced server side.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const indexPage = fs.readFileSync('frontend/index-page.js', 'utf8');
const adminHtml = fs.readFileSync('frontend/admin.html', 'utf8');
const indexHtml = fs.readFileSync('frontend/index.html', 'utf8');
const management = fs.readFileSync('frontend/js/project_management.js', 'utf8');
const adminPanel = fs.readFileSync('frontend/js/admin_panel.js', 'utf8');

// The admin page links to the input page in input mode (plain link, CSP-safe).
assert.match(adminHtml, /<a href="index\.html\?mode=input" id="adminInputModeLink"[^>]*>/);
assert.match(indexHtml, /src="index-page\.js\?v=1\.01"/);
// Input pickers list every account, admins included.
assert.doesNotMatch(management, /role !== 'admin'/, 'Admins must not be filtered out of input pickers.');
assert.match(management, /renderProjectUserOptions\('projectInputUsers', users, 'input'\)/);

function runIndexPage({ role, search }) {
    const listeners = {};
    const backButton = {
        href: 'admin.html#data',
        hidden: true,
        classList: { remove(name) { if (name === 'd-none') backButton.hidden = false; } },
    };
    const sandbox = {
        URLSearchParams,
        console,
        localStorage: {
            getItem(key) {
                if (key === 'token') return 'token';
                if (key === 'user') return JSON.stringify({ id: 1, username: 'u', role });
                return null;
            },
        },
        window: { location: { href: '/index.html', search } },
        document: {
            readyState: 'loading',
            addEventListener(type, handler) { listeners[type] = handler; },
            getElementById(id) { return id === 'backToAdminBtn' ? backButton : null; },
        },
    };
    vm.createContext(sandbox);
    vm.runInContext(indexPage, sandbox);
    listeners.DOMContentLoaded();
    return { href: sandbox.window.location.href, backButton };
}

let page = runIndexPage({ role: 'admin', search: '' });
assert.equal(page.href, '/admin.html', 'Without input mode an admin still lands on the admin page.');

page = runIndexPage({ role: 'admin', search: '?mode=input' });
assert.equal(page.href, '/index.html', 'Input mode keeps the admin on the input page.');
assert.equal(page.backButton.hidden, false);
assert.equal(page.backButton.href, '/admin.html#projects');

page = runIndexPage({ role: 'admin', search: '?check_id=7' });
assert.equal(page.href, '/index.html');
assert.equal(page.backButton.hidden, true, 'Review links keep their own return button logic (app.js).');

page = runIndexPage({ role: 'user', search: '' });
assert.equal(page.href, '/index.html');
assert.equal(page.backButton.hidden, true);

// The input page asks for "my" reports; the admin page keeps the full list.
async function submissionsUrl(pathname) {
    const urls = [];
    const sandbox = {
        URL,
        console,
        currentUser: { id: 1, role: 'admin' },
        window: { location: { origin: 'http://localhost', pathname } },
        document: {
            getElementById() { return null; },
            querySelectorAll() { return []; },
            createElement() { return { innerHTML: '', classList: { add() {}, toggle() {} } }; },
        },
        async apiCall(url) {
            urls.push(String(url));
            return { data: [], pagination: { page: 1, page_size: 20, total: 0, total_pages: 1, from: 0, to: 0 } };
        },
        escapeHTML: value => String(value ?? ''),
    };
    vm.createContext(sandbox);
    vm.runInContext(adminPanel, sandbox, { filename: 'frontend/js/admin_panel.js' });
    await sandbox.fetchSubmissions();
    return new URL(urls.find(url => url.includes('/api/submissions')));
}

(async () => {
    assert.equal((await submissionsUrl('/index.html')).searchParams.get('mine'), 'true');
    assert.equal((await submissionsUrl('/admin.html')).searchParams.has('mine'), false);
    console.log('Admin data entry self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
