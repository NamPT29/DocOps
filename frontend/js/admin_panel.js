
// --- UTILITIES ---

function renderGenericFolderTree(folders, options) {
    const {
        containerId,
        emptyMessage,
        activeFolderPath,
        itemClassName,
        getBadgeHTML,
        getExtraInfoHTML,
        onFolderClick
    } = options;

    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';
    if (!folders.length) {
        container.innerHTML = `<div class="text-center text-muted p-3">${emptyMessage}</div>`;
        return;
    }

    buildFolderTreeNodes(folders).forEach(node => {
        const row = document.createElement(node.folder ? 'button' : 'div');
        row.style.paddingLeft = `${12 + node.depth * 18}px`;
        if (!node.folder) {
            row.className = 'py-2 fw-semibold text-secondary border-bottom';
            row.innerHTML = `<i class="fas fa-folder me-2 text-warning"></i>${escapeHTML(node.name)}`;
        } else {
            const folder = node.folder;
            const selected = folder.folder_path === activeFolderPath;
            row.type = 'button';
            row.className = `${itemClassName} list-group-item list-group-item-action py-2 ${selected ? 'active' : ''}`;
            row.dataset.folderPath = folder.folder_path;
            row.innerHTML = `
                <div class="d-flex justify-content-between gap-2">
                    <span class="text-break"><i class="fas fa-folder-open me-2"></i>${escapeHTML(node.name)}</span>
                    ${getBadgeHTML(folder)}
                </div>
                <div class="small ${selected ? 'text-white-50' : 'text-muted'} mt-1">
                    Người nhập: ${escapeHTML((folder.input_names || []).join(', ') || 'Chưa xác định')} ${getExtraInfoHTML ? getExtraInfoHTML(folder) : ''}
                </div>`;
            row.onclick = () => onFolderClick(folder.folder_path);
        }
        container.appendChild(row);
    });
}

function buildFolderTreeNodes(folders) {
    const nodes = new Map();
    folders.forEach(folder => {
        const parts = folder.folder_path === '__NO_FOLDER__'
            ? ['Chưa xác định folder']
            : folder.folder_path === '__ROOT__'
                ? ['Thư mục gốc']
                : String(folder.folder_path).split(/[\\/]+/).filter(Boolean);
        parts.forEach((part, index) => {
            const key = parts.slice(0, index + 1).join('/');
            if (!nodes.has(key)) nodes.set(key, { key, name: part, depth: index, folder: null });
            if (index === parts.length - 1) nodes.get(key).folder = folder;
        });
    });
    return [...nodes.values()].sort((a, b) => a.key.localeCompare(b.key, 'vi'));
}

function generatePaginationHTML(pagination, onPageClickFnName) {
    if (pagination.total_pages <= 1) return '';
    let html = `<nav><ul class="pagination pagination-sm justify-content-end mb-0">`;
    html += `<li class="page-item ${pagination.page === 1 ? 'disabled' : ''}">
                <a class="page-link" href="#" data-admin-generated-action="paginate" data-page-function="${escapeHTML(onPageClickFnName)}" data-page="${pagination.page - 1}">Trước</a>
             </li>`;
    for (let i = 1; i <= pagination.total_pages; i++) {
        html += `<li class="page-item ${pagination.page === i ? 'active' : ''}">
                    <a class="page-link" href="#" data-admin-generated-action="paginate" data-page-function="${escapeHTML(onPageClickFnName)}" data-page="${i}">${i}</a>
                 </li>`;
    }
    html += `<li class="page-item ${pagination.page === pagination.total_pages ? 'disabled' : ''}">
                <a class="page-link" href="#" data-admin-generated-action="paginate" data-page-function="${escapeHTML(onPageClickFnName)}" data-page="${pagination.page + 1}">Sau</a>
             </li>`;
    html += `</ul></nav>`;
    return html;
}
// -----------------

let submissionsCurrentPage = 1;
let completedSubmissionsCurrentPage = 1;
let reviewSubmissionsCurrentPage = 1;
let submissionsPageSize = 20;
const selectedSubmissionIds = new Set();
const selectableSubmissionStatuses = new Map();

function hasSubmissionQualityChanges(submission) {
    const quality = submission && submission.quality;
    return Boolean(
        quality
        && (
            quality.has_review_changes === true
            || Number(quality.changed_field_count) > 0
            || quality.is_error_report === true
        )
    );
}

function isSubmissionQualityError(submission) {
    return submission?.quality?.is_error_report === true;
}

function applySubmissionQualityRowClass(row, submission) {
    if (!row) return;
    if (isSubmissionQualityError(submission)) {
        row.classList.add('submission-quality-error');
    } else if (hasSubmissionQualityChanges(submission)) {
        row.classList.add('submission-quality-changed');
    }
}

function filterSubmissionsByQuality(submissions, filterValue) {
    const items = Array.isArray(submissions) ? submissions : [];
    return filterValue === 'changed'
        ? items.filter(hasSubmissionQualityChanges)
        : items;
}

