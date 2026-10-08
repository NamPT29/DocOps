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
assert.match(workflowJs, /\/cases\/\$\{caseItem\.id\}\/assign-input/, 'project_workflow.js must call assign-input endpoint');

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

console.log('Case assignment self-check passed.');
