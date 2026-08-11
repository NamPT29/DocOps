const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

function createNode(tagName) {
    return {
        tagName,
        textContent: '',
        children: [],
        appendChild(child) { this.children.push(child); },
        replaceChildren() { this.children = []; },
    };
}

const previewBody = createNode('tbody');
const status = createNode('div');
const importButton = { disabled: true };
const sandbox = {
    console,
    document: {
        createElement: createNode,
        getElementById(id) {
            if (id === 'bulkDictionaryPreviewBody') return previewBody;
            if (id === 'bulkDictionaryStatus') return status;
            if (id === 'bulkDictionaryImportButton') return importButton;
            return null;
        },
    },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/template_config.js', 'utf8'), sandbox);

const parsed = vm.runInContext(
    `parseBulkDictionaryText('001 - Kinh\\n002 - Giá trị - có gạch\\nA-03\\tThái')`,
    sandbox,
);
assert.deepEqual(
    JSON.parse(JSON.stringify(parsed.items.map(item => [item.code, item.value]))),
    [
        ['001', 'Kinh'],
        ['002', 'Giá trị - có gạch'],
        ['A-03', 'Thái'],
    ],
);
assert.equal(parsed.errors.length, 0);

const duplicate = vm.runInContext(
    `parseBulkDictionaryText('01 - Kinh\\n01 - Trùng')`,
    sandbox,
);
assert.equal(duplicate.items.length, 1);
assert.equal(duplicate.errors.length, 1);

const xssPayload = '<img src=x onerror=alert(1)>';
sandbox.renderBulkDictionaryPreview({
    items: [{ lineNumber: 1, code: '01', value: xssPayload }],
    errors: [],
});
assert.equal(previewBody.children.length, 1);
assert.equal(previewBody.children[0].children[2].textContent, xssPayload);
assert.equal(previewBody.children[0].children[2].children.length, 0);
assert.equal(importButton.disabled, false);

console.log('Dictionary bulk self-check: OK');
