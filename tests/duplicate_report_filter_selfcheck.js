const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const adminHtml = fs.readFileSync('frontend/admin.html', 'utf8');
const employeeHtml = fs.readFileSync('frontend/index.html', 'utf8');
const source = fs.readFileSync('frontend/js/admin_panel.js', 'utf8');

assert(adminHtml.includes('id="filterReviewDuplicates"'));
assert(adminHtml.includes('id="filterCompletedDuplicates"'));
assert(employeeHtml.includes('id="filterReviewDuplicates"'));

const calls = [];
const elements = {
    filterReviewDuplicates: { checked: true },
    filterCompletedDuplicates: { checked: true },
    filterReviewTemplateId: { value: '' },
    filterTemplateId: { value: '', options: [{}, {}] },
    filterStartDate: { value: '' },
    filterEndDate: { value: '' },
    reviewTableBody: { innerHTML: '' },
    submissionsTableBody: { innerHTML: '' },
    reviewSubmissionsPagination: { innerHTML: '', appendChild() {} },
    submissionsPagination: { innerHTML: '', appendChild() {} },
    selectedReviewFolderTitle: { textContent: '' },
    selectedCompletedFolderTitle: { textContent: '' },
    reviewFolderTree: { innerHTML: '', appendChild() {} },
    completedFolderTree: { innerHTML: '', appendChild() {} },
};

const sandbox = {
    URL,
    currentUser: { id: 1, role: 'admin' },
    window: { location: { origin: 'http://127.0.0.1', pathname: '/admin.html' } },
    document: {
        getElementById(id) { return elements[id] || null; },
        createElement(tagName) {
            return {
                tagName,
                style: {},
                dataset: {},
                className: '',
                innerHTML: '',
                textContent: '',
                appendChild() {},
            };
        },
    },
    apiCall: async url => {
        const parsed = new URL(String(url));
        calls.push(parsed);
        if (parsed.pathname === '/api/review-folders') {
            return { data: [{ folder_path: '004/0099', submitted_count: 1, total_documents: 1 }] };
        }
        if (parsed.pathname === '/api/completed-folders') {
            return { data: [{ folder_path: '004/0099', folder_name: '0099', approved_count: 1 }] };
        }
        return { data: [], pagination: { page: 1, page_size: 20, total: 0, total_pages: 1 } };
    },
    escapeHTML: value => String(value),
    console,
    alert() {},
    confirm() { return true; },
};

vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: 'frontend/js/admin_panel.js' });

(async () => {
    await sandbox.fetchReviewSubmissions();
    await sandbox.selectReviewFolder('004/0099');
    await sandbox.fetchCompletedSubmissions();

    const relevant = calls.filter(url => [
        '/api/review-folders',
        '/api/review-folder-submissions',
        '/api/completed-folders',
        '/api/submissions',
    ].includes(url.pathname));
    assert.equal(relevant.length, 4);
    relevant.forEach(url => assert.equal(url.searchParams.get('duplicate_only'), 'true'));
    console.log('Duplicate report filter UI self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
