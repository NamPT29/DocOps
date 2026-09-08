const assert = require('node:assert/strict');
const fs = require('node:fs');

const adminHtml = fs.readFileSync('frontend/admin.html', 'utf8');
const managementSource = fs.readFileSync('frontend/js/project_management.js', 'utf8');
const reportsSource = fs.readFileSync('frontend/js/project_reports.js', 'utf8');

assert(!adminHtml.includes('onclick="exportExcelByTemplate()"'));
assert(!adminHtml.includes('onclick="exportExcelByTemplate(true)"'));
assert(managementSource.includes("'Chỉ xuất hồ sơ đã kiểm duyệt'"));
assert(managementSource.includes("'Xuất toàn bộ'"));
assert(reportsSource.includes('async function exportProjectReports(projectId, includePendingReview)'));
assert(reportsSource.includes("params.set('include_pending_review', 'true')"));
assert(reportsSource.includes('/api/projects/${project.id}/export-jobs?'));
assert(/src=["']auth\.js\?v=[^"']+["']/.test(adminHtml));

console.log('Admin export all self-check: OK');
