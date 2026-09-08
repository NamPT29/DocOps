const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const threshold = { value: '5' };
const configJson = { value: '' };
const genericList = { innerHTML: '', querySelectorAll() { return []; } };
const elements = {
    errorReportThresholdPercent: threshold,
    configJsonInput: configJson,
    dictRulesBody: genericList,
    syncRulesList: genericList,
    concatRulesList: genericList,
};

const sandbox = {
    console,
    escapeHTML: value => String(value),
    document: {
        getElementById: id => elements[id] || null,
        querySelectorAll() { return []; },
        querySelector() { return null; },
    },
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/template_config.js', 'utf8'), sandbox);

vm.runInContext('currentConfigObj = { error_report_threshold_percent: 12 }; renderVisualUiFromJSON();', sandbox);
assert.equal(threshold.value, '12');

threshold.value = '150';
vm.runInContext('buildConfigFromUI()', sandbox);
assert.equal(JSON.parse(configJson.value).error_report_threshold_percent, 100);
assert.equal(threshold.value, '100');

vm.runInContext('currentConfigObj = { error_report_threshold_percent: 0 }; renderVisualUiFromJSON();', sandbox);
assert.equal(threshold.value, '1');

vm.runInContext('currentConfigObj = {}; renderVisualUiFromJSON();', sandbox);
assert.equal(threshold.value, '5');

const adminHtml = fs.readFileSync('frontend/admin.html', 'utf8');
assert(adminHtml.includes('id="errorReportThresholdPercent"'));
assert(adminHtml.includes('min="1" max="100"'));
assert(/js\/template_config\.js\?v=[\d.]+/.test(adminHtml));

console.log('Template quality threshold self-check: OK');
