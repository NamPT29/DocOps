const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function checkbox(value) {
    return { value: String(value), checked: false };
}

const hiddenCheckboxes = [checkbox(1), checkbox(2), checkbox(3)];
const hiddenPanel = {
    innerHTML: '',
    querySelectorAll(selector) {
        if (selector === 'input[type=checkbox]') return hiddenCheckboxes;
        if (selector === 'input[type=checkbox]:checked') {
            return hiddenCheckboxes.filter(item => item.checked);
        }
        return [];
    },
};

const emptyCheckboxPanel = { querySelectorAll() { return []; } };
const elements = {
    hiddenColSelect: hiddenPanel,
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
const configSandbox = {
    console,
    escapeHTML: value => String(value),
    document: {
        getElementById: id => elements[id] || null,
        querySelectorAll(selector) {
            if (selector === '.unified-chk-hidden') return hiddenCheckboxes;
            if (selector === '.unified-chk-hidden:checked') {
                return hiddenCheckboxes.filter(item => item.checked);
            }
            return [];
        },
    },
};

vm.createContext(configSandbox);
vm.runInContext(fs.readFileSync('frontend/js/template_config.js', 'utf8'), configSandbox);
vm.runInContext('currentConfigObj = { hidden_cols: [2] }; renderVisualUiFromJSON();', configSandbox);
assert.equal(hiddenCheckboxes[0].checked, false);
assert.equal(hiddenCheckboxes[1].checked, true);
assert.equal(hiddenCheckboxes[2].checked, false);

hiddenCheckboxes[2].checked = true;
vm.runInContext('buildConfigFromUI()', configSandbox);
assert.deepEqual(JSON.parse(elements.configJsonInput.value).hidden_cols, [2, 3]);

vm.runInContext('currentConfigObj = { hidden_cols: [3] }; renderVisualUiFromJSON();', configSandbox);
assert.equal(hiddenCheckboxes[1].checked, false, 'Khôi phục cấu hình phải bỏ lựa chọn ẩn cũ');
assert.equal(hiddenCheckboxes[2].checked, true);

const rendererSandbox = { console };
vm.createContext(rendererSandbox);
vm.runInContext(fs.readFileSync('frontend/js/form_renderer.js', 'utf8'), rendererSandbox);
const visibleSchema = rendererSandbox.getVisibleFormSchema([
    {
        category: 'Thông tin hồ sơ',
        fields: [
            { col_index: 0, name: 'col_0' },
            { col_index: 1, name: 'col_1' },
            { col_index: 2, name: 'col_2' },
        ],
    },
    { category: 'Chỉ có ô ẩn', fields: [{ col_index: 1, name: 'col_1' }] },
], { hidden_cols: ['2'] });
assert.equal(visibleSchema.length, 1);
assert.deepEqual(
    Array.from(visibleSchema[0].fields, field => field.name),
    ['col_0', 'col_2'],
    'Ẩn cột không được đánh lại chỉ số của các ô còn hiển thị',
);

const adminHtml = fs.readFileSync('frontend/admin.html', 'utf8');
assert(adminHtml.includes('id="unifiedColConfigBody"'));
assert(adminHtml.includes('title="Ẩn cột trên form"'));
console.log('Template hidden fields self-check: OK');
