const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const adminPanelSource = fs.readFileSync('frontend/js/admin_panel.js', 'utf8');
const appSource = fs.readFileSync('frontend/app.js', 'utf8');
const adminHtml = fs.readFileSync('frontend/admin.html', 'utf8');
const adminPageSource = fs.readFileSync('frontend/admin-page.js', 'utf8');

const reviewTableBody = {
    innerHTML: '',
    children: [],
    appendChild(child) { this.children.push(child); },
};
const adminPanelSandbox = {
    URL,
    currentUser: { id: 1, role: 'admin' },
    window: { location: { origin: 'http://localhost', pathname: '/admin.html' } },
    document: {
        getElementById(id) {
            if (id === 'reviewTableBody') return reviewTableBody;
            return null;
        },
        createElement() {
            return {
                innerHTML: '',
                classList: { add() {} },
            };
        },
    },
    escapeHTML: value => String(value),
    console,
    alert() {},
    confirm() { return true; },
};

vm.createContext(adminPanelSandbox);
vm.runInContext(adminPanelSource, adminPanelSandbox, { filename: 'frontend/js/admin_panel.js' });
vm.runInContext("activeReviewFolderPath = '00000000/004/0011';", adminPanelSandbox);

const submission = {
    id: 103,
    created_at: '2026-08-14 08:00:00',
    creator_name: 'nhan-vien-1',
    template: 'mau-1',
    pdf_relative_path: '00000000/004/0011/0000130.pdf',
    status: 'pending_review',
};

adminPanelSandbox.renderAdminSubmissionsTable([submission], 'reviewTableBody', true);
assert.equal(reviewTableBody.children.length, 1);
assert(reviewTableBody.children[0].innerHTML.includes(
    'index.html?check_id=103&return_to=review&return_folder=00000000%2F004%2F0011',
));

const backToAdminBtn = {
    href: '',
    innerHTML: '',
    classList: { add() {}, remove() {} },
};
const genericClassList = { add() {}, remove() {} };
const appSandbox = {
    URLSearchParams,
    currentUser: { id: 1, role: 'admin' },
    window: {
        location: {
            search: '?check_id=103&return_to=project_review&return_project=7&return_folder=00000000%2F004%2F0011',
        },
    },
    document: {
        getElementById(id) {
            if (id === 'form-container') return {};
            if (id === 'backToAdminBtn') return backToAdminBtn;
            if (id === 'employeeTabs' || id === 'fileSidebar') return { classList: genericClassList };
            if (id === 'pdfViewerCol') return { classList: genericClassList };
            if (id === 'templateSelectContainer') {
                return { style: { setProperty() {} } };
            }
            return null;
        },
    },
    fetchSchema() {},
    setupPdfUpload() {},
    restoreQueue() {},
    editSubmission() {},
    setTimeout(callback) { callback(); },
    console,
};

vm.createContext(appSandbox);
vm.runInContext(appSource, appSandbox, { filename: 'frontend/app.js' });
appSandbox.initApp();
assert.equal(
    backToAdminBtn.href,
    '/admin.html?project_id=7&project_view=review&return_folder=00000000%2F004%2F0011#projects',
);
assert(backToAdminBtn.innerHTML.includes('Về kiểm duyệt hồ sơ dự án'));

assert(adminPageSource.includes("window.location.hash === '#projects'"));
assert(adminPageSource.includes('restoreProjectManagementNavigation()'));
assert(!adminHtml.includes('id="review-tab"'));

console.log('Review return navigation self-check: OK');
