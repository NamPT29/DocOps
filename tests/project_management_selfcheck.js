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

console.log('project management self-check passed');
