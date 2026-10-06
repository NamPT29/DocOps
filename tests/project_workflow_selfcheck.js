const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'frontend', 'js', 'project_workflow.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'frontend', 'admin.html'), 'utf8');
const management = fs.readFileSync(path.join(root, 'frontend', 'js', 'project_management.js'), 'utf8');

// Server-provided names (case folders, usernames) must never be written as HTML.
assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML|document\.write/, 'Workflow panel must render with textContent only.');
assert.match(html, /src="js\/project_workflow\.js\?v=[\d.]+"/, 'admin.html must load the workflow panel script.');
assert.match(html, /id="projectWorkflowModal"/);
assert.match(management, /openProjectWorkflow\(project\.id\)/, 'Project actions must expose the workflow panel.');
// BA 3.3: stage member pickers follow each stage's allowed roles (admins included).
assert.match(source, /stage\.allowed_roles/, 'Member pickers must respect stage.allowed_roles.');

const sandbox = { projectManagementUsers: [], projectManagementProjects: [], console };
vm.createContext(sandbox);
vm.runInContext(`${source}\nthis.__api = { workflowCellActions, workflowEnabledKeys };`, sandbox);
const { workflowCellActions } = sandbox.__api;

const work = { kind: 'work', derived: false };
const qc = { kind: 'qc', derived: false };
const derived = { kind: 'work', derived: true };
const labels = (stage, cell) => Array.from(workflowCellActions({}, stage, cell), ([action]) => action);

assert.deepEqual(labels(work, { status: 'pending', available: true }), ['start']);
assert.deepEqual(labels(work, { status: 'pending', available: false }), [], 'Blocked stages offer no action.');
assert.deepEqual(labels(work, { status: 'rejected', available: true }), ['start']);
assert.deepEqual(labels(work, { status: 'in_progress', available: true }), ['complete']);
assert.deepEqual(labels(qc, { status: 'in_progress', available: true }), ['complete', 'reject']);
assert.deepEqual(labels(work, { status: 'done', available: true }), ['reopen']);
assert.deepEqual(labels(derived, { status: 'pending', available: true }), [], 'Derived stages are never moved by hand.');

// Test workflowTransition 409 flow
let fetches = [];
let alerts = [];
let prompts = [];
let refreshed = false;

sandbox.authFetch = async (url, options) => {
    fetches.push({ url, options });
    const action = JSON.parse(options.body).action;
    const reason = JSON.parse(options.body).reason;
    if (action === 'complete' && sandbox._mockCode) {
        return { ok: false, status: 409, json: async () => ({ detail: { code: sandbox._mockCode, message: 'Mock message' } }) };
    }
    return { ok: true, status: 200, json: async () => ({ status: 'ok' }) };
};
sandbox.alert = msg => alerts.push(msg);
sandbox.window = { prompt: msg => { prompts.push(msg); return sandbox._mockPromptResult; } };
sandbox.refreshProjectWorkflow = async () => { refreshed = true; };
sandbox.workflowApiBase = () => '/api';
sandbox.encodeURIComponent = encodeURIComponent;

vm.runInContext('this.__testTransition = async (caseId, stageKey, action) => await workflowTransition(caseId, stageKey, action);', sandbox);

(async () => {
    // 1. scan_processing -> no prompt
    sandbox._mockCode = 'scan_processing';
    await sandbox.__testTransition(1, 'scan_qc', 'complete');
    assert.deepEqual(prompts, []);
    assert.deepEqual(alerts, ['Mock message']);
    
    // 2. scan_catalog_mismatch -> no prompt
    fetches = []; alerts = []; prompts = [];
    sandbox._mockCode = 'scan_catalog_mismatch';
    await sandbox.__testTransition(1, 'scan_qc', 'complete');
    assert.deepEqual(prompts, []);
    assert.deepEqual(alerts, ['Mock message']);
    
    // 3. reason_required -> prompt -> sends reason
    fetches = []; alerts = []; prompts = [];
    sandbox._mockCode = 'reason_required';
    sandbox._mockPromptResult = '  My Reason  '; // trimmed -> 'My Reason'
    
    // override authFetch to return OK on the second call
    sandbox.authFetch = async (url, options) => {
        fetches.push({ url, options });
        const reason = JSON.parse(options.body).reason;
        if (reason === 'My Reason') return { ok: true, status: 200, json: async () => ({ status: 'ok' }) };
        return { ok: false, status: 409, json: async () => ({ detail: { code: sandbox._mockCode, message: 'Mock message' } }) };
    };
    
    await sandbox.__testTransition(1, 'scan_qc', 'complete');
    assert.equal(prompts.length, 1);
    assert.equal(fetches.length, 2);
    assert.equal(JSON.parse(fetches[1].options.body).reason, 'My Reason');
    assert.equal(refreshed, true);
    
    console.log('Project workflow self-check passed.');
})().catch(e => { console.error(e); process.exitCode = 1; });
