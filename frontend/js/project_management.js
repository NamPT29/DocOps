// =============================================================================
// PROJECT MANAGEMENT CORE CONTROLLER (Số hóa All in One)
// Chuyên trách: Danh sách dự án, phân công nhân sự, quản lý tài nguyên và xóa dự án
// =============================================================================

var projectManagementLoaded = false;
var projectManagementUsers = [];
var projectManagementProjects = [];

const PROJECT_STATUS_LABELS = {
    new: 'Mới',
    in_progress: 'Đang tiến hành',
    completed: 'Hoàn thành',
    overdue: 'Quá hạn',
};
const PROJECT_STATUS_CLASSES = {
    new: 'text-secondary',
    in_progress: 'text-warning',
    completed: 'text-success',
    overdue: 'text-danger',
};

function appendProjectCell(row, text, className = '') {
    const cell = document.createElement('td');
    cell.className = className;
    cell.textContent = text;
    row.appendChild(cell);
    return cell;
}

function renderProjectUserOptions(containerId, users, roleName) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.replaceChildren();
    if (!users.length) {
        const empty = document.createElement('span');
        empty.className = 'text-muted';
        empty.textContent = 'Không có tài khoản phù hợp.';
        container.appendChild(empty);
        return;
    }
    users.forEach(user => {
        const wrapper = document.createElement('div');
        wrapper.className = 'form-check';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.className = `form-check-input project-${roleName}-user`;
        input.value = String(Number(user.id));
        input.id = `project-${roleName}-user-${Number(user.id)}`;
        const label = document.createElement('label');
        label.className = 'form-check-label';
        label.htmlFor = input.id;
        label.textContent = `${user.username}${user.role === 'admin' ? ' (Admin)' : ''}`;
        wrapper.append(input, label);
        container.appendChild(wrapper);
    });
}

async function loadProjectFormOptions() {
    const [templateData, userData] = await Promise.all([
        apiCall('/api/templates'),
        apiCall('/api/users'),
    ]);
    if (templateData) {
        const select = document.getElementById('projectTemplateSelect');
        if (select) {
            select.replaceChildren();
            const placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = '-- Chọn biểu mẫu --';
            select.appendChild(placeholder);
            templateData.data.forEach(template => {
                const option = document.createElement('option');
                option.value = String(Number(template.id));
                option.textContent = template.name;
                select.appendChild(option);
            });
        }
    }
    if (userData) {
        const users = Array.isArray(userData.data) ? userData.data : [];
        projectManagementUsers = users;
        renderProjectUserOptions('projectInputUsers', users.filter(user => user.role !== 'admin'), 'input');
        renderProjectUserOptions('projectReviewerUsers', users, 'reviewer');
    }
}

async function updateProjectStatus(project, status, select) {
    const previousStatus = project.status;
    try {
        const response = await apiCall(`/api/projects/${Number(project.id)}/status`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({status}),
        });
        if (!response) throw new Error('Không thể cập nhật trạng thái dự án.');
        project.status = response.data?.status || status;
        select.className = `form-select form-select-sm ${PROJECT_STATUS_CLASSES[project.status] || ''}`.trim();
    } catch (error) {
        project.status = previousStatus;
        select.value = previousStatus;
        throw error;
    }
}

