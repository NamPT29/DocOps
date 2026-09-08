const assert = require('node:assert/strict');
const fs = require('node:fs');

const panel = fs.readFileSync('frontend/js/admin_panel.js', 'utf8');
const operations = fs.readFileSync('frontend/js/admin_operations.js', 'utf8');

assert(operations.includes('// === POOL & ASSIGNMENT LOGIC ==='));
assert(operations.includes('async function fetchDocumentStats()'));
assert(operations.includes('async function fetchDocumentInventory('));
assert(operations.includes('async function revokeAssignments('));
assert(operations.includes('async function uploadAndAssign()'));
assert(!panel.includes('async function fetchDocumentStats()'));
assert(panel.includes('const ADMIN_GENERATED_PAGINATION_ACTIONS'));

for (const page of ['frontend/admin.html', 'frontend/index.html', 'frontend/temp.html']) {
    const html = fs.readFileSync(page, 'utf8');
    const operationsIndex = html.indexOf('js/admin_operations.js?v=1.00');
    const panelIndex = html.indexOf('js/admin_panel.js?v=203.06');
    assert(operationsIndex >= 0, `${page} must load admin_operations.js.`);
    assert(panelIndex > operationsIndex, `${page} must load admin operations before admin panel events.`);
}

console.log('Admin operations split self-check: OK');
