const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(
    path.join(__dirname, '..', 'frontend', 'js', 'admin_panel.js'),
    'utf8',
);

assert(
    !source.includes("else if (isReviewTab && sub.status === 'pending_review')"),
    'Reviewer queue must not render a delete action for employee submissions',
);
assert(
    source.includes('currentUser.role === \'admin\''),
    'Admin review actions must remain available',
);

console.log('Submission RBAC self-check: OK');