async function loadProjectList() {
    const body = document.getElementById('projectListBody');
    if (body) body.innerHTML = `
        <tr class="skeleton-table-row">
            <td><div class="skeleton-loader skeleton-text"></div><div class="skeleton-loader skeleton-text short mt-1"></div></td>
            <td><div class="skeleton-loader skeleton-text"></div><div class="skeleton-loader skeleton-text short mt-1"></div></td>
            <td><div class="skeleton-loader skeleton-text"></div><div class="skeleton-loader skeleton-text short mt-1"></div></td>
            <td><div class="skeleton-loader skeleton-text"></div></td>
            <td><div class="skeleton-loader skeleton-text"></div></td>
        </tr>
        <tr class="skeleton-table-row">
            <td><div class="skeleton-loader skeleton-text"></div><div class="skeleton-loader skeleton-text short mt-1"></div></td>
            <td><div class="skeleton-loader skeleton-text"></div><div class="skeleton-loader skeleton-text short mt-1"></div></td>
            <td><div class="skeleton-loader skeleton-text"></div><div class="skeleton-loader skeleton-text short mt-1"></div></td>
            <td><div class="skeleton-loader skeleton-text"></div></td>
            <td><div class="skeleton-loader skeleton-text"></div></td>
        </tr>`;
    const data = await apiCall('/api/projects', { cache: 'no-store' });
    if (!data || !body) return;
    projectManagementProjects = Array.isArray(data.data) ? data.data : [];
    body.replaceChildren();
    if (!projectManagementProjects.length) {
        body.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Chưa có dự án.</td></tr>';
        return;
    }
    projectManagementProjects.forEach(project => {
        const metrics = project.metrics || {};
        const row = document.createElement('tr');
        const nameCell = appendProjectCell(row, '');
        const strong = document.createElement('strong');
        strong.textContent = project.name;
        const detail = document.createElement('div');
        detail.className = 'small text-muted mt-1';
        detail.textContent = project.template_name;
        nameCell.append(strong, detail);
        const assignmentCell = appendProjectCell(row, '');
        assignmentCell.className = 'admin-project-metrics';
        assignmentCell.innerHTML = `<div><span>Nhập</span><strong>${metrics.input_assigned_cases || 0}/${metrics.total_cases || 0}</strong></div><div><span>Kiểm</span><strong>${metrics.reviewer_assigned_cases || 0}/${metrics.total_cases || 0}</strong></div>`;
        const progressCell = appendProjectCell(row, '');
        progressCell.className = 'admin-project-metrics';
        progressCell.innerHTML = `<div><span>Nhập</span><strong>${metrics.entered_reports || 0}/${metrics.required_reports || 0}</strong></div><div><span>Duyệt</span><strong>${metrics.approved_reports || 0}/${metrics.entered_reports || 0}</strong></div><div class="text-muted"><span>PDF</span><strong>${metrics.total_pdfs || 0}</strong>${metrics.error_pdfs ? ` · lỗi ${metrics.error_pdfs}` : ''}</div>`;
        const statusCell = appendProjectCell(row, '');
        const statusSelect = document.createElement('select');
        statusSelect.className = `form-select form-select-sm ${PROJECT_STATUS_CLASSES[project.status] || ''}`.trim();
        Object.entries(PROJECT_STATUS_LABELS).forEach(([value, label]) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = label;
            option.selected = project.status === value;
            statusSelect.appendChild(option);
        });
        statusSelect.addEventListener('change', async () => {
            try {
                await updateProjectStatus(project, statusSelect.value, statusSelect);
            } catch (error) {
                statusSelect.value = project.status;
                if (typeof setProjectUploadStatus === 'function') {
                    setProjectUploadStatus(error.message || 'Không thể cập nhật trạng thái.', 'danger');
                }
            }
        });
        statusCell.appendChild(statusSelect);
        const actionCell = appendProjectCell(row, '');
        actionCell.className = 'text-nowrap admin-project-actions';
        const buildActionDropdown = (label, icon, buttonClass, actions) => {
            const dropdown = document.createElement('div');
            dropdown.className = 'dropdown d-inline-block ms-1';
            const toggle = document.createElement('button');
            toggle.type = 'button';
            toggle.className = 'form-select form-select-sm d-inline-block w-auto text-start fw-medium';
            toggle.dataset.bsToggle = 'dropdown';
            toggle.setAttribute('aria-expanded', 'false');
            toggle.setAttribute('aria-label', `${label} cho dự án ${project.name}`);
            toggle.innerHTML = `--- ${label} ---`;

            const menu = document.createElement('ul');
            menu.className = 'dropdown-menu dropdown-menu-end shadow-sm small';
            toggle.dataset.bsBoundary = 'window';

            actions.forEach(action => {
                if (action.divider) {
                    const divider = document.createElement('li');
                    divider.innerHTML = '<hr class="dropdown-divider">';
                    menu.appendChild(divider);
                    return;
                }
                const item = document.createElement('li');
                const button = document.createElement('button');
                button.type = 'button';
                button.className = `dropdown-item ${action.className || ''}`.trim();
                button.innerHTML = `<i class="fas ${action.icon} me-2"></i>${action.label}`;
                button.addEventListener('click', action.handler);
                if (action.trackExport) button.dataset.projectExportId = String(project.id);
                item.appendChild(button);
                menu.appendChild(item);
            });
            dropdown.append(toggle, menu);
            return dropdown;
        };
        const projectActions = buildActionDropdown(
            'Thao tác',
            'fa-ellipsis',
            'btn-outline-primary',
            [
                {
                    label: 'Quản lý nhân sự',
                    icon: 'fa-users',
                    handler: () => openProjectMembers(project.id),
                },
                {divider: true},
                {
                    label: 'Thêm / cập nhật PDF',
                    icon: 'fa-sync-alt',
                    handler: () => prepareProjectFolderUpdate(project.id),
                },
                {
                    label: 'Quản lý / xóa PDF',
                    icon: 'fa-file-pdf',
                    handler: () => openProjectAssets(project.id),
                },
                {divider: true},
                {
                    label: 'Xóa dự án',
                    icon: 'fa-trash',
                    handler: () => deleteProject(project),
                    className: 'text-danger fw-bold',
                },
                {divider: true},
                {
                    label: 'Hồ sơ hoàn chỉnh',
                    icon: 'fa-check-circle',
                    handler: () => openProjectReports(project.id, 'completed'),
                },
                {
                    label: 'Kiểm duyệt',
                    icon: 'fa-search',
                    handler: () => openProjectReports(project.id, 'review'),
                },
                {divider: true},
                {
                    label: 'Xuất toàn bộ',
                    icon: 'fa-box-archive',
                    handler: () => exportProjectReports(project.id, true),
                    className: 'fw-bold',
                    trackExport: true,
                },
                {
                    label: 'Chỉ xuất hồ sơ đã kiểm duyệt',
                    icon: 'fa-circle-check',
                    handler: () => exportProjectReports(project.id, false),
                    trackExport: true,
                },
            ],
        );
        actionCell.append(projectActions);
        body.appendChild(row);
    });
}