async function fetchSubmissions(page = 1) {
    submissionsCurrentPage = Math.max(1, Number(page) || 1);
    selectedSubmissionIds.clear();
    selectableSubmissionStatuses.clear();
    updateBulkSubmissionActions();
    let url = new URL('/api/submissions', window.location.origin);
    url.searchParams.set('page', submissionsCurrentPage);
    url.searchParams.set('page_size', submissionsPageSize);

    const filterTid = document.getElementById('filterTemplateId');
    if (filterTid && filterTid.value) {
        url.searchParams.append('template_id', filterTid.value);
    } else if (window.activeTemplateId && !window.location.pathname.includes('admin.html')) {
        url.searchParams.append('template_id', window.activeTemplateId);
    }

    const startDate = document.getElementById('filterStartDate');
    if (startDate && startDate.value) {
        url.searchParams.append('start_date', startDate.value);
    }

    const endDate = document.getElementById('filterEndDate');
    if (endDate && endDate.value) {
        url.searchParams.append('end_date', endDate.value);
    }

    const res = await apiCall(url.toString());
    if (!res) return;

    const tbody = document.getElementById('submissionsTableBody');
    if (!tbody) return; // safety
    tbody.innerHTML = '';

    const qualityFilter = document.getElementById('filterSubmissionQuality')?.value || 'all';
    const displayedSubmissions = filterSubmissionsByQuality(res.data, qualityFilter);

    if (displayedSubmissions.length === 0) {
        const emptyMessage = qualityFilter === 'changed' && res.data.length > 0
            ? 'Trang này không có hồ sơ nào có trường bị sửa.'
            : 'Chưa có dữ liệu';
        tbody.innerHTML = `<tr><td colspan="9" class="text-center">${emptyMessage}</td></tr>`;
        renderSubmissionsPagination(res.pagination, 'submissionsPagination', fetchSubmissions);
        return;
    }

    displayedSubmissions.forEach(sub => {
        const tr = document.createElement('tr');
        const safeId = Number(sub.id);
        const safeCreatedAt = escapeHTML(sub.created_at);
        const safeTemplate = escapeHTML(sub.template);
        const safeCreator = escapeHTML(sub.creator_name || 'Unknown');
        const safeReviewer = escapeHTML(sub.reviewer_name || 'Chưa phân công');
        const safePdfPath = escapeHTML(sub.pdf_relative_path || sub.pdf_filename || '');
        const canDelete = sub.status === 'draft' || (currentUser && currentUser.role === 'admin');
        const canSelect = sub.status === 'draft';
        if (canSelect) selectableSubmissionStatuses.set(safeId, sub.status);
        if (sub.has_errors) {
            tr.classList.add('table-danger');
        }
        applySubmissionQualityRowClass(tr, sub);

        let statusBadge = '';
        if (sub.status === 'pending_review') statusBadge = '<span class="badge bg-warning text-dark"><i class="fas fa-hourglass-half"></i> Chờ duyệt</span>';
        else if (sub.status === 'pending_input_confirmation') statusBadge = '<span class="badge bg-info text-dark"><i class="fas fa-user-check"></i> Chờ người nhập xác nhận</span>';
        else if (sub.status === 'completed') statusBadge = '<span class="badge bg-success"><i class="fas fa-check-circle"></i> Hoàn thành</span>';
        if (isReviewTab && sub.is_reviewer_assigned === false) {
            statusBadge += '<span class="badge bg-secondary ms-1"><i class="fas fa-user-clock"></i> Chưa phân người kiểm</span>';
        }
        else statusBadge = '<span class="badge bg-secondary"><i class="fas fa-save"></i> Lưu nháp</span>';

        tr.innerHTML = `
            <td class="text-center">
                ${canSelect ? `<input type="checkbox" class="form-check-input submission-select-checkbox" value="${safeId}" data-admin-generated-change="toggle-submission-selection" data-submission-id="${safeId}" aria-label="Chọn hồ sơ ${safeId}">` : ''}
            </td>
            <td class="text-center fw-semibold">${Number(sub.serial_number) || ''}</td>
            <td><span class="badge bg-secondary">${safeTemplate}</span></td>
            <td class="text-nowrap">${safeCreatedAt}</td>
            <td class="generated-submission-path-cell">
                ${safePdfPath ? `<button type="button" class="btn btn-link btn-sm text-start text-break p-0" data-admin-generated-action="edit-submission" data-submission-id="${safeId}" title="${safePdfPath}"><i class="fas fa-file-pdf text-danger me-1"></i>${safePdfPath}</button>` : '<span class="text-muted fst-italic">Không liên kết PDF</span>'}
            </td>
            <td><span class="badge bg-info text-dark"><i class="fas fa-user"></i> ${safeCreator}</span></td>
            <td><span class="badge bg-primary"><i class="fas fa-user-check"></i> ${safeReviewer}</span></td>
            <td class="text-center">${statusBadge}</td>
            <td class="generated-submission-actions-cell">
                <div class="d-flex flex-wrap align-items-center gap-2">
                    <button class="btn btn-sm btn-outline-success" data-admin-generated-action="copy-submission" data-submission-id="${safeId}">Nhân bản</button>
                    <button class="btn btn-sm btn-outline-primary" data-admin-generated-action="edit-submission" data-submission-id="${safeId}">Xem/Sửa</button>
                    ${canDelete ? `<button class="btn btn-sm btn-outline-danger" data-admin-generated-action="delete-submission" data-submission-id="${safeId}" title="${sub.status === 'draft' ? 'Xóa bản nháp' : 'Xóa hồ sơ'}">Xóa</button>` : ''}
                </div>
            </td>
        `;
        tbody.appendChild(tr);
    });
    updateBulkSubmissionActions();
    renderSubmissionsPagination(res.pagination, 'submissionsPagination', fetchSubmissions);
}

function updateBulkSubmissionActions() {
    const count = selectedSubmissionIds.size;
    const totalSelectable = selectableSubmissionStatuses.size;
    const allSelected = totalSelectable > 0 && count === totalSelectable;
    const countElement = document.getElementById('selectedSubmissionsCount');
    const selectAllButton = document.getElementById('selectAllSubmissionsBtn');
    const clearButton = document.getElementById('clearSubmissionSelectionBtn');
    const deleteButton = document.getElementById('bulkDeleteSubmissionsBtn');
    const submitButton = document.getElementById('bulkSubmitSubmissionsBtn');
    document.querySelectorAll('.submission-select-checkbox').forEach(checkbox => {
        const checked = selectedSubmissionIds.has(Number(checkbox.value));
        checkbox.checked = checked;
        const row = checkbox.closest('tr');
        if (row) row.classList.toggle('table-success', checked);
    });
    if (countElement) {
        countElement.textContent = `Đã chọn: ${count}`;
        countElement.classList.toggle('bg-primary', count > 0);
        countElement.classList.toggle('text-white', count > 0);
        countElement.classList.toggle('bg-light', count === 0);
        countElement.classList.toggle('text-dark', count === 0);
    }
    if (selectAllButton) {
        selectAllButton.disabled = totalSelectable === 0;
        selectAllButton.classList.toggle('btn-primary', allSelected);
        selectAllButton.classList.toggle('btn-outline-primary', !allSelected);
        selectAllButton.setAttribute('aria-pressed', String(allSelected));
    }
    if (clearButton) clearButton.disabled = count === 0;
    if (submitButton) submitButton.disabled = count === 0;
    if (deleteButton) {
        deleteButton.disabled = count === 0 || Array.from(selectedSubmissionIds).some(
            id => selectableSubmissionStatuses.get(id) !== 'draft'
        );
    }
}

