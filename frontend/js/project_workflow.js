/* global apiCall, projectManagementUsers, projectManagementProjects */

// =============================================================================
// PROJECT PIPELINE ("Quy trình số hóa") ADMIN PANEL
// Chỉnh lý -> Scan -> Check scan -> Nhập liệu -> Check nhập liệu -> Chuẩn hóa -> Bàn giao
// =============================================================================

var projectWorkflowProjectId = 0;
var projectWorkflowConfig = null;

const WORKFLOW_STATUS_LABELS = {
    pending: 'Chờ',
    in_progress: 'Đang làm',
    done: 'Xong',
    rejected: 'Trả lại',
};
const WORKFLOW_STATUS_CLASSES = {
    pending: 'bg-secondary',
    in_progress: 'bg-warning text-dark',
    done: 'bg-success',
    rejected: 'bg-danger',
};

function workflowApiBase() {
    return `/api/projects/${projectWorkflowProjectId}/workflow`;
}

function workflowStatusBadge(status) {
    const badge = document.createElement('span');
    badge.className = `badge ${WORKFLOW_STATUS_CLASSES[status] || 'bg-secondary'}`;
    badge.textContent = WORKFLOW_STATUS_LABELS[status] || status;
    return badge;
}

function workflowTextCell(row, text, className = '') {
    const cell = document.createElement('td');
    if (className) cell.className = className;
    cell.textContent = text;
    row.appendChild(cell);
    return cell;
}

function workflowAccountType(user) {
    if (user.role === 'admin') return 'admin';
    return user.account_type === 'ctv' ? 'ctv' : 'staff';
}

function workflowEnabledKeys() {
    return Array.from(document.querySelectorAll('.workflow-stage-enabled:checked'))
        .map(input => input.value);
}

function renderWorkflowConfig(config) {
    const container = document.getElementById('workflowConfigList');
    if (!container) return;
    container.replaceChildren();
    config.stages.forEach(stage => {
        // BA 3.3 / FR-AUT-03: pickers follow allowed_roles by account type, so
        // CTV accounts only appear on stages that allow "ctv".
        const allowed = stage.allowed_roles || ['admin', 'staff'];
        const workers = projectManagementUsers.filter(
            user => allowed.includes(workflowAccountType(user)),
        );
        const card = document.createElement('div');
        card.className = 'border rounded p-2 mb-2';
        const header = document.createElement('div');
        header.className = 'form-check';
        const toggle = document.createElement('input');
        toggle.type = 'checkbox';
        toggle.className = 'form-check-input workflow-stage-enabled';
        toggle.id = `workflow-stage-${stage.key}`;
        toggle.value = stage.key;
        toggle.checked = !!stage.enabled;
        const label = document.createElement('label');
        label.className = 'form-check-label fw-bold';
        label.htmlFor = toggle.id;
        label.textContent = stage.label;
        header.append(toggle, label);
        card.appendChild(header);

        if (stage.members_from_project) {
            const note = document.createElement('div');
            note.className = 'small text-muted mt-1';
            note.textContent = `Nhân sự lấy từ "Quản lý nhân sự" của dự án (${stage.member_user_ids.length} người). Trạng thái được tính từ dữ liệu nhập liệu.`;
            card.appendChild(note);
        } else {
            const selected = new Set(stage.member_user_ids.map(Number));
            const list = document.createElement('div');
            list.className = 'd-flex flex-wrap gap-3 mt-2';
            if (!workers.length) {
                list.textContent = 'Không có tài khoản phù hợp.';
            }
            workers.forEach(user => {
                const wrapper = document.createElement('div');
                wrapper.className = 'form-check';
                const input = document.createElement('input');
                input.type = 'checkbox';
                input.className = 'form-check-input workflow-member';
                input.dataset.stage = stage.key;
                input.value = String(Number(user.id));
                input.id = `workflow-member-${stage.key}-${Number(user.id)}`;
                input.checked = selected.has(Number(user.id));
                const name = document.createElement('label');
                name.className = 'form-check-label';
                name.htmlFor = input.id;
                name.textContent = {
                    admin: `${user.username} (Admin)`,
                    ctv: `${user.username} (CTV)`,
                }[workflowAccountType(user)] || user.username;
                wrapper.append(input, name);
                list.appendChild(wrapper);
            });
            card.appendChild(list);
        }
        container.appendChild(card);
    });
}

function renderWorkflowOverview(overview) {
    const summary = document.getElementById('workflowOverviewSummary');
    const body = document.getElementById('workflowOverviewBody');
    if (!summary || !body) return;
    body.replaceChildren();
    if (!overview.configured) {
        summary.textContent = 'Dự án chưa bật quy trình. Mở tab "Cấu hình" để chọn các bước áp dụng.';
        return;
    }
    const bottleneck = overview.stages.find(stage => stage.key === overview.bottleneck);
    summary.textContent = `${overview.completed_cases}/${overview.cases_total} hồ sơ đã qua mọi bước`
        + (bottleneck ? ` · điểm nghẽn: ${bottleneck.label} (${bottleneck.backlog} hồ sơ chờ/đang làm)` : '');
    overview.stages.forEach(stage => {
        const row = document.createElement('tr');
        if (!stage.enabled) row.className = 'text-muted';
        if (stage.key === overview.bottleneck) row.className = 'table-warning';
        workflowTextCell(row, stage.label, 'fw-bold');
        if (!stage.enabled) {
            const off = workflowTextCell(row, 'Không áp dụng');
            off.colSpan = 6;
        } else {
            workflowTextCell(row, String(stage.ready));
            workflowTextCell(row, String(stage.counts.pending));
            workflowTextCell(row, String(stage.counts.in_progress));
            workflowTextCell(row, String(stage.counts.rejected));
            workflowTextCell(row, String(stage.counts.done));
            workflowTextCell(row, String(stage.rework_total));
        }
        body.appendChild(row);
    });
}

