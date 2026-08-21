let projectManagementLoaded = false;
let selectedProjectFileRows = [];
let selectedProjectRootName = '';
let selectedProjectMaximumDepth = 0;
let projectManagementUsers = [];
let projectManagementProjects = [];
let projectUpdateTargetId = null;
let activeProjectReportsProjectId = null;
let activeProjectReportsView = 'review';
let activeProjectReportsFolderPath = '';
let activeProjectReportsPage = 1;

function setProjectUploadStatus(message, tone = 'muted') {
    const status = document.getElementById('projectUploadStatus');
    if (!status) return;
    status.textContent = message || '';
    status.className = `small mt-3 text-${tone}`;
}

function setProjectUploadProgress(done, total) {
    const wrapper = document.getElementById('projectUploadProgressWrap');
    const bar = document.getElementById('projectUploadProgress');
    if (!wrapper || !bar) return;
    wrapper.classList.remove('d-none');
    const percent = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
    bar.style.width = `${percent}%`;
    bar.textContent = `${percent}%`;
    bar.setAttribute('aria-valuenow', String(percent));
}

function projectRelativeFileRow(file) {
    const browserPath = String(file.webkitRelativePath || file.name || '').replace(/\\/g, '/');
    const parts = browserPath.split('/').filter(Boolean);
    const rootName = parts.length > 1 ? parts[0] : '';
    const relativeParts = parts.length > 1 ? parts.slice(1) : parts;
    return {
        file,
        rootName,
        relativePath: relativeParts.join('/'),
        folderDepth: Math.max(0, relativeParts.length - 1),
    };
}

function handleProjectFolderSelection() {
    const picker = document.getElementById('projectFolderPicker');
    const summary = document.getElementById('projectFolderSummary');
    const rows = Array.from((picker && picker.files) || [])
        .filter(file => String(file.name || '').toLocaleLowerCase('vi-VN').endsWith('.pdf'))
        .map(projectRelativeFileRow);
    selectedProjectFileRows = rows;
    selectedProjectRootName = rows[0] ? rows[0].rootName : '';
    selectedProjectMaximumDepth = rows.reduce((maximum, row) => Math.max(maximum, row.folderDepth), 0);

    if (!rows.length) {
        if (summary) summary.textContent = 'Folder không có PDF.';
        updateProjectLevelOptions();
        return;
    }
    const roots = new Set(rows.map(row => row.rootName));
    if (roots.size !== 1 || !selectedProjectRootName) {
        selectedProjectFileRows = [];
        if (summary) summary.textContent = 'Không xác định được một folder gốc duy nhất.';
        updateProjectLevelOptions();
        return;
    }
    const nameInput = document.getElementById('projectNameInput');
    if (nameInput && !nameInput.value.trim()) nameInput.value = selectedProjectRootName;
    if (summary) {
        summary.textContent = `${rows.length.toLocaleString('vi-VN')} PDF; ${selectedProjectMaximumDepth} cấp folder bên dưới “${selectedProjectRootName}”.`;
    }
    updateProjectLevelOptions();
    const resume = getProjectUploadResumeState();
    if (resume && resume.root_name === selectedProjectRootName) {
        setProjectUploadStatus(`Đã tìm thấy phiên tải dở của dự án #${resume.project_id}; bấm nút để tiếp tục.`, 'warning');
    }
}

function updateProjectLevelOptions() {
    const caseSelect = document.getElementById('projectCaseLevel');
    const reportSelect = document.getElementById('projectReportLevel');
    if (!caseSelect || !reportSelect) return;
    const previousCase = Number(caseSelect.value || 0);
    caseSelect.replaceChildren();
    if (selectedProjectMaximumDepth < 1) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = 'Folder cần ít nhất 1 cấp hồ sơ';
        caseSelect.appendChild(option);
    } else {
        for (let level = 1; level <= selectedProjectMaximumDepth; level += 1) {
            const option = document.createElement('option');
            option.value = String(level);
            option.textContent = `Cấp ${level}`;
            caseSelect.appendChild(option);
        }
        caseSelect.value = String(
            previousCase >= 1 && previousCase <= selectedProjectMaximumDepth ? previousCase : 1,
        );
    }

    const caseLevel = Number(caseSelect.value || 0);
    reportSelect.replaceChildren();
    for (let level = caseLevel + 1; level <= selectedProjectMaximumDepth; level += 1) {
        const option = document.createElement('option');
        option.value = String(level);
        option.textContent = `Cấp ${level}`;
        reportSelect.appendChild(option);
    }
    if (!reportSelect.options.length) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = 'Không còn cấp folder sâu hơn';
        reportSelect.appendChild(option);
    }
    syncProjectReportMode();
}

