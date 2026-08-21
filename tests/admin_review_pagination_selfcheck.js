const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const reviewTableBody = {
    innerHTML: '',
    children: [],
    appendChild(child) { this.children.push(child); },
};
const reviewPagination = {
    innerHTML: '',
    children: [],
    appendChild(child) { this.children.push(child); },
};
const reviewFolderTree = {
    innerHTML: '',
    children: [],
    appendChild(child) { this.children.push(child); },
};
const selectedReviewFolderTitle = { textContent: '' };
const calls = [];

const sandbox = {
    URL,
    console,
    currentUser: { id: 1, role: 'admin' },
    window: { location: { origin: 'http://127.0.0.1', pathname: '/admin.html' } },
    document: {
        getElementById(id) {
            if (id === 'reviewTableBody') return reviewTableBody;
            if (id === 'reviewSubmissionsPagination') return reviewPagination;
            if (id === 'reviewFolderTree') return reviewFolderTree;
            if (id === 'selectedReviewFolderTitle') return selectedReviewFolderTitle;
            if (id === 'filterReviewTemplateId') return { value: '' };
            return null;
        },
        createElement(tagName) {
            return {
                tagName,
                style: {},
                dataset: {},
                className: '',
                innerHTML: '',
                textContent: '',
                disabled: false,
                appendChild() {},
            };
        },
    },
    async apiCall(url) {
        calls.push(String(url));
        const parsed = new URL(String(url));
        if (parsed.pathname === '/api/review-folders') {
            return { data: [{
                folder_path: '004/0023',
                submitted_count: 21,
                total_documents: 21,
                input_names: ['nguoi-nhap'],
            }] };
        }
        return {
            data: [{
                id: 31,
                created_at: '2026-08-15 08:00:00',
                creator_name: 'nguoi-nhap',
                template: 'Mẫu kiểm duyệt',
                status: 'pending_review',
                has_errors: false,
            }],
            pagination: { page: Number(parsed.searchParams.get('page')), page_size: 20, total: 21, total_pages: 2, from: 21, to: 21 },
        };
    },
    escapeHTML: value => String(value),
    alert() {},
    confirm() { return true; },
};

const adminHtml = fs.readFileSync('frontend/admin.html', 'utf8');
const employeeHtml = fs.readFileSync('frontend/index.html', 'utf8');
assert(!adminHtml.includes('id="reviewSubmissionsPagination"'));
assert(adminHtml.includes('id="projectReportsPagination"'));
assert(employeeHtml.includes('id="reviewSubmissionsPagination"'));

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/admin_panel.js', 'utf8'), sandbox, {
    filename: 'frontend/js/admin_panel.js',
});

(async () => {
    await sandbox.fetchReviewSubmissions();
    await sandbox.selectReviewFolder('004/0023', 2);
    const reviewRequest = new URL(calls.at(-1));
    assert.equal(reviewRequest.pathname, '/api/review-folder-submissions');
    assert.equal(reviewRequest.searchParams.get('folder_path'), '004/0023');
    assert.equal(reviewRequest.searchParams.get('page'), '2');
    assert.equal(reviewRequest.searchParams.get('page_size'), '20');
    assert.equal(reviewPagination.children.length, 5);
    assert.equal(reviewPagination.children[2].disabled, false);
    assert.equal(reviewPagination.children[4].disabled, true);

    await reviewPagination.children[2].onclick();
    const previousPageRequest = new URL(calls.at(-1));
    assert.equal(previousPageRequest.searchParams.get('page'), '1');
    console.log('Admin review pagination self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
