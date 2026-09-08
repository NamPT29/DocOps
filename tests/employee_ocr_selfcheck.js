const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const html = fs.readFileSync('frontend/index.html', 'utf8');
const imageSource = fs.readFileSync('frontend/js/ocr_image.js', 'utf8');
const ocrSource = fs.readFileSync('frontend/js/employee_ocr.js', 'utf8');
const configSource = fs.readFileSync('frontend/js/ocr_config.js', 'utf8');

assert.match(html, /vendor\/tesseract\/tesseract\.min\.js\?v=/);
assert.match(html, /id="ocrStartButton"/);
assert.match(html, /id="ocrResumeButton"/);
assert.match(html, /id="ocrPauseButton"/);
assert.match(html, /id="ocrRetryButton"/);
assert.match(ocrSource, /fetch\('\/health\/live'/);
assert.match(ocrSource, /createWorker\('vie', 1/);
assert.match(ocrSource, /workerPath: TESSERACT_WORKER_PATH/);
assert.match(ocrSource, /worker\.recognize\(upscale\(canvas\)/);
assert.match(ocrSource, /ocr_status = status/);
assert.match(ocrSource, /textContent = 'ocr done'/);
assert.match(ocrSource, /Never overwrite a value entered by a person/);
assert.match(imageSource, /source canvas is treated as immutable/i);
assert.match(imageSource, /root\.OcrImage = Object\.freeze/);
assert.match(imageSource, /function crop\(sourceCanvas, bbox/);
assert.match(imageSource, /function detectTextBounds\(canvas, options/);
assert.match(ocrSource, /OcrImage\.crop\(prepared, region\.bbox, \{\s*snap:\s*true\s*\}\)/);
assert.match(configSource, /OcrImage\.prepare\(target/);
assert.match(configSource, /đã làm sạch/);
assert(!ocrSource.includes('fetch(\'/api/ocr'));
assert(!ocrSource.includes('fetch("/api/ocr'));

const listeners = {};
const elements = new Map();
function makeElement(id) {
    return elements.get(id) || (() => {
        const element = {
            id,
            hidden: false,
            disabled: false,
            textContent: '',
            classList: { toggle() {}, add() {}, remove() {} },
            addEventListener(type, listener) { this[`on${type}`] = listener; },
        };
        elements.set(id, element);
        return element;
    })();
}
const sandbox = {
    console,
    URLSearchParams,
    Date,
    Promise,
    navigator: { onLine: true },
    currentUser: { username: 'employee' },
    currentUserCanInput: () => true,
    fetch: async () => ({ ok: true }),
    document: {
        readyState: 'loading',
        getElementById: makeElement,
        addEventListener(type, listener) { listeners[type] = listener; },
    },
    window: { location: { search: '' }, addEventListener() {}, setInterval() {} },
};
sandbox.window.window = sandbox.window;
vm.createContext(sandbox);
vm.runInContext(ocrSource, sandbox, { filename: 'employee_ocr.js' });
assert.equal(typeof sandbox.window.EmployeeOcr.appendStatus, 'function');
assert.equal(typeof sandbox.window.EmployeeOcr.formReady, 'function');
assert.equal(typeof sandbox.window.EmployeeOcr.start, 'function');

console.log('Employee OCR self-check: OK');
