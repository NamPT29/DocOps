const assert = require('assert');
const fs = require('fs');

const html = fs.readFileSync('frontend/admin.html', 'utf8');
const uploadSource = fs.readFileSync('frontend/js/project_upload.js', 'utf8');
const source = fs.readFileSync('frontend/js/project_management.js', 'utf8');

assert(html.includes('id="projects-tab"'));
assert(html.includes('id="projectFolderPicker"'));
assert(html.includes('webkitdirectory'));
assert(html.includes('js/project_upload.js'));
assert(html.includes('js/project_management.js'));

// Upload engine checks
assert(uploadSource.includes("crypto.subtle.digest('SHA-256'"));
assert(uploadSource.includes("'X-Upload-Offset': String(offset)"));
assert(uploadSource.includes("response.headers.get('Retry-After')"));
assert(uploadSource.includes('response.status === 429'));
assert(uploadSource.includes('Promise.all(Array.from({length: workerCount}'));
assert(uploadSource.includes('projectUploadResumeV1'));
assert(uploadSource.includes('/api/project-upload-sessions/${encodeURIComponent(session.id)}/finalize'));
assert(uploadSource.includes('Number(resume.project_id) !== targetProjectId'));

// Core project management checks
assert(html.includes('id="projectMembersModal"'));
assert(!html.includes('id="rebalanceProjectMembersButton"'));
assert(html.includes('id="projectAssetsModal"'));
assert(source.includes('/api/projects/${projectId}/members'));
assert(!source.includes('rebalance_work'));
assert(source.includes('formatProjectMemberDistribution(result.input_distribution)'));
assert(source.includes('project.member_report_stats'));
assert(source.includes('`Lỗi ${Number(stats.error_reports || 0)}`'));
assert(source.includes('`Chờ duyệt ${Number(stats.pending_review_reports || 0)}`'));
assert(source.includes('`Tổng ${Number(stats.total_reports || 0)}`'));
assert(source.includes('Đã lưu và phân chia lại'));
assert(source.includes("'Thêm / cập nhật PDF'"));
assert(source.includes("'Quản lý / xóa PDF'"));
assert(source.includes("'Kiểm duyệt'"));
assert(source.includes("'Hồ sơ hoàn chỉnh'"));
assert(source.includes("'Chỉ xuất hồ sơ đã kiểm duyệt'"));
assert(source.includes("'Xuất toàn bộ'"));
assert(source.includes('/api/projects/${project.id}/assets'));
assert(source.includes('deleteButton.disabled = Number(asset.submission_count || 0) > 0'));
assert(source.includes('method: \'DELETE\''));
assert(html.includes('id="projectUpdateTargetBanner"'));
assert(source.includes('prepareProjectFolderUpdate(project.id)'));
assert(source.includes("'Xóa dự án'"));
assert(source.includes('async function deleteProject(project)'));
assert(source.includes('/api/projects/${Number(project.id)}'));
assert(source.includes("method: 'DELETE'"));
assert(source.includes('Nhập chính xác tên dự án để xác nhận'));
assert(source.includes('Toàn bộ folder, PDF, báo cáo đã lưu, phân công và công việc kiểm duyệt'));
assert(html.includes('Hệ thống chỉ tải PDF mới hoặc có nội dung thay đổi.'));

console.log('project management self-check passed');