function toggleSubmissionSelection(id, checked) {
    const submissionId = Number(id);
    if (!selectableSubmissionStatuses.has(submissionId)) return;
    if (checked) selectedSubmissionIds.add(submissionId);
    else selectedSubmissionIds.delete(submissionId);
    updateBulkSubmissionActions();
}

function selectAllSubmissionsOnPage() {
    selectableSubmissionStatuses.forEach((_status, id) => selectedSubmissionIds.add(id));
    updateBulkSubmissionActions();
}

function clearSubmissionSelection() {
    selectedSubmissionIds.clear();
    updateBulkSubmissionActions();
}

async function runBulkSubmissionAction(action) {
    const submissionIds = Array.from(selectedSubmissionIds);
    if (submissionIds.length === 0) return;
    if (!['delete', 'submit_for_review'].includes(action)) return;
    const actionLabel = action === 'delete' ? 'xóa' : 'nộp duyệt';
    if (!confirm(`Bạn có chắc muốn ${actionLabel} ${submissionIds.length} hồ sơ đã chọn?`)) return;

    const res = await apiCall('/api/submissions/bulk-action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ submission_ids: submissionIds, action }),
    });
    if (!res) return;
    alert(`Đã ${actionLabel} thành công ${res.processed_count} hồ sơ.`);
    await fetchSubmissions(submissionsCurrentPage);
}

function bulkDeleteSelectedSubmissions() {
    return runBulkSubmissionAction('delete');
}

function bulkSubmitSelectedSubmissions() {
    return runBulkSubmissionAction('submit_for_review');
}

let activeReviewFolderPath = null;
let reviewFolderCache = [];
let activeCompletedFolderPath = null;
let completedFolderCache = [];

