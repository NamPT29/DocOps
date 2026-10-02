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

console.log('Project workflow self-check passed.');
