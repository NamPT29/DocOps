const assert = require('node:assert/strict');
const fs = require('node:fs');

const html = fs.readFileSync('frontend/admin.html', 'utf8');
const source = fs.readFileSync('frontend/js/project_management.js', 'utf8');
const app = fs.readFileSync('frontend/app.js', 'utf8');
const adminPanel = fs.readFileSync('frontend/js/admin_panel.js', 'utf8');

assert(!html.includes('id="review-tab"'));
assert(!html.includes('id="review-pane"'));
assert(!html.includes('id="data-tab"'));
assert(!html.includes('id="data-pane"'));
assert(!html.includes('id="inventory-tab"'));
assert(!html.includes('id="inventory-pane"'));
assert(!html.includes('id="assignment-tab"'));
assert(!html.includes('id="assignment-pane"'));
assert(html.includes('phân nhân sự trong <strong>Quản lý Dự án</strong>'));
assert(html.includes('id="projectReportsModal"'));
assert(html.includes('id="projectReportsFolderTree"'));
assert(html.includes('id="projectExportStatus"'));
assert(source.includes("openProjectReports(project.id, 'review')"));
assert(source.includes("openProjectReports(project.id, 'completed')"));
assert(source.includes("'Xuất bản'"));
assert(source.includes("'Chỉ xuất hồ sơ đã kiểm duyệt'"));
assert(source.includes("'Xuất toàn bộ'"));
assert(source.includes("'Cập nhật tài liệu'"));
assert(source.includes("'Quản lý / xóa PDF'"));
assert(source.includes("'Hồ sơ hoàn chỉnh'"));
assert(!source.includes("Hồ sơ / Xuất"));
assert(source.includes('/submission-folders?${params.toString()}'));
assert(source.includes('/submissions?${params.toString()}'));
assert(source.includes('/export-jobs?${params.toString()}'));
assert(source.includes("folders.sort((left, right)"));
assert(source.includes("url.hash = 'projects'"));
assert(app.includes("returnTarget === 'project_review' || returnTarget === 'project_completed'"));
assert(adminPanel.includes("params.set('project_id', navigation.projectId)"));
assert(adminPanel.includes("params.set('return_project', navigation.projectId)"));

console.log('project reporting self-check passed');