async function fetchReviewSubmissions(resetPage = true) {
    if (resetPage) reviewSubmissionsCurrentPage = 1;
    let url = new URL('/api/review-folders', window.location.origin);
    const filterTid = document.getElementById('filterReviewTemplateId');
    if (filterTid && filterTid.value) url.searchParams.append('template_id', filterTid.value);
    const duplicateFilter = document.getElementById('filterReviewDuplicates');
    if (duplicateFilter && duplicateFilter.checked) url.searchParams.set('duplicate_only', 'true');
    const res = await apiCall(url.toString());
    if (!res) return;
    reviewFolderCache = Array.isArray(res.data) ? res.data : [];
    if (!reviewFolderCache.some(folder => folder.folder_path === activeReviewFolderPath)) {
        activeReviewFolderPath = null;
    }
    renderReviewFolderTree(reviewFolderCache);
    if (activeReviewFolderPath) {
        await selectReviewFolder(activeReviewFolderPath, reviewSubmissionsCurrentPage, false);
        return;
    }
    const title = document.getElementById('selectedReviewFolderTitle');
    if (title) title.textContent = 'Chọn một folder để xem báo cáo đã nộp';
    const tbody = document.getElementById('reviewTableBody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Chưa chọn folder kiểm tra.</td></tr>';
    const pagination = document.getElementById('reviewSubmissionsPagination');
    if (pagination) pagination.innerHTML = '';
}

function renderReviewFolderTree(folders) {
    renderGenericFolderTree(folders, {
        containerId: 'reviewFolderTree',
        emptyMessage: 'Chưa có folder nào được phân kiểm tra.',
        activeFolderPath: activeReviewFolderPath,
        itemClassName: 'review-folder-item',
        getBadgeHTML: (folder) => `<span class="badge ${folder.submitted_count ? 'bg-danger' : 'bg-secondary'} rounded-pill">${Number(folder.submitted_count) || 0}</span>`,
        getExtraInfoHTML: (folder) => `· ${Number(folder.total_documents) || 0} tài liệu`,
        onFolderClick: (folderPath) => selectReviewFolder(folderPath)
    });
}

async function selectReviewFolder(folderPath, page = 1, rerenderTree = true) {
    activeReviewFolderPath = folderPath;
    reviewSubmissionsCurrentPage = Math.max(1, Number(page) || 1);
    if (rerenderTree) renderReviewFolderTree(reviewFolderCache);
    const title = document.getElementById('selectedReviewFolderTitle');
    if (title) title.textContent = folderPath === '__ROOT__' ? 'Thư mục gốc' : folderPath;
    const tbody = document.getElementById('reviewTableBody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="6" class="text-center">Đang tải báo cáo trong folder...</td></tr>';

    const url = new URL('/api/review-folder-submissions', window.location.origin);
    url.searchParams.set('folder_path', folderPath);
    url.searchParams.set('page', reviewSubmissionsCurrentPage);
    url.searchParams.set('page_size', submissionsPageSize);
    const filterTid = document.getElementById('filterReviewTemplateId');
    if (filterTid && filterTid.value) url.searchParams.set('template_id', filterTid.value);
    const duplicateFilter = document.getElementById('filterReviewDuplicates');
    if (duplicateFilter && duplicateFilter.checked) url.searchParams.set('duplicate_only', 'true');
    const res = await apiCall(url.toString());
    if (!res) return;
    reviewSubmissionsCurrentPage = Math.max(1, Number(res.pagination?.page) || reviewSubmissionsCurrentPage);
    renderAdminSubmissionsTable(
        Array.isArray(res.data) ? res.data : [],
        'reviewTableBody',
        true,
        res.pagination,
    );
}

async function fetchCompletedSubmissions(page = 1, refreshFolders = Number(page) === 1) {
    completedSubmissionsCurrentPage = Math.max(1, Number(page) || 1);
    const filterTid = document.getElementById('filterTemplateId');
    if (filterTid && filterTid.options.length <= 1 && typeof populateTemplatesDropdown === 'function') {
        await populateTemplatesDropdown('filterTemplateId', true);
    }

    const startDate = document.getElementById('filterStartDate');
    const endDate = document.getElementById('filterEndDate');
    const duplicateFilter = document.getElementById('filterCompletedDuplicates');
    if (refreshFolders) {
        const folderUrl = new URL('/api/completed-folders', window.location.origin);
        if (filterTid && filterTid.value) folderUrl.searchParams.set('template_id', filterTid.value);
        if (startDate && startDate.value) folderUrl.searchParams.set('start_date', startDate.value);
        if (endDate && endDate.value) folderUrl.searchParams.set('end_date', endDate.value);
        if (duplicateFilter && duplicateFilter.checked) folderUrl.searchParams.set('duplicate_only', 'true');
        const folderResponse = await apiCall(folderUrl.toString());
        if (!folderResponse) return;
        completedFolderCache = Array.isArray(folderResponse.data) ? folderResponse.data : [];
        if (!completedFolderCache.some(folder => folder.folder_path === activeCompletedFolderPath)) {
            activeCompletedFolderPath = completedFolderCache[0]?.folder_path || null;
        }
        renderCompletedFolderTree(completedFolderCache);
    }

    const title = document.getElementById('selectedCompletedFolderTitle');
    const tbody = document.getElementById('submissionsTableBody');
    const pagination = document.getElementById('submissionsPagination');
    if (!activeCompletedFolderPath) {
        if (title) title.textContent = 'Chọn một folder để xem hồ sơ hoàn thành';
        if (tbody) tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-4">Chưa có hồ sơ hoàn chỉnh theo bộ lọc hiện tại.</td></tr>';
        if (pagination) pagination.innerHTML = '';
        return;
    }
    const activeFolder = completedFolderCache.find(
        folder => folder.folder_path === activeCompletedFolderPath
    );
    if (title) {
        title.textContent = activeFolder?.folder_name === 'Chưa xác định folder'
            ? activeFolder.folder_name
            : activeCompletedFolderPath === '__ROOT__'
                ? 'Thư mục gốc'
                : activeCompletedFolderPath;
    }
    if (tbody) tbody.innerHTML = '<tr><td colspan="7" class="text-center">Đang tải hồ sơ trong folder...</td></tr>';

    let url = new URL('/api/submissions', window.location.origin);
    url.searchParams.set('status', 'completed');
    url.searchParams.set('folder_path', activeCompletedFolderPath);
    url.searchParams.set('page', completedSubmissionsCurrentPage);
    url.searchParams.set('page_size', submissionsPageSize);
    if (filterTid && filterTid.value) url.searchParams.set('template_id', filterTid.value);
    if (startDate && startDate.value) url.searchParams.set('start_date', startDate.value);
    if (endDate && endDate.value) url.searchParams.set('end_date', endDate.value);
    if (duplicateFilter && duplicateFilter.checked) url.searchParams.set('duplicate_only', 'true');
    const res = await apiCall(url.toString());
    if (!res) return;
    renderAdminSubmissionsTable(res.data, 'submissionsTableBody', false, res.pagination);
}

function renderCompletedFolderTree(folders) {
    renderGenericFolderTree(folders, {
        containerId: 'completedFolderTree',
        emptyMessage: 'Chưa có folder chứa hồ sơ hoàn thành.',
        activeFolderPath: activeCompletedFolderPath,
        itemClassName: 'completed-folder-item',
        getBadgeHTML: (folder) => `<span class="badge bg-success rounded-pill">${Number(folder.approved_count) || 0}</span>`,
        getExtraInfoHTML: null,
        onFolderClick: (folderPath) => selectCompletedFolder(folderPath)
    });
}

async function selectCompletedFolder(folderPath) {
    activeCompletedFolderPath = folderPath;
    renderCompletedFolderTree(completedFolderCache);
    await fetchCompletedSubmissions(1, false);
}

function renderSubmissionsPagination(pagination, containerId, onPageChange, options = {}) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';
    if (!pagination || Number(pagination.total) === 0) return;

    const page = Number(pagination.page) || 1;
    const totalPages = Number(pagination.total_pages) || 1;
    const summary = document.createElement('span');
    summary.className = 'text-muted small me-3';
    summary.textContent = `Hiển thị ${Number(pagination.from) || 0}–${Number(pagination.to) || 0} / ${Number(pagination.total) || 0} hồ sơ`;
    container.appendChild(summary);

    const sizeSelector = document.createElement('select');
    sizeSelector.className = 'form-select form-select-sm d-inline-block w-auto me-3';
    const sizeValue = Number(options.pageSize) || submissionsPageSize;
    [5, 10, 15, 20].forEach(size => {
        const option = document.createElement('option');
        option.value = size;
        option.textContent = `${size} / trang`;
        if (size === sizeValue) option.selected = true;
        sizeSelector.appendChild(option);
    });
    sizeSelector.onchange = (e) => {
        if (typeof options.onPageSizeChange === 'function') {
            options.onPageSizeChange(Number(e.target.value));
        } else {
            submissionsPageSize = Number(e.target.value);
        }
        onPageChange(1);
    };
    container.appendChild(sizeSelector);

    const previous = document.createElement('button');
    previous.type = 'button';
    previous.className = 'btn btn-sm btn-outline-primary me-2';
    previous.textContent = '‹ Trước';
    previous.disabled = page <= 1;
    previous['onclick'] = () => onPageChange(page - 1);
    container.appendChild(previous);

    const pageLabel = document.createElement('span');
    pageLabel.className = 'small fw-semibold me-2';
    pageLabel.textContent = `Trang ${page} / ${totalPages}`;
    container.appendChild(pageLabel);

    const next = document.createElement('button');
    next.type = 'button';
    next.className = 'btn btn-sm btn-outline-primary';
    next.textContent = 'Sau ›';
    next.disabled = page >= totalPages;
    next.onclick = () => onPageChange(page + 1);
    container.appendChild(next);
}

function renderAdminSubmissionsTable(data, tbodyId, isReviewTab, pagination = null) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    const renderPagination = () => {
        if (isReviewTab) {
            renderSubmissionsPagination(
                pagination,
                'reviewSubmissionsPagination',
                page => selectReviewFolder(activeReviewFolderPath, page, false),
            );
            return;
        }
        renderSubmissionsPagination(pagination, 'submissionsPagination', fetchCompletedSubmissions);
    };
    tbody.innerHTML = '';
    if (data.length === 0) {
        tbody.innerHTML = `<tr><td colspan="${isReviewTab ? 6 : 7}" class="text-center text-muted py-4">${isReviewTab ? 'Folder đã được phân nhưng chưa có báo cáo nào được nộp duyệt.' : 'Chưa có dữ liệu'}</td></tr>`;
        renderPagination();
        return;
    }
    data.forEach(sub => {
        const tr = document.createElement('tr');
        const safeId = Number(sub.id);
        const safeCreatedAt = escapeHTML(sub.created_at);
        const safeCreator = escapeHTML(sub.creator_name || 'Unknown');
        const safeTemplate = escapeHTML(sub.template);
        const safePdfPath = escapeHTML(sub.pdf_relative_path || sub.pdf_filename || '');
        const returnTarget = isReviewTab ? 'review' : 'completed';
        let submissionUrl = `index.html?check_id=${safeId}&return_to=${returnTarget}`;
        if (isReviewTab && activeReviewFolderPath) {
            submissionUrl += `&return_folder=${encodeURIComponent(activeReviewFolderPath)}`;
        }
        const safeSubmissionUrl = escapeHTML(submissionUrl);
        if (sub.has_errors) tr.classList.add('table-danger');
        applySubmissionQualityRowClass(tr, sub);

        let statusBadge = '';
        if (sub.status === 'pending_review') statusBadge = '<span class="badge bg-warning text-dark"><i class="fas fa-hourglass-half"></i> Chờ duyệt</span>';
        else if (sub.status === 'pending_input_confirmation') statusBadge = '<span class="badge bg-info text-dark"><i class="fas fa-user-check"></i> Chờ người nhập xác nhận</span>';
        else if (sub.status === 'completed') statusBadge = '<span class="badge bg-success"><i class="fas fa-check-circle"></i> Hoàn thành</span>';

        const reviewTarget = isReviewTab ? '' : ' target="_blank"';
        let actions = `<a class="btn btn-sm btn-outline-primary" href="${safeSubmissionUrl}"${reviewTarget} title="Mở để kiểm tra và chỉnh sửa"><i class="fas fa-search"></i> Kiểm tra/Sửa</a>`;
        if (sub.is_being_viewed || sub.viewing_user_name) {
            const viewerName = escapeHTML(sub.viewing_user_name || 'Người dùng khác');
            statusBadge += `<span class='badge bg-info text-dark ms-1'><i class='fas fa-eye'></i> Báo cáo đang có người xem: ${viewerName}</span>`;
        }
        if (currentUser && currentUser.role === 'admin') {
            if (sub.status === 'completed') {
                actions += `<button class="btn btn-sm btn-outline-warning" data-admin-generated-action="reopen-submission" data-submission-id="${safeId}" title="Chuyển hồ sơ về hàng chờ kiểm tra"><i class="fas fa-undo"></i> Về chờ duyệt</button>`;
            }
            actions += `<button class="btn btn-sm btn-outline-danger" data-admin-generated-action="delete-submission" data-submission-id="${safeId}" title="Xóa hồ sơ"><i class="fas fa-trash"></i></button>`;
        }

        tr.innerHTML = `
            ${isReviewTab ? '' : `<td class="text-center fw-semibold">${Number(sub.serial_number) || ''}</td>`}
            <td><span class="badge bg-secondary">${safeTemplate}</span></td>
            <td class="text-nowrap">${safeCreatedAt}</td>
            <td class="generated-submission-path-cell">
                ${safePdfPath ? `<a class="text-break" href="${safeSubmissionUrl}"${reviewTarget} title="${safePdfPath}"><i class="fas fa-file-pdf text-danger me-1"></i>${safePdfPath}</a>` : '<span class="text-muted fst-italic">Không liên kết PDF</span>'}
            </td>
            <td><span class="badge bg-info text-dark"><i class="fas fa-user"></i> ${safeCreator}</span></td>
            <td class="text-center">${statusBadge}</td>
            <td class="generated-submission-actions-cell"><div class="d-flex flex-wrap align-items-center gap-2">${actions}</div></td>
        `;
        tbody.appendChild(tr);
    });
    renderPagination();
}

