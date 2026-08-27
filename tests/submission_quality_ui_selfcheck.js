const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'frontend', 'index.html'), 'utf8');
const script = fs.readFileSync(path.join(root, 'frontend', 'js', 'admin_panel.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'frontend', 'index-page.css'), 'utf8');

function assert(condition, message) {
    if (!condition) throw new Error(message);
}

assert(html.includes('id="filterSubmissionQuality"'), 'Missing submission quality filter.');
assert(html.includes('<option value="all">Tất cả hồ sơ</option>'), 'Missing all-submissions choice.');
assert(html.includes('<option value="changed">Có trường bị sửa</option>'), 'Missing changed-fields choice.');
assert(
    html.includes('id="filterSubmissionQuality"') && html.includes('data-action="fetchSubmissions"'),
    'Quality filter must use the delegated CSP-safe change action.',
);
assert(!/id="filterSubmissionQuality"[^>]+onchange=/i.test(html), 'Quality filter uses an inline handler.');

assert(script.includes("quality.has_review_changes === true"), 'Changed quality metadata is not consumed.');
assert(script.includes("submission?.quality?.is_error_report === true"), 'Error-report metadata is not consumed.');
assert(script.includes("filterValue === 'changed'"), 'Changed-fields filter is not applied.');
assert(script.includes("row.classList.add('submission-quality-changed')"), 'Missing yellow row class.');
assert(script.includes("row.classList.add('submission-quality-error')"), 'Missing red row class.');
assert(
    !/searchParams\.(?:set|append)\(['"](?:quality|quality_filter|has_review_changes|is_error_report)/.test(script),
    'Frontend must not invent a server-side quality filter parameter.',
);

assert(css.includes('tr.submission-quality-changed > *'), 'Missing changed-row CSS.');
assert(css.includes('background-color: #fff3cd'), 'Changed rows are not yellow.');
assert(css.includes('tr.submission-quality-error > *'), 'Missing error-row CSS.');
assert(css.includes('background-color: #f8d7da'), 'Error reports are not red.');

const helperStart = script.indexOf('function hasSubmissionQualityChanges');
const helperEnd = script.indexOf('async function fetchSubmissions', helperStart);
assert(helperStart >= 0 && helperEnd > helperStart, 'Could not isolate quality helpers.');
const sandbox = {};
vm.runInNewContext(script.slice(helperStart, helperEnd), sandbox);

const changed = {quality: {has_review_changes: true, changed_field_count: 1, is_error_report: false}};
const error = {quality: {has_review_changes: false, changed_field_count: 0, is_error_report: true}};
const clean = {quality: {has_review_changes: false, changed_field_count: 0, is_error_report: false}};
assert(sandbox.filterSubmissionsByQuality([changed, error, clean], 'changed').length === 2,
    'Changed filter must keep both yellow and red quality rows.');
assert(sandbox.filterSubmissionsByQuality([changed, error, clean], 'all').length === 3,
    'All filter must preserve every row.');

function qualityClasses(submission) {
    const classes = [];
    sandbox.applySubmissionQualityRowClass({classList: {add: value => classes.push(value)}}, submission);
    return classes;
}
assert(qualityClasses(changed)[0] === 'submission-quality-changed', 'Changed report is not yellow.');
assert(qualityClasses(error)[0] === 'submission-quality-error', 'Error report is not red.');
assert(qualityClasses(clean).length === 0, 'Clean report must not receive a quality row class.');

console.log('submission quality UI self-check passed');
