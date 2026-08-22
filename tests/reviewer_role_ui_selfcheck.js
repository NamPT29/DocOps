const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const adminHtml = fs.readFileSync('frontend/admin.html', 'utf8');
const employeeHtml = fs.readFileSync('frontend/index.html', 'utf8');
const calls = [];
const reviewTableBody = { innerHTML: '' };
const reviewFolderTree = {
    innerHTML: '',
    children: [],
    appendChild(child) { this.children.push(child); },
};
const selectedReviewFolderTitle = { textContent: '' };
const sandbox = {
    URL,
    currentUser: { id: 3, role: 'user', can_input: true, can_review: true },
    window: { location: { origin: 'http://localhost', pathname: '/index.html' } },
    document: {
        getElementById(id) {
            if (id === 'reviewTableBody') return reviewTableBody;
            if (id === 'reviewFolderTree') return reviewFolderTree;
            if (id === 'selectedReviewFolderTitle') return selectedReviewFolderTitle;
            if (id === 'filterReviewTemplateId') return null;
            return null;
        },
        createElement(tagName) {
            return {
                tagName,
                innerHTML: '',
                style: {},
                dataset: {},
                classList: { add() {}, toggle() {} },
            };
        },
    },
    apiCall: async url => {
        calls.push(String(url));
        if (String(url).includes('/api/review-folders')) {
            return {
                status: 'ok',
                data: [{
                    folder_path: '00000000/004/0011',
                    submitted_count: 0,
                    total_documents: 3,
                    input_names: ['nhap-1'],
                }],
            };
        }
        return { status: 'ok', data: [] };
    },
    escapeHTML: value => String(value),
    console,
    alert() {},
    confirm() { return true; },
};

assert(!adminHtml.includes('data-bs-target="#inventory-pane"'));
assert(!adminHtml.includes('data-bs-target="#assignment-pane"'));
assert(!adminHtml.includes('Kho Tài liệu &amp; Phân công'));
assert(!adminHtml.includes('id="assignmentPermissionsTableBody"'));
assert(!adminHtml.includes('fetchAssignmentPermissions()'));
assert(!adminHtml.includes('id="assignInputUserCheckboxes"'));
assert(!adminHtml.includes('id="assignReviewerCheckboxes"'));
assert(!adminHtml.includes('id="assignmentRevocationTableBody"'));
assert(!adminHtml.includes('id="reassignReviewerCheckboxes"'));
assert(!adminHtml.includes('id="reviewerFolderReassignmentPreview"'));
assert(adminHtml.includes('auth.js?v=100.01'));
assert(adminHtml.includes('js/admin_panel.js?v=202.01'));
assert(employeeHtml.includes('js/admin_panel.js?v=202.01'));
assert(!adminHtml.includes('id="reviewFolderTree"'));
assert(employeeHtml.includes('id="reviewFolderTree"'));
assert(!adminHtml.includes('id="newUserCanReview"'));
assert(!adminHtml.includes('id="newUserCanInput"'));
assert(employeeHtml.includes('id="employee-review-tab"'));
assert(employeeHtml.includes('id="reviewTableBody"'));
assert(employeeHtml.includes('id="noAssignmentNotice"'));

const authSource = fs.readFileSync('frontend/auth.js', 'utf8');
assert(!authSource.includes('async function fetchAssignmentPermissions()'));
assert(!authSource.includes('/capabilities'));
assert(authSource.includes("apiCall('/api/me'"));

const assignmentSource = fs.readFileSync('frontend/js/admin_panel.js', 'utf8');
assert(assignmentSource.includes('input_user_ids: inputUserIds'));
assert(assignmentSource.includes('reviewer_user_ids: reviewerUserIds'));
assert(assignmentSource.includes('formatApiErrorDetail(data.detail'));
assert(assignmentSource.includes('async function revokeAssignments('));
assert(assignmentSource.includes('/api/documents/assignments/revoke'));
assert(assignmentSource.includes("const canDelete = sub.status === 'draft'"));
assert(assignmentSource.includes("canDelete ? `<button"));
assert(assignmentSource.includes('async function fetchReviewerReassignmentData('));
assert(assignmentSource.includes('async function reassignDocumentReviewer('));
assert(assignmentSource.includes('/api/documents/reviewer-folder-assignments'));
assert(assignmentSource.includes('/api/documents/reviewer-folders/redistribute'));
assert(assignmentSource.includes('reviewer_user_ids: reviewerUserIds'));

vm.createContext(sandbox);
vm.runInContext(
    fs.readFileSync('frontend/js/admin_panel.js', 'utf8'),
    sandbox,
    { filename: 'frontend/js/admin_panel.js' },
);

(async () => {
    await sandbox.fetchReviewSubmissions();
    const url = new URL(calls[0]);
    assert.equal(url.pathname, '/api/review-folders');
    assert.equal(reviewFolderTree.children.at(-1).dataset.folderPath, '00000000/004/0011');
    await sandbox.selectReviewFolder('00000000/004/0011');
    const folderUrl = new URL(calls[1]);
    assert.equal(folderUrl.pathname, '/api/review-folder-submissions');
    assert.equal(folderUrl.searchParams.get('folder_path'), '00000000/004/0011');
    assert(reviewTableBody.innerHTML.includes('chưa có báo cáo nào'));
    console.log('Reviewer role UI self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