async function reopenSubmissionReview(id) {
    if (!currentUser || currentUser.role !== 'admin') {
        alert('Chỉ admin được chuyển hồ sơ về chờ duyệt.');
        return;
    }
    if (!confirm('Chuyển hồ sơ này về trạng thái Chờ duyệt?')) return;

    const res = await apiCall(`/api/submissions/${id}/reopen-review`, { method: 'PUT' });
    if (res && res.status === 'ok') {
        await Promise.all([
            fetchReviewSubmissions(),
            fetchCompletedSubmissions(1, true),
        ]);
    }
}

function updateReviewConfirmationStatus(status, canConfirm = false, submissionStatus = null) {
    const checkbox = document.getElementById('reviewConfirmCheckbox');
    const badge = document.getElementById('reviewConfirmationStatusBadge');
    const help = document.getElementById('reviewConfirmationHelp');
    const isCompleted = status === 'completed' || submissionStatus === 'completed';
    const isConfirmed = status === 'confirmed' || isCompleted;
    const isSaving = status === 'saving';

    if (checkbox) {
        checkbox.checked = isConfirmed || isSaving;
        checkbox.disabled = isConfirmed || isSaving || !canConfirm;
    }
    if (badge) {
        badge.className = isConfirmed
            ? 'badge bg-success'
            : (isSaving ? 'badge bg-info text-dark' : 'badge bg-warning text-dark');
        badge.textContent = isConfirmed
            ? (isCompleted ? 'Hoàn thành' : 'Đã kiểm duyệt')
            : (isSaving ? 'Đang lưu...' : 'Chưa kiểm duyệt');
    }
    if (help) {
        help.textContent = isCompleted
            ? 'Người kiểm không thay đổi nội dung; hồ sơ đã hoàn thành ngay.'
            : (isConfirmed
                ? 'Nội dung đã được lưu và chuyển cho người nhập kiểm tra lại.'
            : (isSaving
                ? 'Hệ thống đang lưu chỉnh sửa và xác nhận kiểm duyệt.'
                : 'Tích xác nhận để lưu chỉnh sửa; hồ sơ không đổi sẽ hoàn thành ngay.'));
    }
}

