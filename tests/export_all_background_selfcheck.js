const assert = require('node:assert/strict');
const fs = require('node:fs');

const html = fs.readFileSync('frontend/admin.html', 'utf8');
const source = fs.readFileSync('frontend/auth.js', 'utf8');

assert(html.includes('id="exportAllBtn"'));
assert(html.includes('id="exportAllStatus"'));
assert(html.includes('auth.js?v=100.01'));
assert(source.includes("authFetch(`/api/export-jobs?${params.toString()}`"));
assert(source.includes("authFetch(`/api/export-jobs/${jobId}`"));
assert(source.includes("authFetch(`/api/export-jobs/${jobId}/download`"));
assert(source.includes("params.set('include_pending_review', 'true');"));
assert(source.includes('return exportAllReportsAsJob(params, tid);'));
assert(source.includes('button.disabled = true'));
assert(source.includes('button.disabled = false'));

console.log('Export-all background UI self-check: OK');
