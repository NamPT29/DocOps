// =============================================================================
// PROJECT REPORTS & EXPORT (Số hóa All in One)
// Chuyên trách: Modal duyệt cây thư mục báo cáo, kiểm duyệt và tác vụ xuất Excel
// =============================================================================

var activeProjectReportsProjectId = null;
var activeProjectReportsView = 'review';
var activeProjectReportsFolderPath = '';
var activeProjectReportsPage = 1;

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
        if (item.has_errors) row.classList.add('table-danger');
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
        badge.className = item.status === 'completed'
            ? 'badge bg-success'
            : item.status === 'pending_input_confirmation'
                ? 'badge bg-info text-dark'
                : 'badge bg-warning text-dark';
        badge.textContent = item.status === 'completed'
            ? 'Hoàn thành'
            : item.status === 'pending_input_confirmation'
                ? 'Chờ người nhập xác nhận'
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
            approveButton.innerHTML = '<i class="fas fa-check"></i> Xác nhận kiểm duyệt';
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
    const projectsList = typeof projectManagementProjects !== 'undefined' ? projectManagementProjects : [];
    const project = projectsList.find(item => Number(item.id) === Number(projectId));
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
    const performApproval = () => apiCall(`/api/submissions/${Number(submissionId)}/toggle_check`, {
        method: 'PUT',
        headers: typeof submissionLeaseHeaders === 'function' ? submissionLeaseHeaders() : {},
    });
    const response = typeof withSubmissionViewLease === 'function'
        ? await withSubmissionViewLease(submissionId, performApproval)
        : await performApproval();
    if (!response || response.status !== 'ok') return;
    await Promise.all([
        reloadProjectReports(),
        typeof loadProjectList === 'function' ? loadProjectList() : Promise.resolve(),
    ]);
}

async function reopenProjectSubmission(submissionId) {
    if (!confirm('Chuyển hồ sơ này về trạng thái Chờ duyệt?')) return;
    const response = await apiCall(`/api/submissions/${Number(submissionId)}/reopen-review`, {method: 'PUT'});
    if (!response || response.status !== 'ok') return;
    await Promise.all([
        reloadProjectReports(),
        typeof loadProjectList === 'function' ? loadProjectList() : Promise.resolve(),
    ]);
}

async function deleteProjectSubmission(submissionId) {
    if (!confirm('Bạn có chắc muốn xóa hồ sơ này?')) return;
    const response = await apiCall(`/api/submissions/${Number(submissionId)}`, {method: 'DELETE'});
    if (!response) return;
    await Promise.all([
        reloadProjectReports(),
        typeof loadProjectList === 'function' ? loadProjectList() : Promise.resolve(),
    ]);
}

async function exportProjectReports(projectId, includePendingReview) {
    const projectsList = typeof projectManagementProjects !== 'undefined' ? projectManagementProjects : [];
    const project = projectsList.find(item => Number(item.id) === Number(projectId));
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
