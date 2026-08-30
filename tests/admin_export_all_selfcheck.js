const assert = require('node:assert/strict');
const fs = require('node:fs');

const adminHtml = fs.readFileSync('frontend/admin.html', 'utf8');
const projectSource = fs.readFileSync('frontend/js/project_management.js', 'utf8');

assert(!adminHtml.includes('onclick="exportExcelByTemplate()"'));
assert(!adminHtml.includes('onclick="exportExcelByTemplate(true)"'));
assert(projectSource.includes("'Chỉ xuất hồ sơ đã kiểm duyệt'"));
assert(projectSource.includes("'Xuất toàn bộ'"));
assert(projectSource.includes('async function exportProjectReports(projectId, includePendingReview)'));
assert(projectSource.includes("params.set('include_pending_review', 'true')"));
assert(projectSource.includes('/api/projects/${project.id}/export-jobs?'));
assert(adminHtml.includes('auth.js?v=100.02'));

console.log('Admin export all self-check: OK');
