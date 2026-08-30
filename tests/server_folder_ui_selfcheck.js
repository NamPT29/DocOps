const assert = require('assert');
const fs = require('fs');

const html = fs.readFileSync('frontend/admin.html', 'utf8');
const source = fs.readFileSync('frontend/js/admin_operations.js', 'utf8');

assert.ok(!html.includes('id="serverSourcePath"'));
assert.ok(!html.includes('id="assignmentFolderLevel"'));
assert.ok(html.includes('id="projectFolderPicker"'));
assert.ok(html.includes('webkitdirectory'));
assert.ok(source.includes('/api/documents/server-folders'));
assert.ok(source.includes('/api/documents/server-folder/scan'));
assert.ok(source.includes('/api/documents/server-folder/import'));
assert.ok(source.includes('/api/documents/server-folder/jobs/'));
assert.ok(!source.includes('/api/documents/upload-folder-file'));
assert.ok(html.includes('id="projectInputUsers"'));
assert.ok(html.includes('id="projectReviewerUsers"'));
assert.ok(source.includes('input_user_ids: inputUserIds'));
assert.ok(source.includes('reviewer_user_ids: reviewerUserIds'));
assert.ok(source.includes('đã có (chia lại nếu đang chờ)'));

console.log('Server folder UI self-check: OK');
