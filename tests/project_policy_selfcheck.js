// FR-PRJ-03: project policy dialog (QC-01/02/03/07/08/09).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('frontend/js/project_policy.js', 'utf8');
const html = fs.readFileSync('frontend/admin.html', 'utf8');
const management = fs.readFileSync('frontend/js/project_management.js', 'utf8');
const adminPage = fs.readFileSync('frontend/admin-page.js', 'utf8');

const KEYS = [
    'error_threshold_percent', 'sample_rate_percent', 'box_deadline_days',
    'organ_code', 'file_notation', 'export_profile',
    'bad_paper_factor', 'overtime_factor', 'sunday_factor',
];

assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML|document\.write/, 'Render with textContent only.');
assert.match(html, /id="projectPolicyModal"/);
assert.match(html, /src="js\/project_policy\.js\?v=[\d.]+"/);
assert.deepEqual(Array.from(html.matchAll(/data-policy-key="([^"]+)"/g), match => match[1]), KEYS);
assert.match(html, /Ngưỡng lỗi của hộp \(BR-07\)/);
assert.match(html, /data-admin-action="save-project-policy"/);
assert.match(html, /data-admin-action="reset-project-policy"/);
assert.match(adminPage, /'save-project-policy': \(\) => saveProjectPolicy\(\)/);
assert.match(adminPage, /'reset-project-policy': \(\) => resetProjectPolicyDefaults\(\)/);
assert.match(management, /label: 'Chính sách dự án',[\s\S]*?openProjectPolicy\(project\.id\)/);

function field(key) {
    const isSelect = key === 'export_profile';
    const isText = key === 'organ_code' || key === 'file_notation';
    const defaultOption = { textContent: 'Theo mặc định QC-01' };
    return {
        dataset: { policyKey: key },
        tagName: isSelect ? 'SELECT' : 'INPUT',
        type: isSelect ? 'select-one' : (isText ? 'text' : 'number'),
        value: '',
        placeholder: isText ? 'Ví dụ' : '',
        querySelector: () => (isSelect ? defaultOption : null),
        defaultOption,
    };
}

const fields = KEYS.map(field);
const byKey = Object.fromEntries(fields.map(item => [item.dataset.policyKey, item]));
const elements = {
    projectPolicyStatus: { textContent: '' },
    projectPolicyQcVersion: { textContent: '' },
    projectPolicyModalTitle: { textContent: '' },
    projectPolicyModal: {},
    saveProjectPolicyButton: { disabled: false },
};
const calls = [];
const policy = {
    qc_version: 'QC-01 v0.1.1',
    defaults: {
        error_threshold_percent: 5, sample_rate_percent: 30, box_deadline_days: 2,
        organ_code: null, file_notation: null, export_profile: 'NN-SIP',
        bad_paper_factor: 1.3, overtime_factor: 1.2, sunday_factor: 1.4,
    },
    overrides: Object.fromEntries(KEYS.map(key => [key, null])),
    export_profiles: { 'NN-SIP': 'Khối Nhà nước (NN-SIP)', 'DANG-HD40': 'Khối Đảng (DANG-HD40)' },
    updated_by: null,
};
policy.overrides.organ_code = 'H05.02.02';
policy.overrides.sunday_factor = 1.5;

const sandbox = {
    console,
    alert() {},
    projectManagementProjects: [{ id: 7, name: 'Bộ Y tế' }],
    bootstrap: { Modal: class { show() { calls.push('show'); } } },
    document: {
        querySelectorAll: () => fields,
        getElementById: id => elements[id] || null,
    },
    async apiCall(url, options = {}) {
        calls.push({ url, method: options.method || 'GET', body: options.body });
        return { data: policy };
    },
};
vm.createContext(sandbox);
vm.runInContext(source, sandbox);

(async () => {
    await sandbox.openProjectPolicy(7);
    assert.equal(elements.projectPolicyModalTitle.textContent, 'Bộ Y tế');
    assert.equal(elements.projectPolicyQcVersion.textContent, 'QC-01 v0.1.1');
    // Stored values fill the inputs; empty ones show the QC-01 default as a hint.
    assert.equal(byKey.organ_code.value, 'H05.02.02');
    assert.equal(byKey.sunday_factor.value, '1.5');
    assert.equal(byKey.error_threshold_percent.value, '');
    assert.equal(byKey.bad_paper_factor.placeholder, 'Mặc định: 1,3');
    assert.equal(byKey.box_deadline_days.placeholder, 'Mặc định: 2');
    assert.equal(byKey.organ_code.placeholder, 'Ví dụ', 'Text fields keep their example hint.');
    assert.equal(byKey.export_profile.defaultOption.textContent, 'Theo mặc định QC-01: Khối Nhà nước (NN-SIP)');
    assert.match(elements.projectPolicyStatus.textContent, /mặc định/);

    // Empty fields are sent as null (= follow QC-01); numbers as numbers.
    byKey.error_threshold_percent.value = '4.5';
    byKey.file_notation.value = '  HC ';
    byKey.overtime_factor.value = 'abc';
    const payload = sandbox.collectProjectPolicyPayload();
    assert.equal(payload.error_threshold_percent, 4.5);
    assert.equal(payload.sample_rate_percent, null);
    assert.equal(payload.file_notation, 'HC');
    assert.equal(payload.export_profile, null);
    assert.equal(payload.overtime_factor, 'abc', 'Unparsable text goes to the server for a clear error.');

    byKey.overtime_factor.value = '';
    await sandbox.saveProjectPolicy();
    const put = calls.find(call => call.method === 'PUT');
    assert.equal(put.url, '/api/projects/7/policy');
    assert.deepEqual(Object.keys(JSON.parse(put.body)), KEYS);
    assert.equal(elements.saveProjectPolicyButton.disabled, false);

    sandbox.resetProjectPolicyDefaults();
    assert.ok(fields.every(item => item.value === ''));
    assert.match(elements.projectPolicyStatus.textContent, /Lưu chính sách/);

    console.log('Project policy self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
