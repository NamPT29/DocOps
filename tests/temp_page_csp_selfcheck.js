const assert = require('assert');
const fs = require('fs');
const path = require('path');

const projectRoot = path.resolve(__dirname, '..');
const frontendRoot = path.join(projectRoot, 'frontend');
const html = fs.readFileSync(path.join(frontendRoot, 'temp.html'), 'utf8');
const actions = fs.readFileSync(path.join(frontendRoot, 'temp-actions.js'), 'utf8');

assert.doesNotMatch(html, /<script\b(?![^>]*\bsrc\s*=)[^>]*>/i, 'Temp page must not contain inline scripts.');
assert.doesNotMatch(html, /\bon[a-z]+\s*=/i, 'Temp page must not contain inline event handlers.');
assert.doesNotMatch(html, /<style\b/i, 'Temp page must not contain style blocks.');
assert.doesNotMatch(html, /\bstyle\s*=/i, 'Temp page must not contain style attributes.');

for (const asset of ['temp-page.css', 'temp-index.js', 'temp-admin.js', 'temp-login.js', 'temp-actions.js']) {
    assert(html.includes(asset), `Temp page must reference ${asset}.`);
    assert(fs.existsSync(path.join(frontendRoot, asset)), `Referenced temp asset must exist: ${asset}.`);
}

const actionAttributes = [...html.matchAll(/data-temp-(?:click|change|dblclick|keyup)="([^"]+)"/g)];
assert.equal(actionAttributes.length, 64, 'All 64 former inline handlers must remain wired as delegated actions.');

const allowlistedActions = new Set([...actions.matchAll(/^\s*'([^']+)'\s*:/gm)].map(match => match[1]));
for (const [, actionName] of actionAttributes) {
    assert(allowlistedActions.has(actionName), `Delegated temp action must be allowlisted: ${actionName}.`);
}

for (const preservedCall of [
    "openQueueFolder(null)",
    "submitData('draft')",
    "submitData('pending_review')",
    "loadServerSourceFolders('')",
    'fetchDocumentStats()',
    'fetchReviewerReassignmentData()',
    'loadServerSourceFolders()',
]) {
    assert(actions.includes(preservedCall), `Delegated action must preserve call and arguments: ${preservedCall}.`);
}

console.log('Temp page CSP self-check passed.');
