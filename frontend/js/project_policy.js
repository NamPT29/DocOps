/* global apiCall, projectManagementProjects */

// =============================================================================
// PROJECT POLICY (FR-PRJ-03, QC-01/02/03/07/08/09)
// An empty field follows the current QC-01 default; only typed values are
// stored for the project.
// =============================================================================

var projectPolicyProjectId = 0;

function projectPolicyFields() {
    return Array.from(document.querySelectorAll('[data-policy-key]'));
}

function formatPolicyDefault(value) {
    if (value === null || value === undefined || value === '') return '(trống)';
    // Vietnamese decimal comma for hints: 1.3 -> 1,3
    return typeof value === 'number' ? String(value).replace('.', ',') : String(value);
}

function setProjectPolicyStatus(message) {
    const status = document.getElementById('projectPolicyStatus');
    if (status) status.textContent = message || '';
}

function fillProjectPolicyForm(policy) {
    const defaults = policy.defaults || {};
    const overrides = policy.overrides || {};
    projectPolicyFields().forEach(field => {
        const key = field.dataset.policyKey;
        const override = overrides[key];
        if (field.dataset.policyType === 'bool') {
            field.value = override === true ? 'true' : (override === false ? 'false' : '');
            const defaultOption = field.querySelector('option[value=""]');
            if (defaultOption) {
                defaultOption.textContent = `Theo QC-01 (${defaults[key] ? 'Bật' : 'Tắt'})`;
            }
        } else {
            field.value = override === null || override === undefined ? '' : String(override);
            if (field.tagName === 'SELECT') {
                const defaultOption = field.querySelector('option[value=""]');
                const profiles = policy.export_profiles || {};
                if (defaultOption) {
                    defaultOption.textContent = `Theo mặc định QC-01: ${profiles[defaults[key]] || defaults[key]}`;
                }
            } else if (key !== 'organ_code' && key !== 'file_notation') {
                field.placeholder = `Mặc định: ${formatPolicyDefault(defaults[key])}`;
            }
        }
    });
    const version = document.getElementById('projectPolicyQcVersion');
    if (version) version.textContent = policy.qc_version || 'QC-01';
    const updated = policy.updated_by
        ? `Sửa lần cuối bởi ${policy.updated_by}${policy.updated_at ? ` lúc ${new Date(policy.updated_at).toLocaleString('vi-VN')}` : ''}.`
        : 'Dự án đang dùng toàn bộ mặc định.';
    setProjectPolicyStatus(updated);
}

function collectProjectPolicyPayload() {
    const payload = {};
    projectPolicyFields().forEach(field => {
        const key = field.dataset.policyKey;
        const raw = String(field.value || '').trim();
        if (field.dataset.policyType === 'bool') {
            payload[key] = raw === 'true' ? true : (raw === 'false' ? false : null);
        } else if (!raw) {
            payload[key] = null;
        } else if (field.type === 'number') {
            const number = Number(raw);
            // Leave unparsable text as is so the server explains the error.
            payload[key] = Number.isFinite(number) ? number : raw;
        } else {
            payload[key] = raw;
        }
    });
    return payload;
}

async function openProjectPolicy(projectId) {
    const project = projectManagementProjects.find(item => Number(item.id) === Number(projectId));
    if (!project) return alert('Không tìm thấy dự án trong danh sách hiện tại.');
    const response = await apiCall(`/api/projects/${Number(project.id)}/policy`, { cache: 'no-store' });
    if (!response) return;
    projectPolicyProjectId = Number(project.id);
    document.getElementById('projectPolicyModalTitle').textContent = project.name;
    fillProjectPolicyForm(response.data);
    new bootstrap.Modal(document.getElementById('projectPolicyModal')).show();
}

async function saveProjectPolicy() {
    if (!projectPolicyProjectId) return;
    const button = document.getElementById('saveProjectPolicyButton');
    if (button) button.disabled = true;
    try {
        const response = await apiCall(`/api/projects/${projectPolicyProjectId}/policy`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(collectProjectPolicyPayload()),
        });
        if (!response) return;
        fillProjectPolicyForm(response.data);
        setProjectPolicyStatus('Đã lưu chính sách dự án.');
    } finally {
        if (button) button.disabled = false;
    }
}

function resetProjectPolicyDefaults() {
    projectPolicyFields().forEach(field => { field.value = ''; });
    setProjectPolicyStatus('Đã xóa giá trị riêng. Bấm "Lưu chính sách" để áp dụng mặc định QC-01.');
}
