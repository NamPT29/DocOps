const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const filterTemplateId = {
    value: '',
    options: [{ value: '', textContent: '-- Tất cả Biểu mẫu --' }],
};
const submissionsTableBody = { innerHTML: '' };
const submissionsPagination = { innerHTML: '', appendChild() {} };
const selectedCompletedFolderTitle = { textContent: '' };
const completedFolderTree = {
    innerHTML: '',
    children: [],
    appendChild(child) { this.children.push(child); },
};
const calls = [];

const sandbox = {
    URL,
    window: {
        location: {
            origin: 'http://127.0.0.1',
            pathname: '/admin.html',
        },
    },
    document: {
        getElementById(id) {
            if (id === 'filterTemplateId') return filterTemplateId;
            if (id === 'filterStartDate' || id === 'filterEndDate') return { value: '' };
            if (id === 'submissionsTableBody') return submissionsTableBody;
            if (id === 'submissionsPagination') return submissionsPagination;
            if (id === 'selectedCompletedFolderTitle') return selectedCompletedFolderTitle;
            if (id === 'completedFolderTree') return completedFolderTree;
            return null;
        },
        createElement(tagName) {
            return {
                tagName,
                style: {},
                dataset: {},
                className: '',
                innerHTML: '',
            };
        },
    },
    populateTemplatesDropdown: async (elementId, keepDefault) => {
        calls.push(['populate', elementId, keepDefault]);
        filterTemplateId.options.push({ value: '2', textContent: 'Mẫu văn bản' });
    },
    apiCall: async url => {
        calls.push(['api', String(url)]);
        const parsed = new URL(String(url));
        if (parsed.pathname === '/api/completed-folders') {
            return {
                data: [{
                    folder_path: '00000000/004/0011',
                    folder_name: '0011',
                    approved_count: 2,
                    input_names: ['nhan-vien'],
                }],
            };
        }
        return {
            data: [],
            pagination: { page: 1, page_size: 20, total: 0, total_pages: 1, from: 0, to: 0 },
        };
    },
    escapeHTML: value => String(value),
    console,
    alert() {},
    confirm() { return true; },
};

vm.createContext(sandbox);
vm.runInContext(
    fs.readFileSync('frontend/js/admin_panel.js', 'utf8'),
    sandbox,
    { filename: 'frontend/js/admin_panel.js' },
);

(async () => {
    await vm.runInContext('fetchCompletedSubmissions()', sandbox);
    assert.deepEqual(calls[0], ['populate', 'filterTemplateId', true]);
    assert.equal(filterTemplateId.options.length, 2);
    assert.equal(new URL(calls[1][1]).pathname, '/api/completed-folders');
    assert.equal(completedFolderTree.children.length, 3);
    assert(completedFolderTree.children.some(
        child => child.dataset.folderPath === '00000000/004/0011'
    ));
    const firstUrl = new URL(calls[2][1]);
    assert.equal(firstUrl.pathname, '/api/submissions');
    assert.equal(firstUrl.searchParams.get('folder_path'), '00000000/004/0011');
    assert.equal(firstUrl.searchParams.get('page'), '1');
    assert.equal(firstUrl.searchParams.get('page_size'), '20');

    await vm.runInContext('fetchCompletedSubmissions(2)', sandbox);
    const secondUrl = new URL(calls[3][1]);
    assert.equal(secondUrl.searchParams.get('page'), '2');
    assert.equal(secondUrl.searchParams.get('page_size'), '20');

    const authSource = fs.readFileSync('frontend/auth.js', 'utf8');
    assert(authSource.includes('formatApiErrorDetail(data.detail || data.message)'));
    assert(authSource.includes('folder_path: folderPath'));
    assert(authSource.includes('start_date'));
    assert(authSource.includes('end_date'));
    console.log('Admin completed export self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
