const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function createClassList() {
    const values = new Set();
    return {
        add(...names) { names.forEach(name => values.add(name)); },
        toggle(name, force) {
            if (force) values.add(name);
            else values.delete(name);
        },
    };
}

const tableBody = {
    innerHTML: '',
    children: [],
    appendChild(child) { this.children.push(child); },
};

const submissions = [
    {
        id: 71,
        serial_number: 1,
        created_at: '2026-08-31 08:00:00',
        creator_name: 'nhan-vien',
        reviewer_name: 'nguoi-kiem',
        template: 'UBND',
        pdf_relative_path: '001/report-71.pdf',
        status: 'draft',
        quality: {},
    },
    {
        id: 72,
        serial_number: 2,
        created_at: '2026-08-31 08:01:00',
        creator_name: 'nhan-vien',
        reviewer_name: 'nguoi-kiem',
        template: 'UBND',
        pdf_relative_path: '001/report-72.pdf',
        status: 'pending_review',
        quality: {},
    },
];

const sandbox = {
    URL,
    currentUser: { id: 19, role: 'user' },
    window: {
        activeTemplateId: 1,
        location: { origin: 'http://localhost', pathname: '/index.html' },
    },
    document: {
        getElementById(id) {
            if (id === 'submissionsTableBody') return tableBody;
            return null;
        },
        querySelectorAll() { return []; },
        createElement() {
            return {
                innerHTML: '',
                classList: createClassList(),
            };
        },
    },
    async apiCall() {
        return {
            data: submissions,
            pagination: { page: 1, page_size: 20, total: 2, total_pages: 1, from: 1, to: 2 },
        };
    },
    escapeHTML: value => String(value ?? ''),
    console,
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/admin_panel.js', 'utf8'), sandbox, {
    filename: 'frontend/js/admin_panel.js',
});

(async () => {
    await sandbox.fetchSubmissions();

    assert.equal(tableBody.children.length, 2, 'Bảng hồ sơ đã nhập phải render dữ liệu API');
    assert(tableBody.children[0].innerHTML.includes('Lưu nháp'));
    assert(tableBody.children[1].innerHTML.includes('Chờ duyệt'));
    assert(!tableBody.children[1].innerHTML.includes('Lưu nháp'));

    console.log('Submission list render self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
