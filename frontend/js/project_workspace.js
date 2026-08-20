window.activeProjectId = null;
window.activeProjectWorkspace = null;

function employeeProjectStorageKey() {
    const userKey = currentUser && (currentUser.id || currentUser.username);
    return `activeEmployeeProject_${userKey || 'anonymous'}`;
}

function setEmployeeProjectSummary(message, tone = 'muted') {
    const summary = document.getElementById('employeeProjectSummary');
    if (!summary) return;
    summary.className = `small text-${tone} mt-md-4`;
    summary.textContent = message;
}

function clearEmployeeProjectQueue(message = 'Dự án chưa có tài liệu được giao cho bạn.') {
    uploadedFilesQueue = [];
    iframeCurrentIndex = -1;
    activeQueueFolderKey = null;
    activeDocumentFolderPath = null;
    setActiveDocumentRelativePath(null);
    saveQueueState();
    renderFileQueue();
    showEmptyPdfQueueState(message);
}

function applyEmployeeProjectQueue(workspace) {
    const files = Array.isArray(workspace.files) ? workspace.files : [];
    uploadedFilesQueue = files.map(file => ({
        name: file.name,
        url: file.url,
        uuid: file.uuid,
        relative_path: file.relative_path || null,
        folder_group: file.folder_group || null,
        case_id: file.case_id,
        case_name: file.case_name,
        report_unit_id: file.report_unit_id,
        report_name: file.report_name,
        project_id: workspace.project.id,
        project_name: workspace.project.name,
        template_id: workspace.project.template_id,
        template_name: workspace.project.template_name,
        temporary_view: false,
        completed: file.entered === true,
    }));
    iframeCurrentIndex = -1;
    activeQueueFolderKey = null;
    saveQueueState();
    renderFileQueue();
    if (uploadedFilesQueue.length) {
        selectFileFromQueue(0);
    } else {
        showEmptyPdfQueueState('Dự án chưa có tài liệu được giao cho bạn.');
    }
}

async function loadEmployeeProjectWorkspace(projectId) {
    const safeProjectId = Number(projectId);
    if (!Number.isInteger(safeProjectId) || safeProjectId <= 0) return false;

    setEmployeeProjectSummary('Đang tải cấu hình và tài liệu dự án...', 'primary');
    const response = await apiCall(
        `/api/projects/${safeProjectId}/workspace`,
        { cache: 'no-store' },
        'Không thể tải dự án',
    );
    if (!response || !response.data) return false;

    if (typeof cancelEdit === 'function') cancelEdit();
    window.activeProjectId = safeProjectId;
    window.activeProjectWorkspace = response.data;
    window.activeTemplateId = response.data.project.template_id;
    localStorage.setItem(employeeProjectStorageKey(), String(safeProjectId));

    const hiddenTemplateSelect = document.getElementById('templateSelect');
    if (hiddenTemplateSelect) hiddenTemplateSelect.value = String(window.activeTemplateId);
    const templateContainer = document.getElementById('templateSelectContainer');
    if (templateContainer) templateContainer.style.setProperty('display', 'none', 'important');
    const manualUploadLabel = document.getElementById('manualPdfUploadLabel');
    if (manualUploadLabel) manualUploadLabel.classList.add('d-none');

    await fetchSchema();
    applyEmployeeProjectQueue(response.data);
    setEmployeeProjectSummary(
        `${response.data.project.template_name} · ${response.data.files.length} PDF được giao`,
        'success',
    );
    return true;
}

async function onEmployeeProjectSelected() {
    const select = document.getElementById('employeeProjectSelect');
    if (!select || !select.value) {
        window.activeProjectId = null;
        window.activeProjectWorkspace = null;
        clearEmployeeProjectQueue('Vui lòng chọn dự án để bắt đầu nhập.');
        return;
    }
    await loadEmployeeProjectWorkspace(select.value);
}

async function initializeEmployeeProjectWorkspace() {
    const card = document.getElementById('employeeProjectCard');
    const select = document.getElementById('employeeProjectSelect');
    if (!select || !currentUser || !currentUserCanInput()) return false;

    const response = await apiCall('/api/projects/mine', { cache: 'no-store' }, 'Không thể tải danh sách dự án');
    if (!response) return false;
    const currentUserId = Number(currentUser.id);
    const projects = (Array.isArray(response.data) ? response.data : []).filter(project =>
        Array.isArray(project.input_user_ids)
        && project.input_user_ids.map(Number).includes(currentUserId)
        && project.status === 'ready'
    );

    select.replaceChildren();
    if (!projects.length) {
        if (card) card.classList.add('d-none');
        const manualUploadLabel = document.getElementById('manualPdfUploadLabel');
        if (manualUploadLabel) manualUploadLabel.classList.remove('d-none');
        return false;
    }

    if (card) card.classList.remove('d-none');
    projects.forEach(project => {
        const option = document.createElement('option');
        option.value = String(project.id);
        option.textContent = `${project.name} — ${project.template_name}`;
        select.appendChild(option);
    });
    const storedProjectId = localStorage.getItem(employeeProjectStorageKey());
    const selectedProject = projects.find(project => String(project.id) === storedProjectId) || projects[0];
    select.value = String(selectedProject.id);
    return loadEmployeeProjectWorkspace(selectedProject.id);
}

async function refreshEmployeeProjectQueue() {
    if (window.activeProjectId) {
        await loadEmployeeProjectWorkspace(window.activeProjectId);
        return;
    }
    if (typeof fetchMyQueue === 'function') await fetchMyQueue(true);
}
