const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class InputEvent {
    constructor(type, options = {}) {
        this.type = type;
        this.bubbles = options.bubbles === true;
    }
}

const sandbox = {
    window: {},
    document: {},
    console,
    Event: InputEvent,
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/form_renderer.js', 'utf8'), sandbox);

assert.equal(
    sandbox.normalizePastedFieldText('  Tiêu đề\n  hồ sơ\r\n UBND\t '),
    'Tiêu đề hồ sơ UBND',
);
assert.equal(sandbox.normalizePastedFieldText('\n\t  '), '');

let prevented = false;
let dispatchedEvent = null;
const input = {
    value: 'ABC xyz',
    selectionStart: 4,
    selectionEnd: 7,
    setRangeText(text, start, end) {
        this.value = this.value.slice(0, start) + text + this.value.slice(end);
        this.selectionStart = this.selectionEnd = start + text.length;
    },
    dispatchEvent(event) { dispatchedEvent = event; },
};
const pasteEvent = {
    clipboardData: {
        getData(type) {
            return type === 'text/plain' ? '  Nguyễn\n  Văn\t A  ' : '';
        },
    },
    preventDefault() { prevented = true; },
};

sandbox.pasteNormalizedFieldText(input, pasteEvent);
assert.equal(input.value, 'ABC Nguyễn Văn A');
assert.equal(prevented, true);
assert.equal(dispatchedEvent.type, 'input');
assert.equal(dispatchedEvent.bubbles, true);

const source = fs.readFileSync('frontend/js/form_renderer.js', 'utf8');
assert(source.includes("input.addEventListener('paste'"));
console.log('Paste whitespace self-check: OK');
