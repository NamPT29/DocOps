const assert = require('assert');
const fs = require('fs');

const html = fs.readFileSync('frontend/admin.html', 'utf8');
const source = fs.readFileSync('frontend/js/project_management.js', 'utf8');

assert(html.includes('id="projects-tab"'));
assert(html.includes('id="projectFolderPicker"'));
assert(html.includes('webkitdirectory'));
assert(html.includes('js/project_management.js'));
assert(source.includes("crypto.subtle.digest('SHA-256'"));
assert(source.includes("'X-Upload-Offset': String(offset)"));
assert(source.includes('Promise.all(Array.from({length: workerCount}'));
assert(source.includes('projectUploadResumeV1'));
assert(source.includes('/api/project-upload-sessions/${encodeURIComponent(session.id)}/finalize'));
assert(html.includes('id="projectMembersModal"'));
assert(html.includes('id="projectAssetsModal"'));
assert(source.includes('/api/projects/${projectId}/members'));
assert(source.includes('/api/projects/${project.id}/assets'));
assert(source.includes('deleteButton.disabled = Number(asset.submission_count || 0) > 0'));
assert(source.includes('method: \'DELETE\''));
assert(html.includes('id="projectUpdateTargetBanner"'));
assert(source.includes('prepareProjectFolderUpdate(project.id)'));
assert(source.includes('Number(resume.project_id) !== targetProjectId'));
assert(html.includes('Hệ thống chỉ tải PDF mới hoặc có nội dung thay đổi.'));

console.log('project management self-check passed');