function workflowCellActions(item, stage, cell) {
    const actions = [];
    if (stage.derived) return actions;
    if ((cell.status === 'pending' || cell.status === 'rejected') && cell.available) {
        actions.push(['start', 'Bắt đầu']);
    } else if (cell.status === 'in_progress') {
        actions.push(['complete', stage.kind === 'qc' ? 'Đạt' : 'Hoàn tất']);
        if (stage.kind === 'qc') actions.push(['reject', 'Trả lại']);
    } else if (cell.status === 'done') {
        actions.push(['reopen', 'Mở lại']);
    }
    return actions;
}

function renderWorkflowCases(data) {
    const head = document.getElementById('workflowCasesHead');
    const body = document.getElementById('workflowCasesBody');
    if (!head || !body) return;
    head.replaceChildren();
    body.replaceChildren();
    const enabled = data.enabled_stages || [];
    const stagesByKey = new Map(projectWorkflowConfig.stages.map(stage => [stage.key, stage]));
    const headRow = document.createElement('tr');
    const caseHeader = document.createElement('th');
    caseHeader.textContent = 'Hồ sơ';
    headRow.appendChild(caseHeader);
    enabled.forEach(key => {
        const th = document.createElement('th');
        th.textContent = stagesByKey.get(key)?.label || key;
        headRow.appendChild(th);
    });
    head.appendChild(headRow);

    if (!data.items.length) {
        const row = document.createElement('tr');
        const cell = workflowTextCell(row, enabled.length ? 'Chưa có hồ sơ.' : 'Chưa bật bước nào.', 'text-center text-muted');
        cell.colSpan = enabled.length + 1;
        body.appendChild(row);
        return;
    }
    data.items.forEach(item => {
        const row = document.createElement('tr');
        const nameCell = workflowTextCell(row, item.display_name, 'fw-bold');
        nameCell.title = item.case_key;
        enabled.forEach(key => {
            const stage = stagesByKey.get(key);
            const cellData = item.stages[key];
            const td = document.createElement('td');
            td.appendChild(workflowStatusBadge(cellData.status));
            if (cellData.rework_count) {
                const rework = document.createElement('small');
                rework.className = 'text-danger ms-1';
                rework.textContent = `↺${cellData.rework_count}`;
                td.appendChild(rework);
            }
            workflowCellActions(item, stage, cellData).forEach(([action, label]) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'btn btn-sm btn-outline-secondary ms-1 py-0';
                button.textContent = label;
                button.addEventListener('click', () => workflowTransition(item.case_id, key, action));
                td.appendChild(button);
            });
            row.appendChild(td);
        });
        body.appendChild(row);
    });
}

async function refreshProjectWorkflow() {
    const [config, overview, cases] = await Promise.all([
        apiCall(workflowApiBase(), { cache: 'no-store' }),
        apiCall(`${workflowApiBase()}/overview`, { cache: 'no-store' }),
        apiCall(`${workflowApiBase()}/cases?page_size=200`, { cache: 'no-store' }),
    ]);
    if (!config || !overview || !cases) return false;
    projectWorkflowConfig = config.data;
    renderWorkflowConfig(config.data);
    renderWorkflowOverview(overview.data);
    renderWorkflowCases(cases.data);
    return true;
}

async function openProjectWorkflow(projectId) {
    const project = projectManagementProjects.find(item => Number(item.id) === Number(projectId));
    if (!project) return alert('Không tìm thấy dự án trong danh sách hiện tại.');
    projectWorkflowProjectId = Number(project.id);
    document.getElementById('projectWorkflowModalTitle').textContent = project.name;
    if (!(await refreshProjectWorkflow())) return;
    new bootstrap.Modal(document.getElementById('projectWorkflowModal')).show();
}

async function saveProjectWorkflow() {
    if (!projectWorkflowProjectId) return;
    const enabled = workflowEnabledKeys();
    const members = {};
    document.querySelectorAll('.workflow-member:checked').forEach(input => {
        (members[input.dataset.stage] ||= []).push(Number(input.value));
    });
    const button = document.getElementById('saveProjectWorkflowButton');
    if (button) button.disabled = true;
    try {
        const response = await apiCall(workflowApiBase(), {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({enabled_stages: enabled, members}),
        });
        if (!response) return;
        const backfilled = Number(response.data.backfilled_states || 0);
        if (backfilled) {
            alert(`Đã bật quy trình. ${backfilled} trạng thái của hồ sơ đã có PDF được đánh dấu hoàn tất cho các bước trước nhập liệu.`);
        }
        await refreshProjectWorkflow();
    } finally {
        if (button) button.disabled = false;
    }
}

async function workflowTransition(caseId, stageKey, action) {
    let reason = null;
    if (action === 'reject' || action === 'reopen') {
        reason = (window.prompt('Nhập lý do:') || '').trim();
        if (!reason) return;
    }
    const response = await apiCall(
        `${workflowApiBase()}/cases/${Number(caseId)}/stages/${encodeURIComponent(stageKey)}/transition`,
        {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action, reason}),
        },
    );
    if (response) await refreshProjectWorkflow();
}
