const assert = require('node:assert/strict');
const fs = require('node:fs');

const adminHtml = fs.readFileSync('frontend/admin.html', 'utf8');
const authSource = fs.readFileSync('frontend/auth.js', 'utf8');

assert(adminHtml.includes('onclick="exportExcelByTemplate()"'));
assert(adminHtml.includes('> Xuất đã duyệt</button>'));
assert(adminHtml.includes('onclick="exportExcelByTemplate(true)"'));
assert(adminHtml.includes('> Xuất toàn bộ</button>'));
assert(authSource.includes('async function exportExcelByTemplate(includePendingReview = false)'));
assert(authSource.includes("params.set('include_pending_review', 'true')"));
assert(authSource.includes('} else {'));
assert(adminHtml.includes('auth.js?v=100.01'));

console.log('Admin export all self-check: OK');
