const assert = require('node:assert/strict');
const fs = require('node:fs');

const html = fs.readFileSync('frontend/admin.html', 'utf8');
const source = fs.readFileSync('frontend/js/admin_panel.js', 'utf8');

assert(html.includes('id="assignedFoldersModal"'));
assert(html.includes('id="assignedFoldersList"'));
assert(html.includes('js/admin_panel.js?v=200.02'));
assert(source.includes('Tài liệu đã giao'));
assert(source.includes('/api/documents/assignments/folders?user_id='));
assert(source.includes('folder_path: folderPath'));
assert(source.includes("button.textContent = folder.can_revoke ? 'Thu hồi' : 'Đã có hồ sơ'"));
assert(!source.includes("revokeAssignments(${safeUserId}, 'input')"));

console.log('Admin folder revocation self-check: OK');
