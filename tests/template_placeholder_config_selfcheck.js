const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function hintInput(col) {
    return {
        value: '',
        dataCol: String(col),
        getAttribute(name) {
            return name === 'data-col' ? this.dataCol : null;
        },
    };
}

const hintInputs = [hintInput(8), hintInput(13)];
const placeholderContainer = {
    innerHTML: '',
    querySelectorAll(selector) {
        if (selector === '.placeholder-rule-text') return hintInputs;
        return [];
    },
    querySelector(selector) {
        const inputMatch = selector.match(/^\.placeholder-rule-text\[data-col="(\d+)"\]$/);
        if (inputMatch) {
            return hintInputs.find(item => item.dataCol === inputMatch[1]) || null;
        }
        return null;
    },
};

const emptyCheckboxPanel = { querySelectorAll() { return []; } };
const elements = {
    placeholderColSelect: placeholderContainer,
    roColSelect: emptyCheckboxPanel,
    dateColSelect: emptyCheckboxPanel,
    yearColSelect: emptyCheckboxPanel,
    linkedPdfPathEnabled: { checked: false },
    linkedPdfPathCol: { value: '' },
    linkedPdfPathFolderLevels: { value: '0' },
    configJsonInput: { value: '' },
    dictRulesBody: { innerHTML: '' },
    syncRulesList: { innerHTML: '' },
    concatRulesList: { innerHTML: '' },
};
const sandbox = {
    console,
    escapeHTML: value => String(value),
    document: {
        getElementById: id => elements[id] || null,
        querySelectorAll: selector => placeholderContainer.querySelectorAll(selector),
        querySelector: selector => placeholderContainer.querySelector(selector),
    },
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/template_config.js', 'utf8'), sandbox);
vm.runInContext(`currentConfigObj = {
    placeholder_rules: [
        { col: 8, text: 'Ví dụ: Nguyễn Văn A' },
        { col: 13, text: 'Nhập số giấy tờ' },
    ],
}; renderVisualUiFromJSON();`, sandbox);

assert.equal(hintInputs[0].value, 'Ví dụ: Nguyễn Văn A');
assert.equal(hintInputs[1].value, 'Nhập số giấy tờ');

hintInputs[1].value = '';
vm.runInContext('buildConfigFromUI()', sandbox);
const saved = JSON.parse(elements.configJsonInput.value);
assert.deepEqual(saved.placeholder_rules, [
    { col: 8, text: 'Ví dụ: Nguyễn Văn A' },
]);

const adminHtml = fs.readFileSync('frontend/admin.html', 'utf8');
assert(adminHtml.includes('id="unifiedColConfigBody"'));
assert(adminHtml.includes('Chữ gợi ý (Placeholder)'));
console.log('Template placeholder config self-check: OK');