function syncProjectReportMode() {
    const mode = document.getElementById('projectReportMode');
    const group = document.getElementById('projectReportLevelGroup');
    const reportSelect = document.getElementById('projectReportLevel');
    const folderMode = !mode || mode.value === 'folder_level';
    if (group) group.classList.toggle('d-none', !folderMode);
    if (reportSelect) reportSelect.disabled = !folderMode;
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

function appendProjectCell(row, text, className = '') {
    const cell = document.createElement('td');
    cell.className = className;
    cell.textContent = text;
    row.appendChild(cell);
    return cell;
}

async function loadProjectList() {
    const body = document.getElementById('projectListBody');
    if (body) body.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Đang tải...</td></tr>';
    const data = await apiCall('/api/projects', { cache: 'no-store' });
    if (!data || !body) return;
    projectManagementProjects = Array.isArray(data.data) ? data.data : [];
    body.replaceChildren();
    if (!projectManagementProjects.length) {
        body.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Chưa có dự án.</td></tr>';
        return;
    }
    projectManagementProjects.forEach(project => {
        const metrics = project.metrics || {};
        const row = document.createElement('tr');
        const nameCell = appendProjectCell(row, '');
        const strong = document.createElement('strong');
        strong.textContent = project.name;
        const detail = document.createElement('div');
        detail.className = 'text-muted';
        detail.textContent = project.template_name;
        nameCell.append(strong, detail);
        appendProjectCell(
            row,
            `Nhập ${metrics.input_assigned_cases || 0}/${metrics.total_cases || 0}; kiểm ${metrics.reviewer_assigned_cases || 0}/${metrics.total_cases || 0}`,
        );
        appendProjectCell(row, `${metrics.total_pdfs || 0} (lỗi ${metrics.error_pdfs || 0})`);
        appendProjectCell(row, `${metrics.entered_reports || 0}/${metrics.required_reports || 0}`);
        appendProjectCell(row, `${metrics.approved_reports || 0}/${metrics.entered_reports || 0}`);
        const statusCell = appendProjectCell(row, project.status || '');
        statusCell.classList.add(project.status === 'ready' ? 'text-success' : 'text-warning');
        const actionCell = appendProjectCell(row, '');
        actionCell.className = 'text-nowrap';
        const membersButton = document.createElement('button');
        membersButton.type = 'button';
        membersButton.className = 'btn btn-sm btn-outline-primary me-1';
        membersButton.innerHTML = '<i class="fas fa-users"></i> Nhân sự';
        membersButton.addEventListener('click', () => openProjectMembers(project.id));
        const updateButton = document.createElement('button');
        updateButton.type = 'button';
        updateButton.className = 'btn btn-sm btn-outline-warning me-1';
        updateButton.innerHTML = '<i class="fas fa-sync-alt"></i> Cập nhật PDF';
        updateButton.addEventListener('click', () => prepareProjectFolderUpdate(project.id));
        const assetsButton = document.createElement('button');
        assetsButton.type = 'button';
        assetsButton.className = 'btn btn-sm btn-outline-danger';
        assetsButton.innerHTML = '<i class="fas fa-file-pdf"></i> PDF';
        assetsButton.addEventListener('click', () => openProjectAssets(project.id));
        const reportActions = document.createElement('div');
        reportActions.className = 'dropdown d-inline-block ms-1';
        const reportActionsButton = document.createElement('button');
        reportActionsButton.type = 'button';
        reportActionsButton.className = 'btn btn-sm btn-success dropdown-toggle';
        reportActionsButton.dataset.bsToggle = 'dropdown';
        reportActionsButton.setAttribute('aria-expanded', 'false');
        reportActionsButton.innerHTML = '<i class="fas fa-folder-open"></i> Hồ sơ / Xuất';
        const reportActionsMenu = document.createElement('ul');
        reportActionsMenu.className = 'dropdown-menu dropdown-menu-end';
        const appendAction = (label, icon, handler, className = '') => {
            const item = document.createElement('li');
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `dropdown-item ${className}`.trim();
            button.innerHTML = `<i class="fas ${icon} me-2"></i>${label}`;
            button.addEventListener('click', handler);
            item.appendChild(button);
            reportActionsMenu.appendChild(item);
            return button;
        };
        appendAction(
            'Xem kiểm duyệt hồ sơ',
            'fa-search',
            () => openProjectReports(project.id, 'review'),
        );
        appendAction(
            'Xem hồ sơ hoàn chỉnh',
            'fa-check-circle',
            () => openProjectReports(project.id, 'completed'),
        );
        const divider = document.createElement('li');
        divider.innerHTML = '<hr class="dropdown-divider">';
        reportActionsMenu.appendChild(divider);
        const completedExportButton = appendAction(
            'Xuất hồ sơ hoàn chỉnh',
            'fa-file-export',
            () => exportProjectReports(project.id, false),
        );
        completedExportButton.dataset.projectExportId = String(project.id);
        const allExportButton = appendAction(
            'Xuất toàn bộ',
            'fa-file-export',
            () => exportProjectReports(project.id, true),
            'fw-bold',
        );
        allExportButton.dataset.projectExportId = String(project.id);
        const deleteDivider = document.createElement('li');
        deleteDivider.innerHTML = '<hr class="dropdown-divider">';
        reportActionsMenu.appendChild(deleteDivider);
        appendAction(
            'Xóa dự án',
            'fa-trash',
            () => deleteProject(project),
            'text-danger fw-bold',
        );
        reportActions.append(reportActionsButton, reportActionsMenu);
        actionCell.append(membersButton, updateButton, assetsButton, reportActions);
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

    const resume = getProjectUploadResumeState();
    if (resume && Number(resume.project_id) === Number(project.id)) {
        clearProjectUploadResumeState();
    }
    if (Number(projectUpdateTargetId) === Number(project.id)) {
        cancelProjectFolderUpdate();
    }
    if (Number(activeProjectReportsProjectId) === Number(project.id)) {
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

function prepareProjectFolderUpdate(projectId) {
    const project = projectManagementProjects.find(item => Number(item.id) === Number(projectId));
    if (!project) return alert('Không tìm thấy dự án trong danh sách hiện tại.');
    projectUpdateTargetId = Number(project.id);
    clearProjectUploadResumeState();
    selectedProjectFileRows = [];
    selectedProjectRootName = '';
    selectedProjectMaximumDepth = 0;
    const picker = document.getElementById('projectFolderPicker');
    if (picker) picker.value = '';
    const summary = document.getElementById('projectFolderSummary');
    if (summary) summary.textContent = `Chọn lại folder gốc “${project.root_folder_name}”.`;
    const banner = document.getElementById('projectUpdateTargetBanner');
    if (banner) banner.classList.remove('d-none');
    const name = document.getElementById('projectUpdateTargetName');
    if (name) name.textContent = project.name;
    const buttonText = document.getElementById('createProjectButtonText');
    if (buttonText) buttonText.textContent = 'Cập nhật PDF cho dự án đã chọn';
    setProjectUploadStatus('Chọn lại folder để đối chiếu manifest với dữ liệu hiện có.', 'warning');
    document.getElementById('projects-pane')?.scrollIntoView({behavior: 'smooth', block: 'start'});
    if (picker) picker.click();
}

function cancelProjectFolderUpdate() {
    projectUpdateTargetId = null;
    clearProjectUploadResumeState();
    const banner = document.getElementById('projectUpdateTargetBanner');
    if (banner) banner.classList.add('d-none');
    const buttonText = document.getElementById('createProjectButtonText');
    if (buttonText) buttonText.textContent = 'Tạo dự án và tải PDF';
    setProjectUploadStatus('');
}

function renderProjectMemberEditor(containerId, users, selectedUserIds, className) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const selected = new Set((selectedUserIds || []).map(Number));
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
        label.textContent = `${user.username}${user.role === 'admin' ? ' (Admin)' : ''}`;
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

async function saveProjectMembers() {
    const projectId = Number(document.getElementById('projectMembersProjectId')?.value || 0);
    if (!projectId) return;
    if (!confirm('Lưu danh sách nhân sự và tự động chuyển nguyên hồ sơ của những người bị gỡ?')) return;
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
            `Đã cập nhật. Chuyển ${result.input_cases_transferred || 0} hồ sơ nhập, `
            + `${result.reviewer_cases_transferred || 0} hồ sơ kiểm và ${result.submissions_transferred || 0} báo cáo.`,
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
    body.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Đang tải...</td></tr>';
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

function setProjectExportStatus(message, isError = false) {
    const status = document.getElementById('projectExportStatus');
    if (!status) return;
    status.textContent = message || '';
    status.className = `small mt-2 ${isError ? 'text-danger' : 'text-muted'}`;
}

function setProjectReportsTableMessage(message) {
    const body = document.getElementById('projectReportsTableBody');
    if (!body) return;
    body.innerHTML = '';
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 7;
    cell.className = 'text-center text-muted py-4';
    cell.textContent = message;
    row.appendChild(cell);
    body.appendChild(row);
}

function projectReportEditorUrl(submissionId) {
    const params = new URLSearchParams({
        check_id: String(Number(submissionId)),
        return_to: activeProjectReportsView === 'review' ? 'project_review' : 'project_completed',
        return_project: String(activeProjectReportsProjectId),
    });
    if (activeProjectReportsFolderPath) {
        params.set('return_folder', activeProjectReportsFolderPath);
    }
    return `index.html?${params.toString()}`;
}

function updateProjectReportsUrl() {
    if (!window.history || !activeProjectReportsProjectId) return;
    const url = new URL(window.location.href);
    url.search = '';
    url.searchParams.set('project_id', String(activeProjectReportsProjectId));
    url.searchParams.set('project_view', activeProjectReportsView);
    if (activeProjectReportsFolderPath) {
        url.searchParams.set('return_folder', activeProjectReportsFolderPath);
    }
    url.hash = 'projects';
    window.history.replaceState({}, '', url);
}

function renderProjectReportPagination(pagination) {
    const container = document.getElementById('projectReportsPagination');
    if (!container) return;
    container.replaceChildren();
    const page = Number(pagination?.page || 1);
    const totalPages = Number(pagination?.total_pages || 1);
    const total = Number(pagination?.total || 0);
    const summary = document.createElement('span');
    summary.className = 'small text-muted me-2';
    summary.textContent = `${total.toLocaleString('vi-VN')} hồ sơ · Trang ${page}/${totalPages}`;
    container.appendChild(summary);
    for (const [label, nextPage, disabled] of [
        ['‹ Trước', page - 1, page <= 1],
        ['Sau ›', page + 1, page >= totalPages],
    ]) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-sm btn-outline-secondary';
        button.textContent = label;
        button.disabled = disabled;
        button.addEventListener('click', () => selectProjectReportsFolder(
            activeProjectReportsFolderPath,
            nextPage,
        ));
        container.appendChild(button);
    }
}

function renderProjectReportRows(items, pagination) {
    const body = document.getElementById('projectReportsTableBody');
    if (!body) return;
    body.replaceChildren();
    if (!items.length) {
        setProjectReportsTableMessage('Folder không có hồ sơ ở trạng thái này.');
        renderProjectReportPagination(pagination);
        return;
    }
    items.forEach(item => {
        const row = document.createElement('tr');
        if (item.has_errors || item.status === 'rejected') row.classList.add('table-danger');
        appendProjectCell(row, String(Number(item.serial_number) || ''), 'text-center fw-semibold');
        appendProjectCell(row, item.template || '');
        appendProjectCell(row, item.created_at || '', 'text-nowrap');

        const pdfCell = appendProjectCell(row, '', 'text-break');
        const pdfPath = item.pdf_relative_path || item.pdf_filename || '';
        if (pdfPath) {
            const link = document.createElement('a');
            link.href = projectReportEditorUrl(item.id);
            if (activeProjectReportsView === 'completed') link.target = '_blank';
            link.title = pdfPath;
            const icon = document.createElement('i');
            icon.className = 'fas fa-file-pdf text-danger me-1';
            link.append(icon, document.createTextNode(pdfPath));
            pdfCell.appendChild(link);
        } else {
            pdfCell.textContent = 'Không liên kết PDF';
            pdfCell.classList.add('text-muted', 'fst-italic');
        }
        appendProjectCell(row, item.creator_name || '');

        const statusCell = appendProjectCell(row, '', 'text-center');
        const badge = document.createElement('span');
        badge.className = item.status === 'approved'
            ? 'badge bg-success'
            : item.status === 'rejected'
                ? 'badge bg-danger'
                : 'badge bg-warning text-dark';
        badge.textContent = item.status === 'approved'
            ? 'Đã duyệt'
            : item.status === 'rejected'
                ? 'Báo lỗi'
                : 'Chờ duyệt';
        statusCell.appendChild(badge);
        if (item.viewer) {
            const viewer = document.createElement('span');
            viewer.className = 'badge bg-info text-dark ms-1';
            viewer.textContent = `Đang xem: ${item.viewer.username || 'Người dùng khác'}`;
            statusCell.appendChild(viewer);
        }

        const actionCell = appendProjectCell(row, '');
        actionCell.className = 'text-nowrap';
        const openButton = document.createElement('a');
        openButton.className = 'btn btn-sm btn-outline-primary me-1';
        openButton.href = projectReportEditorUrl(item.id);
        if (activeProjectReportsView === 'completed') openButton.target = '_blank';
        openButton.innerHTML = '<i class="fas fa-search"></i> Mở';
        actionCell.appendChild(openButton);
        if (activeProjectReportsView === 'review') {
            const approveButton = document.createElement('button');
            approveButton.type = 'button';
            approveButton.className = 'btn btn-sm btn-success me-1';
            approveButton.innerHTML = '<i class="fas fa-check"></i> Duyệt';
            approveButton.addEventListener('click', () => approveProjectSubmission(item.id));
            actionCell.appendChild(approveButton);
        } else {
            const reopenButton = document.createElement('button');
            reopenButton.type = 'button';
            reopenButton.className = 'btn btn-sm btn-outline-warning me-1';
            reopenButton.innerHTML = '<i class="fas fa-undo"></i> Về chờ duyệt';
            reopenButton.addEventListener('click', () => reopenProjectSubmission(item.id));
            actionCell.appendChild(reopenButton);
        }
        const deleteButton = document.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'btn btn-sm btn-outline-danger';
        deleteButton.innerHTML = '<i class="fas fa-trash"></i>';
        deleteButton.title = 'Xóa hồ sơ';
        deleteButton.addEventListener('click', () => deleteProjectSubmission(item.id));
        actionCell.appendChild(deleteButton);
        body.appendChild(row);
    });
    renderProjectReportPagination(pagination);
}

async function selectProjectReportsFolder(folderPath, page = 1) {
    if (!activeProjectReportsProjectId) return;
    activeProjectReportsFolderPath = folderPath || '';
    activeProjectReportsPage = Number(page) || 1;
    document.querySelectorAll('#projectReportsFolderTree [data-folder-path]').forEach(button => {
        button.classList.toggle('active', button.dataset.folderPath === activeProjectReportsFolderPath);
    });
    const title = document.getElementById('projectReportsFolderTitle');
    if (title) title.textContent = activeProjectReportsFolderPath || 'Tất cả folder';
    setProjectReportsTableMessage('Đang tải hồ sơ...');
    const params = new URLSearchParams({
        view: activeProjectReportsView,
        page: String(activeProjectReportsPage),
        page_size: '20',
    });
    if (activeProjectReportsFolderPath) params.set('folder_path', activeProjectReportsFolderPath);
    const response = await apiCall(
        `/api/projects/${activeProjectReportsProjectId}/submissions?${params.toString()}`,
        {cache: 'no-store'},
    );
    if (!response) return;
    const payload = response.data || {};
    activeProjectReportsPage = Number(payload.pagination?.page || 1);
    renderProjectReportRows(Array.isArray(payload.data) ? payload.data : [], payload.pagination || {});
    updateProjectReportsUrl();
}

async function openProjectReports(projectId, view, preferredFolderPath = '') {
    const project = projectManagementProjects.find(item => Number(item.id) === Number(projectId));
    if (!project) return alert('Không tìm thấy dự án trong danh sách hiện tại.');
    activeProjectReportsProjectId = Number(project.id);
    activeProjectReportsView = view === 'completed' ? 'completed' : 'review';
    activeProjectReportsFolderPath = preferredFolderPath || '';
    activeProjectReportsPage = 1;
    document.getElementById('projectReportsProjectTitle').textContent = project.name;
    document.getElementById('projectReportsViewTitle').textContent = activeProjectReportsView === 'review'
        ? 'Kiểm duyệt hồ sơ'
        : 'Hồ sơ hoàn chỉnh';
    const tree = document.getElementById('projectReportsFolderTree');
    tree.innerHTML = '<div class="text-center text-muted p-3">Đang tải folder...</div>';
    setProjectReportsTableMessage('Chọn một folder để xem hồ sơ.');
    bootstrap.Modal.getOrCreateInstance(document.getElementById('projectReportsModal')).show();

    const params = new URLSearchParams({view: activeProjectReportsView});
    const response = await apiCall(
        `/api/projects/${activeProjectReportsProjectId}/submission-folders?${params.toString()}`,
        {cache: 'no-store'},
    );
    if (!response) return;
    const folders = Array.isArray(response.data?.folders) ? response.data.folders.slice() : [];
    folders.sort((left, right) => String(left.folder_path || '').localeCompare(
        String(right.folder_path || ''),
        'vi',
        {sensitivity: 'base'},
    ));
    tree.replaceChildren();
    if (!folders.length) {
        const empty = document.createElement('div');
        empty.className = 'text-center text-muted p-3';
        empty.textContent = activeProjectReportsView === 'review'
            ? 'Dự án không có hồ sơ chờ kiểm duyệt.'
            : 'Dự án chưa có hồ sơ hoàn chỉnh.';
        tree.appendChild(empty);
        setProjectReportsTableMessage(empty.textContent);
        renderProjectReportPagination({page: 1, total_pages: 1, total: 0});
        updateProjectReportsUrl();
        return;
    }
    folders.forEach(folder => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'list-group-item list-group-item-action text-start';
        button.dataset.folderPath = folder.folder_path;
        const path = document.createElement('div');
        path.className = 'fw-semibold text-break';
        path.textContent = folder.folder_path;
        const count = document.createElement('small');
        count.className = 'text-muted';
        count.textContent = `${Number(folder.submission_count || 0).toLocaleString('vi-VN')} hồ sơ`;
        button.append(path, count);
        button.addEventListener('click', () => selectProjectReportsFolder(folder.folder_path, 1));
        tree.appendChild(button);
    });
    const selectedFolder = folders.some(folder => folder.folder_path === preferredFolderPath)
        ? preferredFolderPath
        : folders[0].folder_path;
    await selectProjectReportsFolder(selectedFolder, 1);
}

async function reloadProjectReports() {
    if (!activeProjectReportsProjectId) return;
    await openProjectReports(
        activeProjectReportsProjectId,
        activeProjectReportsView,
        activeProjectReportsFolderPath,
    );
}

async function approveProjectSubmission(submissionId) {
    const response = await apiCall(`/api/submissions/${Number(submissionId)}/toggle_check`, {method: 'PUT'});
    if (!response || response.status !== 'ok') return;
    await Promise.all([reloadProjectReports(), loadProjectList()]);
}

async function reopenProjectSubmission(submissionId) {
    if (!confirm('Chuyển hồ sơ đã duyệt này về trạng thái Chờ duyệt?')) return;
    const response = await apiCall(`/api/submissions/${Number(submissionId)}/reopen-review`, {method: 'PUT'});
    if (!response || response.status !== 'ok') return;
    await Promise.all([reloadProjectReports(), loadProjectList()]);
}

async function deleteProjectSubmission(submissionId) {
    if (!confirm('Bạn có chắc muốn xóa hồ sơ này?')) return;
    const response = await apiCall(`/api/submissions/${Number(submissionId)}`, {method: 'DELETE'});
    if (!response) return;
    await Promise.all([reloadProjectReports(), loadProjectList()]);
}

async function exportProjectReports(projectId, includePendingReview) {
    const project = projectManagementProjects.find(item => Number(item.id) === Number(projectId));
    if (!project) return alert('Không tìm thấy dự án trong danh sách hiện tại.');
    const exportLabel = includePendingReview ? 'toàn bộ hồ sơ' : 'hồ sơ hoàn chỉnh';
    if (!confirm(`Xuất ${exportLabel} của dự án “${project.name}”?`)) return;
    const buttons = document.querySelectorAll(`[data-project-export-id="${Number(project.id)}"]`);
    buttons.forEach(button => { button.disabled = true; });
    setProjectExportStatus(`Đang khởi tạo tác vụ xuất ${exportLabel} của “${project.name}”...`);
    try {
        const params = new URLSearchParams();
        if (includePendingReview) params.set('include_pending_review', 'true');
        const createResponse = await authFetch(
            `/api/projects/${project.id}/export-jobs?${params.toString()}`,
            {method: 'POST'},
        );
        if (!createResponse) return;
        const createData = await createResponse.json().catch(() => ({}));
        if (!createResponse.ok) {
            throw new Error(formatApiErrorDetail(createData.detail || createData.message));
        }
        const jobId = createData.job?.job_id;
        if (!jobId) throw new Error('Máy chủ không trả về mã tác vụ xuất');
        const deadline = Date.now() + 60 * 60 * 1000;
        while (Date.now() < deadline) {
            await new Promise(resolve => setTimeout(resolve, 2000));
            const statusResponse = await authFetch(`/api/export-jobs/${jobId}`, {cache: 'no-store'});
            if (!statusResponse) return;
            const statusData = await statusResponse.json().catch(() => ({}));
            if (!statusResponse.ok) {
                throw new Error(formatApiErrorDetail(statusData.detail || statusData.message));
            }
            const job = statusData.job || {};
            setProjectExportStatus(job.message || 'Đang tạo file Excel...');
            if (job.state === 'error') throw new Error(job.message || 'Tác vụ xuất thất bại');
            if (job.state !== 'completed') continue;
            const downloadResponse = await authFetch(`/api/export-jobs/${jobId}/download`);
            if (!downloadResponse) return;
            if (!downloadResponse.ok) {
                const errorData = await downloadResponse.json().catch(() => ({}));
                throw new Error(formatApiErrorDetail(errorData.detail || errorData.message));
            }
            await downloadExportResponse(
                downloadResponse,
                job.filename || `DuAn_${project.id}.xlsx`,
            );
            setProjectExportStatus(
                `Đã tải ${Number(job.rows_total || 0).toLocaleString('vi-VN')} hồ sơ của “${project.name}”.`,
            );
            return;
        }
        throw new Error('Tác vụ xuất quá 60 phút chưa hoàn tất');
    } catch (error) {
        setProjectExportStatus(error.message, true);
        alert(`Lỗi xuất báo cáo: ${error.message}`);
    } finally {
        buttons.forEach(button => { button.disabled = false; });
    }
}

async function restoreProjectManagementNavigation() {
    if (window.location.hash !== '#projects') return false;
    const params = new URLSearchParams(window.location.search);
    const projectId = Number(params.get('project_id'));
    const view = params.get('project_view');
    if (!Number.isInteger(projectId) || projectId <= 0 || !['review', 'completed'].includes(view)) {
        return false;
    }
    await openProjectReports(projectId, view, params.get('return_folder') || '');
    return true;
}

async function initializeProjectManagement() {
    if (!projectManagementLoaded) {
        projectManagementLoaded = true;
        await loadProjectFormOptions();
        syncProjectReportMode();
    }
    await loadProjectList();
}

function checkedProjectUserIds(className) {
    return Array.from(document.querySelectorAll(`.${className}:checked`))
        .map(input => Number(input.value))
        .filter(Number.isInteger);
}

async function sha256ProjectFile(file) {
    const buffer = await file.arrayBuffer();
    const digest = await crypto.subtle.digest('SHA-256', buffer);
    return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
}

async function buildProjectManifest() {
    const manifest = [];
    for (let index = 0; index < selectedProjectFileRows.length; index += 1) {
        const row = selectedProjectFileRows[index];
        setProjectUploadStatus(`Đang kiểm tra SHA-256: ${index + 1}/${selectedProjectFileRows.length}`);
        setProjectUploadProgress(index, selectedProjectFileRows.length);
        manifest.push({
            relative_path: row.relativePath,
            size: row.file.size,
            sha256: await sha256ProjectFile(row.file),
            last_modified: String(row.file.lastModified || ''),
        });
    }
    setProjectUploadProgress(selectedProjectFileRows.length, selectedProjectFileRows.length);
    return manifest;
}

function projectUploadResumeStorageKey() {
    return 'projectUploadResumeV1';
}

function getProjectUploadResumeState() {
    try {
        return JSON.parse(localStorage.getItem(projectUploadResumeStorageKey()) || 'null');
    } catch (_) {
        return null;
    }
}

function saveProjectUploadResumeState(state) {
    localStorage.setItem(projectUploadResumeStorageKey(), JSON.stringify(state));
}

function clearProjectUploadResumeState() {
    localStorage.removeItem(projectUploadResumeStorageKey());
}

async function uploadOneProjectFile(session, fileInfo, fileByPath, progressState) {
    const file = fileByPath.get(String(fileInfo.relative_path).toLocaleLowerCase('vi-VN'));
    if (!file) throw new Error(`Không tìm thấy file đã chọn: ${fileInfo.relative_path}`);
    let offset = Number(fileInfo.next_offset || 0);
    while (offset < file.size) {
        const chunk = file.slice(offset, Math.min(file.size, offset + session.chunk_size_bytes));
        let responseData = null;
        let lastError = null;
        for (let attempt = 1; attempt <= 3; attempt += 1) {
            try {
                const response = await authFetch(
                    `/api/project-upload-sessions/${encodeURIComponent(session.id)}/files/${Number(fileInfo.file_id)}`,
                    {
                        method: 'PUT',
                        headers: {'X-Upload-Offset': String(offset)},
                        body: chunk,
                    },
                );
                if (!response) throw new Error('Phiên đăng nhập đã hết hạn');
                responseData = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(formatApiErrorDetail(responseData.detail || responseData.message));
                }
                break;
            } catch (error) {
                lastError = error;
                if (attempt < 3) await new Promise(resolve => setTimeout(resolve, attempt * 500));
            }
        }
        if (!responseData || responseData.status !== 'ok') throw lastError || new Error('Không tải được chunk');
        const nextOffset = Number(responseData.next_offset);
        if (!Number.isFinite(nextOffset) || nextOffset <= offset) throw new Error('Máy chủ trả offset không hợp lệ');
        progressState.doneBytes += nextOffset - offset;
        offset = nextOffset;
        setProjectUploadProgress(progressState.doneBytes, progressState.totalBytes);
        setProjectUploadStatus(
            `Đang tải ${progressState.finishedFiles + 1}/${progressState.totalFiles}: ${fileInfo.relative_path}`,
        );
    }
    progressState.finishedFiles += 1;
}

async function uploadProjectSessionFiles(session) {
    const fileByPath = new Map(
        selectedProjectFileRows.map(row => [row.relativePath.toLocaleLowerCase('vi-VN'), row.file]),
    );
    const queue = session.files.filter(item => item.state !== 'uploaded');
    const progressState = {
        doneBytes: session.files.reduce((sum, item) => sum + Number(item.next_offset || 0), 0),
        totalBytes: session.files.reduce((sum, item) => sum + Number(item.size || 0), 0),
        finishedFiles: session.files.filter(item => item.state === 'uploaded').length,
        totalFiles: session.files.length,
    };
    setProjectUploadProgress(progressState.doneBytes, progressState.totalBytes);
    let cursor = 0;
    async function worker() {
        while (cursor < queue.length) {
            const item = queue[cursor];
            cursor += 1;
            await uploadOneProjectFile(session, item, fileByPath, progressState);
        }
    }
    const workerCount = Math.min(Number(session.concurrency || 4), queue.length);
    await Promise.all(Array.from({length: workerCount}, () => worker()));
}

function projectDateValue(elementId) {
    const value = document.getElementById(elementId)?.value;
    return value ? `${value}T00:00:00` : null;
}

async function createAndUploadProject() {
    if (!selectedProjectFileRows.length) return alert('Vui lòng chọn folder có PDF.');
    const updateProject = projectUpdateTargetId
        ? projectManagementProjects.find(project => Number(project.id) === Number(projectUpdateTargetId))
        : null;
    if (projectUpdateTargetId && !updateProject) return alert('Dự án cần cập nhật không còn trong danh sách.');
    if (
        updateProject
        && String(selectedProjectRootName).toLocaleLowerCase('vi-VN')
            !== String(updateProject.root_folder_name).toLocaleLowerCase('vi-VN')
    ) {
        return alert(`Folder đã chọn là “${selectedProjectRootName}”, cần chọn đúng folder “${updateProject.root_folder_name}”.`);
    }
    const templateId = Number(document.getElementById('projectTemplateSelect')?.value || 0);
    const caseLevel = Number(document.getElementById('projectCaseLevel')?.value || 0);
    const reportMode = document.getElementById('projectReportMode')?.value || 'folder_level';
    const reportLevel = reportMode === 'folder_level'
        ? Number(document.getElementById('projectReportLevel')?.value || 0)
        : null;
    if (!updateProject && !templateId) return alert('Vui lòng chọn biểu mẫu.');
    if (!updateProject && !caseLevel) return alert('Vui lòng chọn cấp hồ sơ.');
    if (!updateProject && reportMode === 'folder_level' && (!reportLevel || reportLevel <= caseLevel)) {
        return alert('Cấp báo cáo phải sâu hơn cấp hồ sơ.');
    }

    const button = document.getElementById('createProjectButton');
    if (button) button.disabled = true;
    try {
        const manifest = await buildProjectManifest();
        let resume = getProjectUploadResumeState();
        const targetProjectId = updateProject ? Number(updateProject.id) : null;
        if (
            !resume
            || resume.root_name !== selectedProjectRootName
            || (targetProjectId && Number(resume.project_id) !== targetProjectId)
        ) {
            let projectId = targetProjectId;
            if (!projectId) {
                const created = await apiCall('/api/projects', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        name: document.getElementById('projectNameInput')?.value.trim() || null,
                        root_folder_name: selectedProjectRootName,
                        template_id: templateId,
                        start_date: projectDateValue('projectStartDate'),
                        end_date: projectDateValue('projectEndDate'),
                        case_level: caseLevel,
                        report_mode: reportMode,
                        report_level: reportLevel,
                        input_user_ids: checkedProjectUserIds('project-input-user'),
                        reviewer_user_ids: checkedProjectUserIds('project-reviewer-user'),
                    }),
                });
                if (!created) return;
                projectId = Number(created.project_id);
            }
            resume = {
                project_id: projectId,
                client_session_key: `browser-${crypto.randomUUID()}`,
                root_name: selectedProjectRootName,
            };
            saveProjectUploadResumeState(resume);
        }

        setProjectUploadStatus('Đang đối chiếu manifest với máy chủ...');
        const sessionData = await apiCall(`/api/projects/${resume.project_id}/upload-sessions`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                client_session_key: resume.client_session_key,
                files: manifest,
            }),
        });
        if (!sessionData) return;
        const session = sessionData.session;
        setProjectUploadStatus(
            `Máy chủ yêu cầu tải ${session.requested_files.toLocaleString('vi-VN')}/${session.total_files.toLocaleString('vi-VN')} PDF.`,
        );
        await uploadProjectSessionFiles(session);
        setProjectUploadStatus('Đang hoàn tất và kiểm tra dữ liệu trên máy chủ...');
        const finalized = await apiCall(
            `/api/project-upload-sessions/${encodeURIComponent(session.id)}/finalize`,
            {method: 'POST'},
        );
        if (!finalized) return;
        clearProjectUploadResumeState();
        if (updateProject) cancelProjectFolderUpdate();
        setProjectUploadProgress(1, 1);
        setProjectUploadStatus(
            `Hoàn tất: ${finalized.session.imported_files || 0} PDF mới, ${finalized.session.reused_files || 0} PDF đã có.`,
            'success',
        );
        await loadProjectList();
    } catch (error) {
        setProjectUploadStatus(`Tạm dừng: ${error.message}. Chọn lại cùng folder để tiếp tục.`, 'danger');
    } finally {
        if (button) button.disabled = false;
    }
}