async function deleteProject(project) {
    if (!project || !Number(project.id)) return;
    const warning = (
        `Xóa vĩnh viễn dự án “${project.name}”?\n\n`
        + 'Toàn bộ folder, PDF, báo cáo đã lưu, phân công và công việc kiểm duyệt '
        + 'của dự án sẽ bị xóa. Thao tác này không thể hoàn tác.'
    );
    if (!confirm(warning)) return;
    const typedName = prompt(`Nhập chính xác tên dự án để xác nhận:\n${project.name}`);
    if (typedName === null) return;
    if (typedName.trim() !== String(project.name || '').trim()) {
        alert('Tên dự án không khớp. Hệ thống chưa xóa dữ liệu.');
        return;
    }

    const response = await apiCall(`/api/projects/${Number(project.id)}`, {
        method: 'DELETE',
    });
    if (!response) return;

    if (typeof getProjectUploadResumeState === 'function') {
        const resume = getProjectUploadResumeState();
        if (resume && Number(resume.project_id) === Number(project.id)) {
            clearProjectUploadResumeState();
        }
    }
    if (typeof projectUpdateTargetId !== 'undefined' && Number(projectUpdateTargetId) === Number(project.id)) {
        cancelProjectFolderUpdate();
    }
    if (typeof activeProjectReportsProjectId !== 'undefined' && Number(activeProjectReportsProjectId) === Number(project.id)) {
        bootstrap.Modal.getInstance(document.getElementById('projectReportsModal'))?.hide();
        activeProjectReportsProjectId = null;
        activeProjectReportsFolderPath = '';
        const url = new URL(window.location.href);
        url.search = '';
        url.hash = 'projects';
        window.history.replaceState({}, '', url);
    }

    const deleted = response.data?.deleted || {};
    alert(
        `Đã xóa dự án “${project.name}”: `
        + `${Number(deleted.assets || 0)} PDF, `
        + `${Number(deleted.submissions || 0)} báo cáo và `
        + `${Number(deleted.submission_review_assignments || 0)} việc kiểm duyệt.`,
    );
    await loadProjectList();
}