async function confirmReviewSubmission(checkbox) {
    if (!checkbox || checkbox.checked !== true) return;
    const submissionId = Number(currentEditingId);
    if (!Number.isInteger(submissionId) || submissionId <= 0) {
        updateReviewConfirmationStatus('pending', true);
        return;
    }

    updateReviewConfirmationStatus('saving', false);
    try {
        const payload = {
            data: collectSubmissionFormData(),
        };
        const response = await authFetch(`/api/submissions/${submissionId}/confirm-review`, {
            method: 'PUT',
            headers: submissionLeaseHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(payload),
        });
        if (!response) throw new Error('Không nhận được phản hồi từ máy chủ.');
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(formatApiErrorDetail(result.detail || result.message || `HTTP ${response.status}`));
        }

        window.reviewApproved = true;
        window.reviewEditMode = false;
        const completedWithoutChanges = result.submission_status === 'completed';
        updateReviewConfirmationStatus(
            completedWithoutChanges ? 'completed' : 'confirmed',
            false,
            result.submission_status || null,
        );
        alert(completedWithoutChanges
            ? 'Đã xác nhận kiểm duyệt. Hồ sơ không có thay đổi và đã hoàn thành.'
            : 'Đã lưu chỉnh sửa và chuyển cho người nhập xác nhận.');
        await editSubmission(submissionId);
    } catch (error) {
        window.reviewApproved = false;
        updateReviewConfirmationStatus('pending', true);
        alert(`Không thể xác nhận kiểm duyệt: ${error.message}`);
    }
}

function reviewNavigationParams() {
    const params = new URLSearchParams(window.location.search);
    if (!params.has('check_id')) return null;
    return {
        folderPath: params.get('return_folder') || '',
        returnTarget: params.get('return_to') || 'review',
        projectId: params.get('return_project') || '',
    };
}

async function refreshReviewNextAction() {
    const button = document.getElementById('reviewNextButton');
    if (!button || !currentEditingId || window.reviewApproved !== true) {
        if (button) button.classList.add('d-none');
        return;
    }
    const navigation = reviewNavigationParams();
    if (!navigation || !['review', 'project_review'].includes(navigation.returnTarget)) {
        button.classList.add('d-none');
        return;
    }
    const params = new URLSearchParams({ current_id: String(currentEditingId) });
    if (navigation.folderPath) params.set('folder_path', navigation.folderPath);
    if (navigation.projectId) params.set('project_id', navigation.projectId);
    const res = await apiCall(`/api/review-next-submission?${params.toString()}`);
    if (!res || !button) return;
    const nextId = Number(res.data?.id);
    button.dataset.nextId = Number.isInteger(nextId) && nextId > 0 ? String(nextId) : '';
    button.classList.remove('d-none');
    button.disabled = !button.dataset.nextId;
    button.innerHTML = button.dataset.nextId
        ? '<i class="fas fa-arrow-right"></i> Hồ sơ tiếp theo'
        : '<i class="fas fa-check"></i> Đã hết hồ sơ cần kiểm tra';
}

function goToNextReviewSubmission() {
    const button = document.getElementById('reviewNextButton');
    const nextId = Number(button?.dataset.nextId);
    if (!Number.isInteger(nextId) || nextId <= 0) return;
    const navigation = reviewNavigationParams() || {};
    const params = new URLSearchParams({
        check_id: String(nextId),
        return_to: navigation.returnTarget || 'review',
    });
    if (navigation.folderPath) params.set('return_folder', navigation.folderPath);
    if (navigation.projectId) params.set('return_project', navigation.projectId);
    window.location.href = `index.html?${params.toString()}`;
}

function normalizeCopyScopeValue(value) {
    return value === null || value === undefined ? null : String(value);
}

function copyQueuePath(file) {
    const value = file?.relative_path || file?.name || '';
    return typeof normalizeQueuePath === 'function'
        ? normalizeQueuePath(value)
        : String(value).replace(/\\/g, '/');
}

function findNextCopyPdfQueueIndex(submission, queue = uploadedFilesQueue) {
    const files = Array.isArray(queue) ? queue : [];
    const sourceUuid = submission?.data?._pdf_uuid;
    const sourceIndex = files.findIndex(file => sourceUuid && file?.uuid === sourceUuid);
    if (sourceIndex < 0) return -1;

    const sourceFile = files[sourceIndex];
    const projectId = normalizeCopyScopeValue(sourceFile.project_id);
    const caseId = normalizeCopyScopeValue(sourceFile.case_id);
    const templateId = normalizeCopyScopeValue(submission?.template_id ?? sourceFile.template_id);
    if (projectId === null || caseId === null || templateId === null) return -1;

    const scopedFiles = files
        .map((file, index) => ({ file, index }))
        .filter(({ file }) => (
            file?.temporary_view !== true
            && normalizeCopyScopeValue(file?.project_id) === projectId
            && normalizeCopyScopeValue(file?.case_id) === caseId
            && normalizeCopyScopeValue(file?.template_id) === templateId
        ))
        .sort((left, right) => (
            copyQueuePath(left.file).localeCompare(copyQueuePath(right.file), 'vi', {
                numeric: true,
                sensitivity: 'base',
            }) || left.index - right.index
        ));
    const sourcePosition = scopedFiles.findIndex(item => item.index === sourceIndex);
    if (sourcePosition < 0) return -1;

    for (let offset = 1; offset < scopedFiles.length; offset++) {
        const candidate = scopedFiles[(sourcePosition + offset) % scopedFiles.length];
        if (candidate.file.completed !== true) return candidate.index;
    }
    return -1;
}

async function copySubmission(id) {
    if (!confirm('Bạn có chắc muốn nhân bản hồ sơ này sang PDF chưa nhập tiếp theo?')) return;
    await editSubmission(id, true);
}

let activeSubmissionViewId = null;
let activeSubmissionLeaseToken = null;
let submissionViewHeartbeat = null;

function submissionLeaseHeaders(headers = {}) {
    const result = { ...headers };
    if (activeSubmissionLeaseToken) {
        result['X-Submission-Lease-Token'] = activeSubmissionLeaseToken;
    }
    return result;
}

async function withSubmissionViewLease(submissionId, operation) {
    const id = Number(submissionId);
    const alreadyOwned = activeSubmissionViewId === id && Boolean(activeSubmissionLeaseToken);
    if (!alreadyOwned && !await startSubmissionView(id)) return null;
    try {
        return await operation();
    } finally {
        if (!alreadyOwned) stopSubmissionView();
    }
}

function bindSubmissionViewLifecycle() {
    if (typeof window === 'undefined' || window.__submissionViewLifecycleBound) return;
    window.__submissionViewLifecycleBound = true;
    window.addEventListener('pagehide', stopSubmissionView);
}

async function renewSubmissionView(submissionId) {
    if (activeSubmissionViewId !== submissionId) return;
    const response = await authFetch(`/api/submissions/${submissionId}/view`, {
        method: 'PUT',
        headers: submissionLeaseHeaders(),
    });
    if (!response || !response.ok) {
        stopSubmissionView();
        alert('Khóa hồ sơ đã hết hạn hoặc bị mất. Vui lòng mở lại hồ sơ trước khi lưu.');
        return;
    }
    const payload = await response.json().catch(() => ({}));
    if (typeof payload.lease_token === 'string' && payload.lease_token) {
        activeSubmissionLeaseToken = payload.lease_token;
    }
}

