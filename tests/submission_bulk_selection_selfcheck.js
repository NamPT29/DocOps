const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function classList(initial = []) {
    const values = new Set(initial);
    return {
        toggle(name, force) {
            if (force) values.add(name);
            else values.delete(name);
        },
        contains(name) { return values.has(name); },
    };
}

function rowWithCheckbox(id) {
    const row = { classList: classList() };
    return {
        value: String(id),
        checked: false,
        closest: selector => selector === 'tr' ? row : null,
        row,
    };
}

const first = rowWithCheckbox(11);
const second = rowWithCheckbox(12);
const elements = {
    selectedSubmissionsCount: { textContent: '', classList: classList(['bg-light', 'text-dark']) },
    selectAllSubmissionsBtn: {
        disabled: false,
        classList: classList(['btn-outline-primary']),
        attributes: {},
        setAttribute(name, value) { this.attributes[name] = value; },
    },
    clearSubmissionSelectionBtn: { disabled: true },
    bulkDeleteSubmissionsBtn: { disabled: true },
    bulkSubmitSubmissionsBtn: { disabled: true },
};
const sandbox = {
    document: {
        getElementById: id => elements[id] || null,
        querySelectorAll: selector => selector === '.submission-select-checkbox' ? [first, second] : [],
    },
    console,
    URL,
    window: { location: { origin: 'http://localhost', pathname: '/index.html' } },
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/admin_panel.js', 'utf8'), sandbox);
vm.runInContext("selectableSubmissionStatuses.set(11, 'draft'); selectableSubmissionStatuses.set(12, 'draft');", sandbox);

sandbox.toggleSubmissionSelection(11, true);
assert.equal(first.checked, true);
assert.equal(first.row.classList.contains('table-success'), true);
assert.equal(second.row.classList.contains('table-success'), false);
assert.equal(elements.selectedSubmissionsCount.textContent, 'Đã chọn: 1');
assert.equal(elements.selectedSubmissionsCount.classList.contains('bg-primary'), true);

sandbox.selectAllSubmissionsOnPage();
assert.equal(first.row.classList.contains('table-success'), true);
assert.equal(second.row.classList.contains('table-success'), true);
assert.equal(elements.selectAllSubmissionsBtn.classList.contains('btn-primary'), true);
assert.equal(elements.selectAllSubmissionsBtn.attributes['aria-pressed'], 'true');
assert.equal(elements.bulkSubmitSubmissionsBtn.disabled, false);

sandbox.clearSubmissionSelection();
assert.equal(first.row.classList.contains('table-success'), false);
assert.equal(second.row.classList.contains('table-success'), false);
assert.equal(elements.selectAllSubmissionsBtn.classList.contains('btn-outline-primary'), true);
assert.equal(elements.selectedSubmissionsCount.textContent, 'Đã chọn: 0');
assert.equal(elements.bulkSubmitSubmissionsBtn.disabled, true);

console.log('Submission bulk selection self-check: OK');

const employeeHtml = fs.readFileSync('frontend/index.html', 'utf8');
const adminPanelSource = fs.readFileSync('frontend/js/admin_panel.js', 'utf8');
assert.equal(employeeHtml.includes('bulkSubmitSubmissionsBtn'), true);
assert.equal(employeeHtml.includes('data-action="bulkSubmitSelectedSubmissions"'), true);
assert.equal(adminPanelSource.includes('function bulkSubmitSelectedSubmissions'), true);
assert.equal(adminPanelSource.includes("runBulkSubmissionAction('submit_for_review')"), true);
