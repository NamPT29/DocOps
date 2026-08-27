const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('frontend/index.html', 'utf8');
const source = fs.readFileSync('frontend/index-page.js', 'utf8');

assert.equal((html.match(/<script\b(?![^>]*\bsrc\s*=)[^>]*>/gi) || []).length, 0);
assert.equal((html.match(/\bon[a-z]+\s*=/gi) || []).length, 0);
assert.equal((html.match(/<style\b/gi) || []).length, 0);
assert.equal((html.match(/\bstyle\s*=/gi) || []).length, 0);
assert.equal((html.match(/\bdata-action\s*=/gi) || []).length, 24);
assert(html.includes('href="index-page.css?v=1.00"'));
assert(html.includes('src="index-page.js?v=1.00"'));

const listeners = {};
const calls = [];
const sandbox = {
    URLSearchParams,
    localStorage: {
        getItem(key) {
            return key === 'token' ? 'valid-token' : JSON.stringify({ role: 'employee' });
        },
    },
    window: { location: { href: '', search: '' } },
    document: {
        readyState: 'loading',
        addEventListener(type, listener) {
            listeners[type] = listener;
        },
    },
    openQueueFolder(folderKey) {
        calls.push(['openQueueFolder', folderKey]);
    },
    confirmReviewSubmission(checkbox) {
        calls.push(['confirmReviewSubmission', checkbox]);
    },
    submitData(status) {
        calls.push(['submitData', status]);
    },
};

vm.runInNewContext(source, sandbox, { filename: 'index-page.js' });
assert.equal(typeof listeners.DOMContentLoaded, 'function');
listeners.DOMContentLoaded();
assert.equal(typeof listeners.click, 'function');
assert.equal(typeof listeners.change, 'function');

function actionElement(action) {
    const element = { dataset: { action } };
    return { element, target: { closest: () => element } };
}

let action = actionElement('openQueueFolder');
listeners.click({ target: action.target });
action = actionElement('submitDataDraft');
listeners.click({ target: action.target });
action = actionElement('submitDataPendingReview');
listeners.click({ target: action.target });
action = actionElement('confirmReviewSubmission');
listeners.change({ target: action.target });

assert.deepEqual(calls.slice(0, 3), [
    ['openQueueFolder', null],
    ['submitData', 'draft'],
    ['submitData', 'pending_review'],
]);
assert.equal(calls[3][0], 'confirmReviewSubmission');
assert.equal(calls[3][1], action.element);

console.log('Index page CSP self-check: OK');
