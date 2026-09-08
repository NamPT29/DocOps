const assert = require('node:assert/strict');
const fs = require('node:fs');

const source = fs.readFileSync('frontend/js/admin_panel.js', 'utf8');
const submissionSource = fs.readFileSync('frontend/js/submission.js', 'utf8');
const projectSource = fs.readFileSync('frontend/js/project_management.js', 'utf8');

assert(!source.includes('Admin vẫn có thể mở để theo dõi'));
assert.match(source, /if \(payload\.viewer_is_current_user !== true\) \{[\s\S]*?return false;/);

const editStart = source.indexOf('async function editSubmission');
const editEnd = source.indexOf('\nasync function deleteSubmission', editStart);
const editSource = source.slice(editStart, editEnd);
assert(editStart >= 0 && editEnd > editStart);
assert(
    editSource.indexOf('await startSubmissionView(id)') < editSource.indexOf('apiCall(`/api/submissions/${id}`)'),
    'Phải giành khóa trước khi tải nội dung hồ sơ',
);
assert.match(editSource, /if \(!res\) \{\s*stopSubmissionView\(\);/);

assert(source.includes('Chưa phân người kiểm'));
assert.match(source, /if \(sub\.status === 'completed'\) \{[\s\S]*?reopen-submission/);
assert(!source.includes("['pending_input_confirmation', 'completed'].includes(sub.status)"));

assert(source.includes("result['X-Submission-Lease-Token'] = activeSubmissionLeaseToken"));
assert(source.includes('activeSubmissionLeaseToken = payload.lease_token'));
assert(!source.includes('Máy chủ không trả về mã khóa hồ sơ'));
assert(source.includes('Rolling-deploy compatibility'));
assert.match(source, /confirm-review[\s\S]*?headers: submissionLeaseHeaders/);
assert.match(submissionSource, /confirm-review[\s\S]*?submissionLeaseHeaders/);
assert.match(submissionSource, /input-confirmation[\s\S]*?submissionLeaseHeaders/);
assert.match(projectSource, /toggle_check[\s\S]*?withSubmissionViewLease/);

console.log('Review workflow frontend policy self-check: OK');