function renderProjectMemberEditor(containerId, users, selectedUserIds, className, reportStats = null) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const selected = new Set((selectedUserIds || []).map(Number));
    const showReportStats = Array.isArray(reportStats);
    const statsByUser = new Map(
        (Array.isArray(reportStats) ? reportStats : [])
            .map(item => [Number(item.user_id), item]),
    );
    container.replaceChildren();
    if (!users.length) {
        const empty = document.createElement('span');
        empty.className = 'text-muted';
        empty.textContent = 'Không có tài khoản phù hợp.';
        container.appendChild(empty);
        return;
    }
    users.forEach(user => {
        const wrapper = document.createElement('div');
        wrapper.className = 'form-check';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.className = `form-check-input ${className}`;
        input.value = String(Number(user.id));
        input.id = `${className}-${Number(user.id)}`;
        input.checked = selected.has(Number(user.id));
        const label = document.createElement('label');
        label.className = 'form-check-label';
        label.htmlFor = input.id;
        const name = document.createElement('span');
        name.textContent = `${user.username}${user.role === 'admin' ? ' (Admin)' : ''}`;
        label.appendChild(name);
        if (showReportStats) {
            const stats = statsByUser.get(Number(user.id)) || {};
            const details = document.createElement('small');
            details.className = 'd-block text-muted';
            details.textContent = [
                `Lỗi ${Number(stats.error_reports || 0)}`,
                `Chờ duyệt ${Number(stats.pending_review_reports || 0)}`,
                `Tổng ${Number(stats.total_reports || 0)}`,
            ].join(' / ');
            label.appendChild(details);
        }
        wrapper.append(input, label);
        container.appendChild(wrapper);
    });
}

function openProjectMembers(projectId) {
    const project = projectManagementProjects.find(item => Number(item.id) === Number(projectId));
    if (!project) return alert('Không tìm thấy dự án trong danh sách hiện tại.');
    document.getElementById('projectMembersProjectId').value = String(project.id);
    document.getElementById('projectMembersModalTitle').textContent = project.name;
    renderProjectMemberEditor(
        'projectMembersInputList',
        projectManagementUsers.filter(user => user.role !== 'admin'),
        project.input_user_ids,
        'project-member-input',
        project.member_report_stats,
    );
    renderProjectMemberEditor(
        'projectMembersReviewerList',
        projectManagementUsers,
        project.reviewer_user_ids,
        'project-member-reviewer',
    );
    new bootstrap.Modal(document.getElementById('projectMembersModal')).show();
}

function checkedMemberEditorIds(className) {
    return Array.from(document.querySelectorAll(`.${className}:checked`))
        .map(input => Number(input.value))
        .filter(Number.isInteger);
}

function formatProjectMemberDistribution(rows) {
    return (rows || []).map(row => {
        const user = projectManagementUsers.find(item => Number(item.id) === Number(row.user_id));
        const username = user?.username || `#${Number(row.user_id)}`;
        return `${username}: ${Number(row.case_count || 0)} folder / ${Number(row.pdf_count || 0)} PDF`;
    }).join('\n');
}

async function saveProjectMembers() {
    const projectId = Number(document.getElementById('projectMembersProjectId')?.value || 0);
    if (!projectId) return;
    if (!confirm('Lưu nhân sự và tự động phân chia lại phần nhập, kiểm tra theo danh sách mới?')) return;
    const button = document.getElementById('saveProjectMembersButton');
    if (button) button.disabled = true;
    try {
        const response = await apiCall(`/api/projects/${projectId}/members`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                input_user_ids: checkedMemberEditorIds('project-member-input'),
                reviewer_user_ids: checkedMemberEditorIds('project-member-reviewer'),
            }),
        });
        if (!response) return;
        const result = response.data || {};
        alert(
            `Đã lưu và phân chia lại.\n\nNgười nhập:\n${formatProjectMemberDistribution(result.input_distribution) || 'Chưa có nhân sự'}\n\n`
            + `Người kiểm tra:\n${formatProjectMemberDistribution(result.reviewer_distribution) || 'Chưa có nhân sự'}\n\n`
            + `Đã chuyển ${result.input_cases_transferred || 0} folder nhập và ${result.reviewer_cases_transferred || 0} folder kiểm tra.`,
        );
        bootstrap.Modal.getInstance(document.getElementById('projectMembersModal'))?.hide();
        await loadProjectList();
    } finally {
        if (button) button.disabled = false;
    }
}

