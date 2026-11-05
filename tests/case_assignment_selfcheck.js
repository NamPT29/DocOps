const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'frontend', 'admin.html'), 'utf8');
const workflowJs = fs.readFileSync(path.join(root, 'frontend', 'js', 'project_workflow.js'), 'utf8');
const managementJs = fs.readFileSync(path.join(root, 'frontend', 'js', 'project_management.js'), 'utf8');
const adminPageJs = fs.readFileSync(path.join(root, 'frontend', 'admin-page.js'), 'utf8');

// 1. admin.html markup checks
assert.match(html, /id="actionNeededCasesModal"/, 'admin.html must contain actionNeededCasesModal');
assert.match(html, /id="caseRevokeModal"/, 'admin.html must contain caseRevokeModal');
assert.match(html, /id="workflow-ready-input-tab"/, 'admin.html must contain workflow-ready-input-tab');
assert.match(html, /id="workflow-ready-input-pane"/, 'admin.html must contain workflow-ready-input-pane');
assert.match(html, /id="actionNeededCasesBtn"/, 'admin.html must contain actionNeededCasesBtn');

// 2. CSP checks
assert.doesNotMatch(workflowJs, /innerHTML|insertAdjacentHTML|document\.write/, 'project_workflow.js must use textContent only');
assert.match(html, /data-admin-action="open-action-needed-cases"/, 'Button must use data-admin-action="open-action-needed-cases"');
assert.match(html, /data-admin-action="submit-case-revoke"/, 'Revoke submit must use data-admin-action="submit-case-revoke"');
assert.match(adminPageJs, /'open-action-needed-cases':/, 'admin-page.js must register open-action-needed-cases');
assert.match(adminPageJs, /'submit-case-revoke':/, 'admin-page.js must register submit-case-revoke');

// 3. API endpoint integration
assert.match(managementJs, /\/api\/projects\/action-needed-cases/, 'project_management.js must query action-needed-cases');
assert.match(managementJs, /\/cases\/\$\{activeCaseRevokeItem\.case_id\}\/revoke-input/, 'project_management.js must call revoke-input endpoint');
assert.match(workflowJs, /\/ready-input-cases/, 'project_workflow.js must query ready-input-cases');
assert.match(workflowJs, /\/cases\/\$\{caseItem\.case_id\}\/assign-input/, 'project_workflow.js must call assign-input with case_id (API ready-input-cases trả case_id)');

// 4. BR-04: Reviewer cannot be assigned as data entry input user
assert.match(workflowJs, /caseItem\.assigned_reviewer_user_id && u\.id === caseItem\.assigned_reviewer_user_id/, 'project_workflow.js must filter reviewer from input candidate options (BR-04)');

// 5. R9: Timezone formatting with Asia/Ho_Chi_Minh and ?v= bumps
assert.match(managementJs, /timeZone:\s*'Asia\/Ho_Chi_Minh'/, 'project_management.js must format with Asia/Ho_Chi_Minh');
assert.doesNotMatch(managementJs, /due_at\.substring\(0,\s*16\)/, 'due_at must not use UTC substring');
assert.doesNotMatch(managementJs, /assigned_at\.substring\(0,\s*16\)/, 'assigned_at must not use UTC substring');
assert.match(html, /project_management\.js\?v=2\.24/, 'admin.html must load project_management.js?v=2.24');
assert.match(html, /project_workflow\.js\?v=[\d.]+/, 'admin.html must load project_workflow.js with a ?v= version');

// 6. Fix infinite recursion in formatVietnamDateTime and verify actual timezone output
const vm = require('node:vm');
const ctx = vm.createContext({});
ctx.window = ctx; // Simulate browser global scope
ctx.document = { 
    getElementById: () => null, 
    querySelectorAll: () => [], 
    createElement: () => ({ classList: {}, appendChild: () => {}, setAttribute: () => {}, style: {} }) 
};
ctx.console = console;
ctx.Intl = Intl; // Expose Intl for DateTimeFormat

// Try running both scripts sequentially. Should not throw recursion error.
vm.runInContext(managementJs, ctx);
vm.runInContext(workflowJs, ctx);

// Verify actual timezone formatting matches Vietnam time UTC+7
const tzResult = vm.runInContext('formatVietnamDateTime("2026-10-14T08:30:00Z")', ctx);
assert.strictEqual(tzResult, '2026-10-14 15:30', 'formatVietnamDateTime must convert UTC to VN time correctly (15:30)');

