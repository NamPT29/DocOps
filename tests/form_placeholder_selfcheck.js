const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const sandbox = { console };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/form_renderer.js', 'utf8'), sandbox);

assert.equal(
    sandbox.getConfiguredPlaceholder(
        { placeholder_rules: [{ col: 8, text: 'Ví dụ: Nguyễn Văn A' }] },
        8,
        '',
    ),
    'Ví dụ: Nguyễn Văn A',
);
assert.equal(
    sandbox.getConfiguredPlaceholder(
        { placeholder_rules: [{ col: 8, text: '   ' }] },
        8,
        'dd/mm/yyyy',
    ),
    'dd/mm/yyyy',
);
assert.equal(
    sandbox.getConfiguredPlaceholder({}, 8, 'yyyy'),
    'yyyy',
);

const source = fs.readFileSync('frontend/js/form_renderer.js', 'utf8');
assert(source.includes('input.placeholder = getConfiguredPlaceholder('));
console.log('Form placeholder self-check: OK');
