const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class FakeElement {
    constructor(id = '') {
        this.id = id;
        this.value = '';
        this.checked = false;
        this.disabled = false;
        this.textContent = '';
        this.attributes = {};
        this.nodes = [];
        this._innerHTML = '';
    }

    set innerHTML(value) {
        this._innerHTML = String(value);
        this.nodes = [];
        if (this.id !== 'unifiedColConfigBody') return;

        const inputPattern = /<input\s+class="([^"]*unified-chk-[^"]*)"[^>]*value="([^"]+)"[^>]*id="([^"]+)"[^>]*>/g;
        for (const match of this._innerHTML.matchAll(inputPattern)) {
            const input = new FakeElement(match[3]);
            input.className = match[1];
            input.value = match[2];
            this.nodes.push(input);
        }

        const buttonPattern = /<button\s+type="button"\s+class="([^"]*ocr-region-button[^"]*)"\s+data-col="([^"]+)">([^<]*)<\/button>/g;
        for (const match of this._innerHTML.matchAll(buttonPattern)) {
            const button = new FakeElement();
            button.className = match[1];
            button.attributes['data-col'] = match[2];
            button.textContent = match[3];
            button.disabled = false;
            this.nodes.push(button);
        }
    }

    get innerHTML() {
        return this._innerHTML;
    }

    getAttribute(name) {
        return this.attributes[name] ?? null;
    }

    setAttribute(name, value) {
        this.attributes[name] = String(value);
    }

    querySelectorAll(selector) {
        if (selector === 'option[value=""]') return [];
        return this.nodes.filter(node => matchesSelector(node, selector));
    }

    querySelector(selector) {
        return this.querySelectorAll(selector)[0] || null;
    }
}

