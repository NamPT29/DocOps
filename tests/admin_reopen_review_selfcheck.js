const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const tableBody = {
    innerHTML: '',
    children: [],
    appendChild(child) { this.children.push(child); },
};
const pagination = { innerHTML: '', appendChild() {} };
const apiRequests = [];
let reviewRefreshes = 0;
let completedRefreshes = 0;

const sandbox = {
    URL,
    console,
    currentUser: { id: 1, role: 'admin' },
    window: {
        location: {
            origin: 'http://127.0.0.1',
            pathname: '/admin.html',
        },
    },
    document: {
        getElementById(id) {
            if (id === 'submissionsTableBody') return tableBody;
            if (id === 'submissionsPagination') return pagination;
            return null;
        },
        createElement(tagName) {
            return {
                tagName,
                style: {},
                dataset: {},
                className: '',
                innerHTML: '',
                appendChild() {},
            };
        },
    },
    escapeHTML: value => String(value),
    async apiCall(url, options) {
        apiRequests.push([url, options]);
        return { status: 'ok', new_status: 'pending_review', is_checked: false };
    },
    alert() {},
    confirm() { return true; },
};

vm.createContext(sandbox);
vm.runInContext(
    fs.readFileSync('frontend/js/admin_panel.js', 'utf8'),
    sandbox,
    { filename: 'frontend/js/admin_panel.js' },
);

const approvedSubmission = [{
    id: 41,
    serial_number: 1,
    created_at: '2026-08-14 10:00:00',
    creator_name: 'nguoi-nhap',
    template: 'Mẫu kiểm tra',
    pdf_relative_path: '0000/004/0011/0000130.pdf',
    status: 'completed',
    has_errors: false,
}];

(async () => {
    sandbox.renderAdminSubmissionsTable(
        approvedSubmission,
        'submissionsTableBody',
        false,
        { page: 1, total: 1, total_pages: 1, from: 1, to: 1 },
    );
    assert.equal(tableBody.children.length, 1);
    assert.match(tableBody.children[0].innerHTML, /Về chờ duyệt/);
    assert.match(tableBody.children[0].innerHTML, /data-admin-generated-action="reopen-submission"/);
    assert.match(tableBody.children[0].innerHTML, /data-submission-id="41"/);

    tableBody.children.length = 0;
    sandbox.renderAdminSubmissionsTable(
        [{ ...approvedSubmission[0], status: 'pending_input_confirmation' }],
        'submissionsTableBody',
        false,
        { page: 1, total: 1, total_pages: 1, from: 1, to: 1 },
    );
    assert.doesNotMatch(tableBody.children[0].innerHTML, /Về chờ duyệt/);

    tableBody.children.length = 0;
    sandbox.currentUser = { id: 2, role: 'user' };
    sandbox.renderAdminSubmissionsTable(
        approvedSubmission,
        'submissionsTableBody',
        false,
        { page: 1, total: 1, total_pages: 1, from: 1, to: 1 },
    );
    assert.doesNotMatch(tableBody.children[0].innerHTML, /Về chờ duyệt/);

    sandbox.currentUser = { id: 1, role: 'admin' };
    sandbox.fetchReviewSubmissions = async () => { reviewRefreshes++; };
    sandbox.fetchCompletedSubmissions = async () => { completedRefreshes++; };
    await sandbox.reopenSubmissionReview(41);

    assert.deepEqual(JSON.parse(JSON.stringify(apiRequests)), [[
        '/api/submissions/41/reopen-review',
        { method: 'PUT' },
    ]]);
    assert.equal(reviewRefreshes, 1);
    assert.equal(completedRefreshes, 1);
    console.log('Admin reopen review self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