// 7. Tab "Hộp chờ giao nhập" chạy thật với dữ liệu đúng dạng API ready-input-cases:
//    cột Số PDF lấy pdf_count, nút Giao hộp gọi assign-input bằng case_id.
function withTimeout(promise, message, ms = 1500) {
    let timer;
    const guard = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), ms); });
    return Promise.race([promise, guard]).finally(() => clearTimeout(timer));
}

function fakeElement(tag) {
    return {
        tagName: String(tag).toUpperCase(),
        className: '',
        textContent: '',
        value: '',
        disabled: false,
        children: [],
        listeners: {},
        appendChild(child) { this.children.push(child); return child; },
        replaceChildren(...items) { this.children = items; },
        addEventListener(type, handler) { this.listeners[type] = handler; },
    };
}

function findAll(node, predicate, out = []) {
    if (predicate(node)) out.push(node);
    (node.children || []).forEach(child => findAll(child, predicate, out));
    return out;
}

(async () => {
    const body = fakeElement('tbody');
    const summary = fakeElement('div');
    const calls = [];
    const alerts = [];
    const uiCtx = vm.createContext({
        console,
        Intl,
        setTimeout,
        clearTimeout,
        alert: message => alerts.push(message),
        document: {
            getElementById: id => ({ workflowReadyInputBody: body, workflowReadyInputSummary: summary }[id] || null),
            querySelectorAll: () => [],
            createElement: fakeElement,
        },
    });
    uiCtx.window = uiCtx;
    vm.runInContext(workflowJs, uiCtx);
    uiCtx.apiCall = async (url, options) => { calls.push({ url, options }); return { status: 'ok' }; };
    uiCtx.refreshProjectWorkflow = async () => true;
    uiCtx.projectWorkflowProjectId = 1;

    uiCtx.renderWorkflowReadyInput({
        previous_stage_label: 'Check scan',
        cases: [{ case_id: 7, case_key: '0001', display_name: 'Hộp 0001', pdf_count: 6, assigned_reviewer_user_id: 3 }],
        eligible_users: [
            { id: 3, username: 'hc2', full_name: 'Người kiểm', account_type: 'staff' },
            { id: 4, username: 'ctv1', full_name: 'Người nhập', account_type: 'ctv' },
        ],
    });

    const row = body.children[0];
    assert.ok(row, 'Phải có một dòng hộp chờ giao');
    const cells = row.children;
    assert.strictEqual(cells[2].textContent, '6', 'Cột Số PDF phải hiện pdf_count từ API (6), không phải 0');
    const select = findAll(row, node => node.tagName === 'SELECT')[0];
    const optionValues = select.children.map(option => option.value);
    assert.deepStrictEqual(optionValues, ['', '4'], 'Danh sách người nhập bỏ người kiểm tra của hộp (BR-04)');
    const button = findAll(row, node => node.tagName === 'BUTTON' && node.textContent === 'Giao hộp')[0];
    assert.ok(button && button.listeners.click, 'Phải có nút Giao hộp');

    // Chưa chọn người: không gọi API.
    await withTimeout(button.listeners.click(), 'Giao hộp khi chưa chọn người bị treo');
    assert.strictEqual(calls.length, 0, 'Chưa chọn người nhập thì không gọi API');
    assert.deepStrictEqual(alerts, ['Vui lòng chọn người nhập liệu.']);

    // Chọn ctv1 rồi giao: gọi đúng endpoint bằng case_id.
    select.value = '4';
    await withTimeout(button.listeners.click(), 'Giao hộp bị treo');
    assert.strictEqual(calls.length, 1, 'Giao hộp phải gọi API đúng một lần');
    assert.strictEqual(calls[0].url, '/api/projects/1/cases/7/assign-input', 'URL giao hộp phải dùng case_id');
    assert.strictEqual(calls[0].options.method, 'POST');
    assert.deepStrictEqual(JSON.parse(calls[0].options.body), { user_id: 4 });
    assert.strictEqual(button.disabled, false, 'Nút được bật lại sau khi giao');

    console.log('Case assignment self-check passed.');
})().catch(error => {
    console.error(error);
    process.exit(1);
});