function matchesSelector(node, selector) {
    const checked = selector.endsWith(':checked');
    const dataColMatch = selector.match(/\[data-col="([^"]+)"\]/);
    if (dataColMatch && node.getAttribute('data-col') !== dataColMatch[1]) return false;
    const className = selector
        .replace(/:checked$/, '')
        .replace(/\[data-col="[^"]+"\]/, '')
        .replace(/^\./, '');
    if (checked && !node.checked) return false;
    return className.split('.').every(name => node.className?.split(/\s+/).includes(name));
}

const elements = {
    unifiedColConfigBody: new FakeElement('unifiedColConfigBody'),
    configJsonInput: new FakeElement('configJsonInput'),
    dictRulesBody: new FakeElement('dictRulesBody'),
    syncRulesList: new FakeElement('syncRulesList'),
    concatRulesList: new FakeElement('concatRulesList'),
    errorReportThresholdPercent: new FakeElement('errorReportThresholdPercent'),
    coverFolderLevels: new FakeElement('coverFolderLevels'),
    linkedPdfPathEnabled: new FakeElement('linkedPdfPathEnabled'),
    linkedPdfPathCol: new FakeElement('linkedPdfPathCol'),
    linkedPdfPathFolderLevels: new FakeElement('linkedPdfPathFolderLevels'),
};
elements.errorReportThresholdPercent.value = '5';
elements.coverFolderLevels.value = '0';
elements.linkedPdfPathFolderLevels.value = '0';

const document = {
    body: new FakeElement('body'),
    getElementById: id => elements[id] || null,
    querySelectorAll(selector) {
        if (selector === '.col-dropdown' || selector === '.dict-dropdown') return [];
        return selector.split(',').flatMap(part => elements.unifiedColConfigBody.nodes.filter(node => matchesSelector(node, part.trim())));
    },
    querySelector(selector) {
        const idMatch = selector.match(/^#([^ ]+)$/);
        if (idMatch) return elements[idMatch[1]] || elements.unifiedColConfigBody.nodes.find(node => node.id === idMatch[1]) || null;
        return this.querySelectorAll(selector)[0] || null;
    },
    addEventListener() {},
};

let refreshCalls = 0;
const sandbox = {
    console,
    document,
    escapeHTML: value => String(value),
    refreshOcrButtons() {
        refreshCalls += 1;
        document.querySelectorAll('.ocr-region-button').forEach(button => {
            button.disabled = false;
        });
    },
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/template_config.js', 'utf8'), sandbox);
vm.runInContext(`
    templateFields = [
        { col: 1, label: '[Cột 1] Họ tên' },
        { col: 2, label: '[Cột 2] Ngày sinh' },
        { col: 3, label: '[Cột 3] Số giấy tờ' },
    ];
    populateColDropdowns();
`, sandbox);

const adminHtml = fs.readFileSync('frontend/admin.html', 'utf8');
const bodyMarker = '<tbody id="unifiedColConfigBody">';
const bodyIndex = adminHtml.indexOf(bodyMarker);
const tableStart = adminHtml.lastIndexOf('<table', bodyIndex);
const tableEnd = adminHtml.indexOf('</table>', bodyIndex);
const configTable = bodyIndex >= 0 && tableStart >= 0 && tableEnd >= 0
    ? adminHtml.slice(tableStart, tableEnd + '</table>'.length)
    : '';
const headerRow = configTable.match(/<thead[\s\S]*?<tr>([\s\S]*?)<\/tr>/i)?.[1] || '';
const headers = [...headerRow.matchAll(/<th\b[^>]*>([\s\S]*?)<\/th>/gi)]
    .map(match => match[1].replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim());
assert.equal(headers.length, 8);
assert(headers[6].includes('Bắt buộc nhập'));
assert.equal(headers[7], 'OCR');
assert(!adminHtml.includes('Chữ gợi ý (Placeholder)'));

const body = elements.unifiedColConfigBody;
assert.equal(body.querySelectorAll('.unified-chk-required').length, 3);
assert.equal(body.querySelectorAll('.unified-chk-ocr').length, 3);
assert.equal(body.querySelectorAll('.ocr-region-button').length, 3);
body.querySelectorAll('.ocr-region-button').forEach(button => {
    assert.equal(button.textContent, 'Chọn vùng');
    assert.equal(button.disabled, false);
});

vm.runInContext(`currentConfigObj = {
    required_cols: [2],
    ocr_cols: [3],
    ocr_regions: [{ col: 3, regions: [{ x: 0, y: 0, width: 10, height: 10 }] }],
    placeholder_rules: [{ col: 2, text: 'legacy hint' }],
}; renderVisualUiFromJSON();`, sandbox);

const required2 = document.querySelector('#chk_required_2');
const ocr2 = document.querySelector('#chk_ocr_2');
const ocr3 = document.querySelector('#chk_ocr_3');
assert.equal(required2.checked, true);
assert.equal(ocr2.checked, false);
assert.equal(ocr3.checked, true);
assert.equal(document.querySelector('.ocr-region-button[data-col="2"]')?.disabled, false);
assert.equal(document.querySelector('.ocr-region-button[data-col="3"]')?.disabled, false);
assert(refreshCalls > 0);

vm.runInContext('buildConfigFromUI()', sandbox);
let saved = JSON.parse(elements.configJsonInput.value);
assert.deepEqual(saved.required_cols, [2]);
assert.deepEqual(saved.ocr_cols, [3]);
assert.deepEqual(saved.ocr_regions, [{ col: 3, regions: [{ x: 0, y: 0, width: 10, height: 10 }] }]);
assert.equal(Object.hasOwn(saved, 'placeholder_rules'), false);

required2.checked = false;
ocr3.checked = true;
vm.runInContext('buildConfigFromUI()', sandbox);
saved = JSON.parse(elements.configJsonInput.value);
assert.deepEqual(saved.required_cols, []);
assert.deepEqual(saved.ocr_cols, [3]);

required2.checked = true;
ocr3.checked = false;
vm.runInContext('buildConfigFromUI()', sandbox);
saved = JSON.parse(elements.configJsonInput.value);
assert.deepEqual(saved.required_cols, [2]);
assert.deepEqual(saved.ocr_cols, []);
assert.deepEqual(saved.ocr_regions, [{ col: 3, regions: [{ x: 0, y: 0, width: 10, height: 10 }] }]);

vm.runInContext('currentConfigObj = {}; renderVisualUiFromJSON(); buildConfigFromUI();', sandbox);
saved = JSON.parse(elements.configJsonInput.value);
assert.deepEqual(saved.ocr_cols, []);
assert.equal(required2.checked, false);
assert.equal(ocr2.checked, false);
assert.equal(ocr3.checked, false);

console.log('Template placeholder/OCR config self-check: OK');