async function startSubmissionView(submissionId) {
    const id = Number(submissionId);
    if (!Number.isInteger(id) || id <= 0) return false;
    bindSubmissionViewLifecycle();
    if (activeSubmissionViewId !== id) stopSubmissionView();
    const response = await authFetch(`/api/submissions/${id}/view`, {
        method: 'PUT',
        headers: activeSubmissionViewId === id ? submissionLeaseHeaders() : {},
    });
    if (!response) return false;
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        const detail = payload.detail;
        const message = detail && typeof detail === 'object' && detail.message
            ? detail.message
            : formatApiErrorDetail(detail || 'Không thể mở hồ sơ lúc này.');
        alert(message);
        return false;
    }
    if (payload.viewer_is_current_user !== true) {
        const viewerName = payload.viewing_user_name || 'Người dùng khác';
        alert(`${viewerName} đang mở hồ sơ này. Vui lòng thử lại sau.`);
        return false;
    }
    activeSubmissionViewId = id;
    activeSubmissionLeaseToken = typeof payload.lease_token === 'string'
        ? payload.lease_token
        : null;
    // Rolling-deploy compatibility: the currently running legacy backend does
    // not return a lease token. It also does not require the lease header, so
    // keep the form usable until that backend is restarted. Once the new
    // backend is live, every write automatically carries the returned token.
    if (submissionViewHeartbeat) clearInterval(submissionViewHeartbeat);
    submissionViewHeartbeat = setInterval(() => renewSubmissionView(id), 30000);
    return true;
}

function stopSubmissionView() {
    const id = activeSubmissionViewId;
    const leaseToken = activeSubmissionLeaseToken;
    activeSubmissionViewId = null;
    activeSubmissionLeaseToken = null;
    if (submissionViewHeartbeat) clearInterval(submissionViewHeartbeat);
    submissionViewHeartbeat = null;
    if (!id || typeof fetch !== 'function') return;
    const headers = {};
    if (currentToken) headers.Authorization = `Bearer ${currentToken}`;
    if (leaseToken) headers['X-Submission-Lease-Token'] = leaseToken;
    fetch(`/api/submissions/${id}/view`, {
        method: 'DELETE',
        headers,
        keepalive: true,
    }).catch(() => { });
}

