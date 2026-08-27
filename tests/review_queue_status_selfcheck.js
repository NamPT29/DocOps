const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function createClassList() {
    const values = new Set();
    return {
        add(...names) { names.forEach(name => values.add(name)); },
        remove(...names) { names.forEach(name => values.delete(name)); },
        contains(name) { return values.has(name); },
    };
}

function createElement(tagName) {
    return {
        tagName,
        children: [],
        className: '',
        classList: createClassList(),
        style: {},
        appendChild(child) { this.children.push(child); },
        textContent: '',
        innerText: '',
    };
}

const sandbox = {
    console,
    window: { activeTemplateConfig: {}, pdfLinkState: { setLinked() {} } },
    document: {
        createElement,
        getElementById() { return null; },
    },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/pdf_handler.js', 'utf8'), sandbox);

function statusFor(file) {
    const list = createElement('div');
    sandbox.appendQueueFileRow(list, file, 0);
    return list.children[0].children[0];
}

assert.equal(statusFor({ name: 'draft.pdf', completed: false }).textContent, 'Chưa nhập');
assert.equal(statusFor({ name: 'entered.pdf', completed: true }).textContent, 'Đã nhập');
assert.equal(
    statusFor({ name: 'pending.pdf', review_status: 'pending_review' }).textContent,
    'Chờ kiểm duyệt',
);
assert.equal(
    statusFor({ name: 'confirm.pdf', review_status: 'pending_input_confirmation' }).textContent,
    'Chờ người nhập xác nhận',
);
const completed = statusFor({ name: 'completed.pdf', review_status: 'completed' });
assert.equal(completed.textContent, 'Hoàn thành');
assert.match(completed.className, /bg-success/);

const source = fs.readFileSync('frontend/js/pdf_handler.js', 'utf8');
assert(source.includes('review_status: file.review_status || null'));
console.log('Review queue status self-check: OK');
