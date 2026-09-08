const assert = require('node:assert/strict');
const fs = require('node:fs');

const html = fs.readFileSync('frontend/admin.html', 'utf8');
const source = fs.readFileSync('frontend/js/project_reports.js', 'utf8');
const normalizedSource = source.replace(/\r\n/g, '\n');

assert(!html.includes('id="exportAllBtn"'));
assert(html.includes('id="projectExportStatus"'));
assert(/src=["']auth\.js\?v=[^"']+["']/.test(html));
assert(normalizedSource.includes("authFetch(\n            `/api/projects/${project.id}/export-jobs?${params.toString()}`"));
assert(source.includes("authFetch(`/api/export-jobs/${jobId}`"));
assert(source.includes("authFetch(`/api/export-jobs/${jobId}/download`"));
assert(source.includes("params.set('include_pending_review', 'true')"));
assert(source.includes('buttons.forEach(button => { button.disabled = true; })'));
assert(source.includes('buttons.forEach(button => { button.disabled = false; })'));

console.log('Export-all background UI self-check: OK');
