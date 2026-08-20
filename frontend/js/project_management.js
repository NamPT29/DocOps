let projectManagementLoaded = false;
let selectedProjectFileRows = [];
let selectedProjectRootName = '';
let selectedProjectMaximumDepth = 0;
let projectManagementUsers = [];
let projectManagementProjects = [];

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
        const assetsButton = document.createElement('button');
        assetsButton.type = 'button';
        assetsButton.className = 'btn btn-sm btn-outline-danger';
        assetsButton.innerHTML = '<i class="fas fa-file-pdf"></i> PDF';
        assetsButton.addEventListener('click', () => openProjectAssets(project.id));
        actionCell.append(membersButton, assetsButton);
        body.appendChild(row);
    });
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
    const templateId = Number(document.getElementById('projectTemplateSelect')?.value || 0);
    const caseLevel = Number(document.getElementById('projectCaseLevel')?.value || 0);
    const reportMode = document.getElementById('projectReportMode')?.value || 'folder_level';
    const reportLevel = reportMode === 'folder_level'
        ? Number(document.getElementById('projectReportLevel')?.value || 0)
        : null;
    if (!templateId) return alert('Vui lòng chọn biểu mẫu.');
    if (!caseLevel) return alert('Vui lòng chọn cấp hồ sơ.');
    if (reportMode === 'folder_level' && (!reportLevel || reportLevel <= caseLevel)) {
        return alert('Cấp báo cáo phải sâu hơn cấp hồ sơ.');
    }

    const button = document.getElementById('createProjectButton');
    if (button) button.disabled = true;
    try {
        const manifest = await buildProjectManifest();
        let resume = getProjectUploadResumeState();
        if (!resume || resume.root_name !== selectedProjectRootName) {
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
            resume = {
                project_id: Number(created.project_id),
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
