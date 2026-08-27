const assert = require('node:assert/strict');
const fs = require('node:fs');

const source = fs.readFileSync('frontend/js/admin_panel.js', 'utf8');
const html = fs.readFileSync('frontend/index.html', 'utf8');

assert(source.includes('/api/review-next-submission?'));
assert(source.includes('function goToNextReviewSubmission()'));
assert(source.includes('button.dataset.nextId'));
assert(html.includes('id="reviewNextButton"'));
assert(html.includes('data-action="goToNextReviewSubmission"'));
console.log('Review next self-check: OK');
