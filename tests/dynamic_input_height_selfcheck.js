const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('frontend/js/form_renderer.js', 'utf8');
const submissionSource = fs.readFileSync('frontend/js/submission.js', 'utf8');
const adminPanelSource = fs.readFileSync('frontend/js/admin_panel.js', 'utf8');
const employeeHtml = fs.readFileSync('frontend/index.html', 'utf8');
const employeeCss = fs.readFileSync('frontend/index-page.css', 'utf8');
const sandbox = {
    window: {},
    document: {},
    console,
};

vm.createContext(sandbox);
vm.runInContext(source, sandbox, { filename: 'frontend/js/form_renderer.js' });

function createTextarea(minHeight, contentHeight) {
    return {
        classList: {
            contains(className) { return className === 'dynamic-height-input'; },
        },
        clientHeight: minHeight,
        dataset: {},
        style: { height: '' },
        get scrollHeight() { return contentHeight; },
    };
}

const longTextarea = createTextarea(38, 96);
sandbox.resizeDynamicFormInput(longTextarea);
assert.equal(longTextarea.style.height, '98px');
assert.equal(longTextarea.dataset.dynamicMinHeight, '38');

const shortTextarea = createTextarea(38, 20);
sandbox.resizeDynamicFormInput(shortTextarea);
assert.equal(shortTextarea.style.height, '38px');

assert(source.includes("document.createElement('textarea')"));
assert(source.includes("input.className = 'form-control dynamic-height-input'"));
assert(source.includes("input.addEventListener('input', resizeInput)"));
assert(source.includes("input.addEventListener('change', resizeInput)"));
assert(source.includes("input.addEventListener('focus', resizeInput)"));
assert(source.includes("querySelectorAll('.dynamic-height-input')"));
assert(source.includes("#dataForm textarea"));
assert(submissionSource.includes("#dataForm textarea"));
assert(submissionSource.includes("resizeDynamicFormInputs(document.getElementById('dataForm'))"));
assert(adminPanelSource.includes("#dataForm input, #dataForm textarea, #dataForm select"));
assert(adminPanelSource.includes("resizeDynamicFormInputs(document.getElementById('dataForm'))"));
assert(employeeHtml.includes('class="index-form-scroll"'));
assert.match(employeeCss, /\.index-form-scroll\s*{[^}]*overflow-y:\s*auto;[^}]*overflow-x:\s*hidden;/s);
assert.match(employeeHtml, /<script src="js\/form_renderer\.js\?v=[^"]+"><\/script>/);

console.log('Dynamic input height self-check: OK');