function formatProjectAssetSize(byteSize) {
    const size = Number(byteSize || 0);
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

async function openProjectAssets(projectId) {
    const project = projectManagementProjects.find(item => Number(item.id) === Number(projectId));
    if (!project) return alert('Không tìm thấy dự án trong danh sách hiện tại.');
    document.getElementById('projectAssetsProjectId').value = String(project.id);
    document.getElementById('projectAssetsModalTitle').textContent = project.name;
    const body = document.getElementById('projectAssetsTableBody');
    body.innerHTML = `
        <tr class="skeleton-table-row">
            <td><div class="skeleton-loader skeleton-text"></div></td>
            <td><div class="skeleton-loader skeleton-text"></div></td>
            <td><div class="skeleton-loader skeleton-text"></div></td>
            <td><div class="skeleton-loader skeleton-text"></div></td>
            <td><div class="skeleton-loader skeleton-text"></div></td>
            <td><div class="skeleton-loader skeleton-text"></div></td>
        </tr>
        <tr class="skeleton-table-row">
            <td><div class="skeleton-loader skeleton-text"></div></td>
            <td><div class="skeleton-loader skeleton-text"></div></td>
            <td><div class="skeleton-loader skeleton-text"></div></td>
            <td><div class="skeleton-loader skeleton-text"></div></td>
            <td><div class="skeleton-loader skeleton-text"></div></td>
            <td><div class="skeleton-loader skeleton-text"></div></td>
        </tr>`;
    bootstrap.Modal.getOrCreateInstance(document.getElementById('projectAssetsModal')).show();
    const response = await apiCall(`/api/projects/${project.id}/assets`, { cache: 'no-store' });
    if (!response) return;
    body.replaceChildren();
    if (!response.data.length) {
        body.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Dự án chưa có PDF hoạt động.</td></tr>';
        return;
    }
    response.data.forEach(asset => {
        const row = document.createElement('tr');
        appendProjectCell(row, asset.relative_path, 'text-break');
        appendProjectCell(row, asset.case_name || '');
        appendProjectCell(row, asset.report_name || '');
        appendProjectCell(row, formatProjectAssetSize(asset.byte_size));
        appendProjectCell(row, String(asset.submission_count || 0));
        const actionCell = appendProjectCell(row, '');
        const deleteButton = document.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'btn btn-sm btn-danger';
        deleteButton.innerHTML = '<i class="fas fa-trash"></i> Xóa PDF';
        deleteButton.disabled = Number(asset.submission_count || 0) > 0;
        deleteButton.title = deleteButton.disabled
            ? 'PDF đã có dữ liệu nhập nên không thể xóa'
            : 'Xóa cứng PDF lỗi khỏi dự án';
        deleteButton.addEventListener('click', () => deleteProjectAsset(project.id, asset.id, asset.relative_path));
        actionCell.appendChild(deleteButton);
        body.appendChild(row);
    });
}

async function deleteProjectAsset(projectId, assetId, relativePath) {
    if (!confirm(`Xóa cứng PDF “${relativePath}”? File chỉ xuất hiện lại khi admin chọn lại folder và cập nhật dự án.`)) return;
    const response = await apiCall(`/api/projects/${Number(projectId)}/assets/${Number(assetId)}`, {
        method: 'DELETE',
    });
    if (!response) return;
    alert('Đã xóa PDF và lưu nhật ký thao tác.');
    await openProjectAssets(projectId);
    await loadProjectList();
}

async function initializeProjectManagement() {
    if (!projectManagementLoaded) {
        projectManagementLoaded = true;
        await loadProjectFormOptions();
        if (typeof syncProjectReportMode === 'function') syncProjectReportMode();
    }
    await loadProjectList();
}

function checkedProjectUserIds(className) {
    return Array.from(document.querySelectorAll(`.${className}:checked`))
        .map(input => Number(input.value))
        .filter(Number.isInteger);
}