async function editSubmission(id, isCopied = false) {
    window.isCopiedSubmissionEdit = isCopied;
    if (!await startSubmissionView(id)) return;
    const res = await apiCall(`/api/submissions/${id}`);
    if (!res) {
        stopSubmissionView();
        return;
    }

    // Switch to form tab safely
    const formTabBtn = document.getElementById('form-tab');
    if (formTabBtn) {
        formTabBtn.click();
    }

    // Ensure schema is loaded before populating data
    if (res.template_id && window.activeTemplateId !== res.template_id) {
        window.activeTemplateId = res.template_id;
        await fetchSchema();
    } else if (!document.getElementById('dataForm').innerHTML.trim()) {
        // Form not rendered yet
        await fetchSchema();
    }

    // Populate data
    const data = res.data;
    for (const [key, value] of Object.entries(data)) {
        const input = document.getElementById(key);
        if (input) {
            input.value = value;
        }
    }
    if (typeof resizeDynamicFormInputs === 'function') {
        resizeDynamicFormInputs(document.getElementById('dataForm'));
    }
    
    if (window.isCopiedSubmissionEdit) {
        window.originalEditingData = collectSubmissionFormData();
    }
    
    // Save initial cover data to detect modifications
    window.initialCoverData = {};
    if (window.activeTemplateConfig && window.activeTemplateConfig.cover_cols) {
        window.activeTemplateConfig.cover_cols.forEach(c => {
            const key = `col_${c-1}`;
            window.initialCoverData[key] = res.data[key] || '';
        });
    }

    if (window.isCopiedSubmissionEdit) {
        const nextPdfIndex = findNextCopyPdfQueueIndex(res);
        if (nextPdfIndex < 0) {
            alert('Không còn PDF chưa nhập trong cùng dự án, cùng cấp hồ sơ và cùng biểu mẫu.');
            cancelEdit();
            return;
        }

        if (typeof stopSubmissionView === 'function') stopSubmissionView();
        currentEditingId = null;
        isEditingFromList = false;
        window.copySourceSubmissionId = Number(id);
        window.reviewEditMode = false;
        window.reviewApproved = false;

        const actionBtns = document.getElementById('actionButtonsRow');
        const readonlyNotice = document.getElementById('readonlyNotice');
        const clearFormBtn = document.getElementById('clearFormBtn');
        const cancelEditBtn = document.getElementById('cancelEditBtn');
        const adminCheckArea = document.getElementById('adminCheckArea');
        const pdfLinkBtn = document.getElementById('pdfLinkBtn');
        if (actionBtns) actionBtns.classList.remove('d-none');
        if (readonlyNotice) readonlyNotice.style.display = 'none';
        if (clearFormBtn) clearFormBtn.classList.remove('d-none');
        if (cancelEditBtn) cancelEditBtn.classList.remove('d-none');
        if (adminCheckArea) adminCheckArea.classList.add('d-none');
        if (pdfLinkBtn) pdfLinkBtn.classList.remove('d-none');
        document.querySelectorAll('#dataForm input, #dataForm textarea, #dataForm select').forEach(input => {
            input.disabled = false;
        });
        document.querySelectorAll('.clear-category-btn').forEach(button => {
            button.classList.remove('d-none');
        });
        if (typeof setSubmissionModeButtons === 'function') setSubmissionModeButtons(false, false);

        await selectFileFromQueue(nextPdfIndex, { allowSubmissionNavigation: false });

        window.initialCoverData = {};
        if (window.activeTemplateConfig && window.activeTemplateConfig.cover_cols) {
            window.activeTemplateConfig.cover_cols.forEach(c => {
                const key = `col_${c - 1}`;
                const input = document.getElementById(key);
                window.initialCoverData[key] = input ? input.value : '';
            });
        }
        await refreshReviewNextAction();
        return;
    }

    // Set editing state
    currentEditingId = id;
    isEditingFromList = true;

    // Handle readonly state
    const actionBtns = document.getElementById('actionButtonsRow');
    const readonlyNotice = document.getElementById('readonlyNotice');
    const clearFormBtn = document.getElementById('clearFormBtn');

    const isAdmin = currentUser && currentUser.role === 'admin';
    const canReview = res.can_review === true;
    const reviewEditMode = canReview && res.submission_status === 'pending_review';
    window.reviewEditMode = reviewEditMode;
    window.reviewApproved = canReview && ['pending_input_confirmation', 'completed'].includes(res.submission_status);
    const isLocked = !isAdmin && !reviewEditMode && res.submission_status !== 'draft';
    const canSubmitFromEnteredReport = !canReview && res.submission_status === 'draft';

    if (isLocked) {
        if (actionBtns) actionBtns.classList.add('d-none');
        if (clearFormBtn) clearFormBtn.classList.add('d-none');
        if (readonlyNotice) readonlyNotice.style.display = 'block';
    } else {
        if (actionBtns) actionBtns.classList.remove('d-none');
        if (clearFormBtn) clearFormBtn.classList.remove('d-none');
        if (readonlyNotice) readonlyNotice.style.display = 'none';

        // Cập nhật text nút
        if (typeof setSubmissionModeButtons === 'function') {
            setSubmissionModeButtons(canSubmitFromEnteredReport, false);
        }
    }

    document.getElementById('cancelEditBtn').classList.remove('d-none');

    if (canReview) {
        const adminCheckArea = document.getElementById('adminCheckArea');
        if (adminCheckArea) adminCheckArea.classList.remove('d-none');
        updateReviewConfirmationStatus(
            window.reviewApproved ? 'confirmed' : 'pending',
            reviewEditMode,
            res.submission_status,
        );

        // Việc lưu nội dung kiểm duyệt được thực hiện bởi ô xác nhận riêng.
        const draftBtn = document.getElementById('draftBtn');
        if (draftBtn) draftBtn.classList.add('d-none');
        const btnSubmit = document.getElementById('submitBtn');
        if (btnSubmit) btnSubmit.classList.add('d-none');
        if (actionBtns) actionBtns.classList.add('d-none');
        if (readonlyNotice) {
            readonlyNotice.style.display = reviewEditMode ? 'none' : 'block';
            readonlyNotice.textContent = reviewEditMode
                ? ''
                : 'Hồ sơ đã kiểm duyệt. Nội dung chỉ được phép xem.';
        }

        const btnClear = document.getElementById('clearFormBtn');
        if (btnClear) btnClear.classList.add('d-none');

        const btnCancel = document.getElementById('cancelEditBtn');
        if (btnCancel) btnCancel.style.setProperty('display', 'none', 'important');

        const pdfLinkBtn = document.getElementById('pdfLinkBtn');
        if (pdfLinkBtn) pdfLinkBtn.classList.add('d-none');

        // Hide clear category buttons
        document.querySelectorAll('.clear-category-btn').forEach(btn => btn.classList.add('d-none'));

        // Chỉ khóa nội dung khi hồ sơ đã rời khỏi bước kiểm tra.
        const inputs = document.querySelectorAll('#dataForm input, #dataForm textarea, #dataForm select');
        inputs.forEach(input => {
            input.disabled = !reviewEditMode;
        });
    } else {
        const adminCheckArea = document.getElementById('adminCheckArea');
        if (adminCheckArea) adminCheckArea.classList.add('d-none');
    }

    await refreshReviewNextAction();

    // Check if there is an attached PDF
    const attachedPdf = data._pdf_filename;
    const loadedReviewFolder = canReview && loadReviewFolderFiles(
        res.folder_files,
        data._pdf_uuid
    );
    if (!loadedReviewFolder && attachedPdf) {
        addFileToQueueAndSelect(attachedPdf, data._pdf_uuid, data._pdf_url, {
            relative_path: data._pdf_relative_path,
            folder_group: data._folder_path,
            template_id: res.template_id,
            temporary_view: true,
        });
    } else {
        window.pdfLinkState.setLinked(false);
    }
}

async function deleteSubmission(id) {
    if (!confirm('Bạn có chắc chắn muốn xóa hồ sơ này vĩnh viễn không?')) return;

    const res = await apiCall(`/api/submissions/${id}`, { method: 'DELETE' });
    if (res) {
        fetchSubmissions();
    }
}

const ADMIN_GENERATED_PAGINATION_ACTIONS = Object.freeze({
    fetchSubmissions: page => fetchSubmissions(page),
    fetchReviewSubmissions: page => fetchReviewSubmissions(page),
    fetchCompletedSubmissions: page => fetchCompletedSubmissions(page),
    fetchDocumentInventory: page => fetchDocumentInventory(page),
});

const ADMIN_GENERATED_CLICK_ACTIONS = Object.freeze({
    paginate: trigger => {
        const action = ADMIN_GENERATED_PAGINATION_ACTIONS[trigger.dataset.pageFunction];
        if (action) return action(Number(trigger.dataset.page));
        return undefined;
    },
    'edit-submission': trigger => editSubmission(Number(trigger.dataset.submissionId)),
    'copy-submission': trigger => copySubmission(Number(trigger.dataset.submissionId)),
    'delete-submission': trigger => deleteSubmission(Number(trigger.dataset.submissionId)),
    'reopen-submission': trigger => reopenSubmissionReview(Number(trigger.dataset.submissionId)),
    'show-assigned-folders': trigger => showAssignedFolders(Number(trigger.dataset.userId)),
    'revoke-reviewer-assignments': trigger => revokeAssignments(Number(trigger.dataset.userId), 'reviewer'),
});

if (typeof document.addEventListener === 'function') {
    document.addEventListener('click', event => {
        const trigger = event.target?.closest?.('[data-admin-generated-action]');
        const action = trigger && ADMIN_GENERATED_CLICK_ACTIONS[trigger.dataset.adminGeneratedAction];
        if (!action) return;
        if (trigger.matches('a[href="#"]')) event.preventDefault();
        action(trigger);
    });

    document.addEventListener('change', event => {
        const trigger = event.target?.closest?.('[data-admin-generated-change="toggle-submission-selection"]');
        if (trigger) toggleSubmissionSelection(Number(trigger.dataset.submissionId), trigger.checked);
    });
}
