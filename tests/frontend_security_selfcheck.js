const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const rows = [];
const tbody = {
    innerHTML: '',
    appendChild(row) { rows.push(row); },
};
const removedKeys = [];
const sandbox = {
    URL,
    console,
    currentUser: { id: 2, username: 'member' },
    window: {
        activeTemplateId: 11,
        location: { origin: 'http://localhost', pathname: '/admin.html' },
    },
    localStorage: {
        removeItem(key) { removedKeys.push(key); },
        getItem() { return null; },
        setItem() {},
    },
    document: {
        addEventListener() {},
        getElementById() { return tbody; },
        createElement() {
            return {
                innerHTML: '',
                classList: { add() {} },
            };
        },
    },
    setTimeout,
    clearTimeout,
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/form_renderer.js', 'utf8'), sandbox);
const adminPanelSource = [
    fs.readFileSync('frontend/js/admin_operations.js', 'utf8'),
    fs.readFileSync('frontend/js/admin_panel.js', 'utf8'),
].join('\n');
vm.runInContext(adminPanelSource, sandbox);

assert(adminPanelSource.includes('const safeUsername = escapeHTML(u.username);'));
assert(!adminPanelSource.includes('<td>${u.username}</td>'));
assert(!adminPanelSource.includes('${u.username} <span class="text-muted small">'));

assert.equal(sandbox.getDraftStorageKey(), 'formDraft_2_none_11_none');
sandbox.window.activeTemplateId = 12;
assert.equal(sandbox.getDraftStorageKey(), 'formDraft_2_none_12_none');
sandbox.removeCurrentFormDraft();
assert.deepEqual(removedKeys, ['formDraft_2_none_12_none']);

sandbox.renderAdminSubmissionsTable([{
    id: 4,
    created_at: '<img src=x onerror=alert(1)>',
    creator_name: '<script>creator()</script>',
    ho_ten: '<img src=x onerror=alert(2)>',
    so_giay_to: '<svg onload=alert(3)>',
    template: '<iframe srcdoc=x>',
    pdf_relative_path: '<img src=x onerror=alert(2)>',
    status: 'pending_review',
    has_errors: false,
}], 'submissionsTableBody', true);

assert.equal(rows.length, 1);
assert(!rows[0].innerHTML.includes('<script>creator()</script>'));
assert(!rows[0].innerHTML.includes('<img src=x'));
assert(rows[0].innerHTML.includes('&lt;script&gt;creator()&lt;/script&gt;'));
assert(rows[0].innerHTML.includes('&lt;img src=x onerror=alert(2)&gt;'));

console.log('Frontend security self-check: OK');
