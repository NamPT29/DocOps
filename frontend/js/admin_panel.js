
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
                <a class="page-link" href="#" onclick="${onPageClickFnName}(${pagination.page - 1})">Trước</a>
             </li>`;
    for (let i = 1; i <= pagination.total_pages; i++) {
        html += `<li class="page-item ${pagination.page === i ? 'active' : ''}">
                    <a class="page-link" href="#" onclick="${onPageClickFnName}(${i})">${i}</a>
                 </li>`;
    }
    html += `<li class="page-item ${pagination.page === pagination.total_pages ? 'disabled' : ''}">
                <a class="page-link" href="#" onclick="${onPageClickFnName}(${pagination.page + 1})">Sau</a>
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

    if (res.data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="text-center">Chưa có dữ liệu</td></tr>';
        renderSubmissionsPagination(res.pagination, 'submissionsPagination', fetchSubmissions);
        return;
    }

    res.data.forEach(sub => {
        const tr = document.createElement('tr');
        const safeId = Number(sub.id);
        const safeCreatedAt = escapeHTML(sub.created_at);
        const safeTemplate = escapeHTML(sub.template);
        const safeCreator = escapeHTML(sub.creator_name || 'Unknown');
        const safeReviewer = escapeHTML(sub.reviewer_name || 'Chưa phân công');
        const safePdfPath = escapeHTML(sub.pdf_relative_path || sub.pdf_filename || '');
        const canDelete = sub.status === 'draft' || (currentUser && currentUser.role === 'admin');
        const canSelect = sub.status === 'draft' || sub.status === 'rejected';
        if (canSelect) selectableSubmissionStatuses.set(safeId, sub.status);
        if (sub.has_errors || sub.status === 'rejected') {
            tr.classList.add('table-danger');
        }

        let statusBadge = '';
        if (sub.status === 'pending_review') statusBadge = '<span class="badge bg-warning text-dark"><i class="fas fa-hourglass-half"></i> Chờ duyệt</span>';
        else if (sub.status === 'rejected') statusBadge = '<span class="badge bg-danger"><i class="fas fa-times-circle"></i> Báo lỗi</span>';
        else if (sub.status === 'approved') statusBadge = '<span class="badge bg-success"><i class="fas fa-check-circle"></i> Đã duyệt</span>';
        else statusBadge = '<span class="badge bg-secondary"><i class="fas fa-save"></i> Lưu nháp</span>';

        tr.innerHTML = `
            <td class="text-center">
                ${canSelect ? `<input type="checkbox" class="form-check-input submission-select-checkbox" value="${safeId}" onchange="toggleSubmissionSelection(${safeId}, this.checked)" aria-label="Chọn hồ sơ ${safeId}">` : ''}
            </td>
            <td class="text-center fw-semibold">${Number(sub.serial_number) || ''}</td>
            <td><span class="badge bg-secondary">${safeTemplate}</span></td>
            <td class="text-nowrap">${safeCreatedAt}</td>
            <td style="min-width: 260px; max-width: 520px;">
                ${safePdfPath ? `<button type="button" class="btn btn-link btn-sm text-start text-break p-0" onclick="editSubmission(${safeId})" title="${safePdfPath}"><i class="fas fa-file-pdf text-danger me-1"></i>${safePdfPath}</button>` : '<span class="text-muted fst-italic">Không liên kết PDF</span>'}
            </td>
            <td><span class="badge bg-info text-dark"><i class="fas fa-user"></i> ${safeCreator}</span></td>
            <td><span class="badge bg-primary"><i class="fas fa-user-check"></i> ${safeReviewer}</span></td>
            <td class="text-center">${statusBadge}</td>
            <td style="min-width: 300px;">
                <div class="d-flex flex-wrap align-items-center gap-2">
                    <button class="btn btn-sm btn-outline-success" onclick="copySubmission(${safeId})">Nhân bản</button>
                    <button class="btn btn-sm btn-outline-primary" onclick="editSubmission(${safeId})">Xem/Sửa</button>
                    ${canDelete ? `<button class="btn btn-sm btn-outline-danger" onclick="deleteSubmission(${safeId})" title="${sub.status === 'draft' ? 'Xóa bản nháp' : 'Xóa hồ sơ'}">Xóa</button>` : ''}
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
    if (action !== 'delete') return;
    const actionLabel = 'xóa';
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
        if (title) title.textContent = 'Chọn một folder để xem hồ sơ đã duyệt';
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
    url.searchParams.set('status', 'approved');
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
        emptyMessage: 'Chưa có folder chứa hồ sơ đã duyệt.',
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
    previous.onclick = () => onPageChange(page - 1);
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
        if (sub.has_errors || sub.status === 'rejected') tr.classList.add('table-danger');

        let statusBadge = '';
        if (sub.status === 'pending_review') statusBadge = '<span class="badge bg-warning text-dark"><i class="fas fa-hourglass-half"></i> Chờ duyệt</span>';
        else if (sub.status === 'rejected') statusBadge = '<span class="badge bg-danger"><i class="fas fa-times-circle"></i> Báo lỗi</span>';
        else if (sub.status === 'approved') statusBadge = '<span class="badge bg-success"><i class="fas fa-check-circle"></i> Đã duyệt</span>';

        const reviewTarget = isReviewTab ? '' : ' target="_blank"';
        let actions = `<a class="btn btn-sm btn-outline-primary" href="${safeSubmissionUrl}"${reviewTarget} title="Mở để kiểm tra và chỉnh sửa"><i class="fas fa-search"></i> Kiểm tra/Sửa</a>`;
        if (sub.is_being_viewed || sub.viewing_user_name) {
            const viewerName = escapeHTML(sub.viewing_user_name || 'Người dùng khác');
            statusBadge += `<span class='badge bg-info text-dark ms-1'><i class='fas fa-eye'></i> Báo cáo đang có người xem: ${viewerName}</span>`;
        }
        if (isReviewTab) {
            actions += `<button class="btn btn-sm btn-success" onclick="approveSubmission(${safeId})" title="Duyệt hoàn thành hồ sơ này"><i class="fas fa-check"></i> Duyệt</button>`;
        }
        if (currentUser && currentUser.role === 'admin') {
            if (sub.status === 'approved') {
                actions += `<button class="btn btn-sm btn-outline-warning" onclick="reopenSubmissionReview(${safeId})" title="Chuyển hồ sơ đã duyệt về hàng chờ kiểm tra"><i class="fas fa-undo"></i> Về chờ duyệt</button>`;
            }
            actions += `<button class="btn btn-sm btn-outline-danger" onclick="deleteSubmission(${safeId})" title="Xóa hồ sơ"><i class="fas fa-trash"></i></button>`;
        }

        tr.innerHTML = `
            ${isReviewTab ? '' : `<td class="text-center fw-semibold">${Number(sub.serial_number) || ''}</td>`}
            <td><span class="badge bg-secondary">${safeTemplate}</span></td>
            <td class="text-nowrap">${safeCreatedAt}</td>
            <td style="min-width: 260px; max-width: 520px;">
                ${safePdfPath ? `<a class="text-break" href="${safeSubmissionUrl}"${reviewTarget} title="${safePdfPath}"><i class="fas fa-file-pdf text-danger me-1"></i>${safePdfPath}</a>` : '<span class="text-muted fst-italic">Không liên kết PDF</span>'}
            </td>
            <td><span class="badge bg-info text-dark"><i class="fas fa-user"></i> ${safeCreator}</span></td>
            <td class="text-center">${statusBadge}</td>
            <td style="min-width: 300px;"><div class="d-flex flex-wrap align-items-center gap-2">${actions}</div></td>
        `;
        tbody.appendChild(tr);
    });
    renderPagination();
}

async function approveSubmission(id) {
    const res = await apiCall(`/api/submissions/${id}/toggle_check`, { method: 'PUT' });
    if (res && res.status === 'ok') {
        fetchReviewSubmissions();
    }
}

async function reopenSubmissionReview(id) {
    if (!currentUser || currentUser.role !== 'admin') {
        alert('Chỉ admin được chuyển hồ sơ về chờ duyệt.');
        return;
    }
    if (!confirm('Chuyển hồ sơ đã duyệt này về trạng thái Chờ duyệt?')) return;

    const res = await apiCall(`/api/submissions/${id}/reopen-review`, { method: 'PUT' });
    if (res && res.status === 'ok') {
        await Promise.all([
            fetchReviewSubmissions(),
            fetchCompletedSubmissions(1, true),
        ]);
    }
}

async function toggleCheckSubmission(id, checkbox) {
    const res = await apiCall(`/api/submissions/${id}/toggle_check`, { method: 'PUT' });
    if (res && res.status === 'ok') {
        if (checkbox && typeof res.is_checked === 'boolean') checkbox.checked = res.is_checked;
        window.reviewApproved = res.is_checked === true;
        if (window.location.pathname.includes('admin.html')) {
            fetchReviewSubmissions();
            fetchCompletedSubmissions();
        } else {
            await refreshReviewNextAction();
        }
    } else {
        checkbox.checked = !checkbox.checked; // revert
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

function toggleFormCheck() {
    if (!currentEditingId) return;
    const checkbox = document.getElementById('adminFormCheckToggle');
    toggleCheckSubmission(currentEditingId, checkbox);
}

async function copySubmission(id) {
    if (!confirm('Bạn có chắc muốn nhân bản hồ sơ này? Bản sao sẽ được tạo ngay lập tức.')) return;
    const res = await apiCall(`/api/submissions/${id}/copy`, { method: 'POST' });
    if (res) {
        fetchSubmissions();
        if (res.new_id) {
            editSubmission(res.new_id, true);
        }
    }
}

let activeSubmissionViewId = null;
let submissionViewHeartbeat = null;

function bindSubmissionViewLifecycle() {
    if (typeof window === 'undefined' || window.__submissionViewLifecycleBound) return;
    window.__submissionViewLifecycleBound = true;
    window.addEventListener('pagehide', stopSubmissionView);
}

async function renewSubmissionView(submissionId) {
    if (activeSubmissionViewId !== submissionId) return;
    const response = await authFetch(`/api/submissions/${submissionId}/view`, { method: 'PUT' });
    if (!response || !response.ok) return;
    await response.json().catch(() => ({}));
}

async function startSubmissionView(submissionId) {
    const id = Number(submissionId);
    if (!Number.isInteger(id) || id <= 0) return;
    bindSubmissionViewLifecycle();
    if (activeSubmissionViewId !== id) stopSubmissionView();
    const response = await authFetch(`/api/submissions/${id}/view`, { method: 'PUT' });
    if (!response || !response.ok) return;
    await response.json().catch(() => ({}));
    activeSubmissionViewId = id;
    if (submissionViewHeartbeat) clearInterval(submissionViewHeartbeat);
    submissionViewHeartbeat = setInterval(() => renewSubmissionView(id), 30000);
}

function stopSubmissionView() {
    const id = activeSubmissionViewId;
    activeSubmissionViewId = null;
    if (submissionViewHeartbeat) clearInterval(submissionViewHeartbeat);
    submissionViewHeartbeat = null;
    if (!id || typeof fetch !== 'function') return;
    const headers = {};
    if (currentToken) headers.Authorization = `Bearer ${currentToken}`;
    fetch(`/api/submissions/${id}/view`, {
        method: 'DELETE',
        headers,
        keepalive: true,
    }).catch(() => { });
}

async function editSubmission(id, isCopied = false) {
    window.isCopiedSubmissionEdit = isCopied;
    const res = await apiCall(`/api/submissions/${id}`);
    if (!res) return;

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
        const inputs = document.querySelectorAll('#dataForm input[type="text"], #dataForm textarea, #dataForm select');
        const snap = {};
        inputs.forEach(input => snap[input.name] = input.value);
        window.originalEditingData = JSON.stringify(snap);
    }
    
    // Save initial cover data to detect modifications
    window.initialCoverData = {};
    if (window.activeTemplateConfig && window.activeTemplateConfig.cover_cols) {
        window.activeTemplateConfig.cover_cols.forEach(c => {
            const key = `col_${c-1}`;
            window.initialCoverData[key] = res.data[key] || '';
        });
    }

    // Set editing state
    currentEditingId = id;
    startSubmissionView(id);
    isEditingFromList = true;

    // Handle readonly state
    const actionBtns = document.getElementById('actionButtonsRow');
    const readonlyNotice = document.getElementById('readonlyNotice');
    const clearFormBtn = document.getElementById('clearFormBtn');

    const isAdmin = currentUser && currentUser.role === 'admin';
    const canReview = res.can_review === true;
    const reviewEditMode = canReview && (res.submission_status === 'pending_review' || res.submission_status === 'rejected');
    window.reviewEditMode = reviewEditMode;
    window.reviewApproved = canReview && (res.submission_status === 'approved' || res.is_checked === true);
    const isLocked = !isAdmin && !reviewEditMode && (res.submission_status === 'pending_review' || res.submission_status === 'approved');
    const canSubmitFromEnteredReport = !canReview && ['draft', 'rejected'].includes(res.submission_status);

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
            setSubmissionModeButtons(canSubmitFromEnteredReport, res.submission_status === 'rejected');
        }
    }

    document.getElementById('cancelEditBtn').classList.remove('d-none');

    // Error markers are stored per visible input. Legacy `_wrong_sections`
    // remains untouched in the record, but new reviews use `_wrong_fields`.
    const wrongFields = Array.isArray(data._wrong_fields) ? data._wrong_fields : [];
    document.querySelectorAll('.field-error-checkbox').forEach(cb => {
        const fieldContainer = cb.closest('.position-relative');
        cb.checked = canReview && wrongFields.includes(cb.dataset.field);
        if (fieldContainer) {
            fieldContainer.classList.toggle('border', cb.checked);
            fieldContainer.classList.toggle('border-danger', cb.checked);
            fieldContainer.classList.toggle('rounded', cb.checked);
            fieldContainer.classList.toggle('p-2', cb.checked);
            fieldContainer.classList.toggle('bg-danger', cb.checked);
            fieldContainer.classList.toggle('bg-opacity-10', cb.checked);
        }
    });

    if (canReview) {
        const adminCheckArea = document.getElementById('adminCheckArea');
        if (adminCheckArea) {
            adminCheckArea.classList.remove('d-none');
            document.getElementById('adminFormCheckToggle').checked = !!res.is_checked;
        }

        // Người kiểm tra được sửa nội dung, nhưng không được đổi luồng nộp duyệt.
        const draftBtn = document.getElementById('draftBtn');
        if (draftBtn) {
            draftBtn.classList.toggle('d-none', !reviewEditMode);
            draftBtn.innerHTML = '<i class="fas fa-save"></i> Lưu nội dung đã sửa';
        }
        const btnSubmit = document.getElementById('submitBtn');
        if (btnSubmit) btnSubmit.classList.add('d-none');
        if (actionBtns) actionBtns.classList.toggle('d-none', !reviewEditMode);
        if (readonlyNotice) {
            readonlyNotice.style.display = reviewEditMode ? 'none' : 'block';
            if (reviewEditMode) readonlyNotice.textContent = '';
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
            if (input.id !== 'adminFormCheckToggle' && !input.classList.contains('field-error-checkbox')) {
                input.disabled = !reviewEditMode;
            }
        });

        // Each visible field has its own internal error marker. Marking a field
        // keeps the report in review; the reviewer corrects the value directly.
        document.querySelectorAll('.review-field-error-check').forEach(el => el.classList.remove('d-none'));
        document.querySelectorAll('.field-error-checkbox').forEach(cb => {
            cb.disabled = !reviewEditMode;
            cb.onchange = async () => {
                if (!reviewEditMode) return;
                const wrongFields = Array.from(
                    document.querySelectorAll('.field-error-checkbox:checked'),
                    checkbox => checkbox.dataset.field,
                );

                // Toggle visual highlight
                const fieldContainer = cb.closest('.position-relative');
                if (fieldContainer) {
                    fieldContainer.classList.toggle('border', cb.checked);
                    fieldContainer.classList.toggle('border-danger', cb.checked);
                    fieldContainer.classList.toggle('rounded', cb.checked);
                    fieldContainer.classList.toggle('p-2', cb.checked);
                    fieldContainer.classList.toggle('bg-danger', cb.checked);
                    fieldContainer.classList.toggle('bg-opacity-10', cb.checked);
                }

                const savePromise = apiCall(`/api/submissions/${id}/errors`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        wrong_sections: Array.isArray(data._wrong_sections) ? data._wrong_sections : [],
                        wrong_fields: wrongFields,
                    })
                });
                window.reviewErrorSavePromise = savePromise;
                try {
                    await savePromise;
                } finally {
                    if (window.reviewErrorSavePromise === savePromise) {
                        window.reviewErrorSavePromise = null;
                    }
                }
            };
        });
    } else {
        // Error markers are internal review metadata, not a request for the
        // input user to re-enter the report.
        document.querySelectorAll('.review-field-error-check').forEach(el => {
            el.classList.add('d-none');
        });
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
        isPdfLinked = false;
    }
}

async function deleteSubmission(id) {
    if (!confirm('Bạn có chắc chắn muốn xóa hồ sơ này vĩnh viễn không?')) return;

    const res = await apiCall(`/api/submissions/${id}`, { method: 'DELETE' });
    if (res) {
        fetchSubmissions();
    }
}

// === POOL & ASSIGNMENT LOGIC ===
async function fetchDocumentStats() {
    // Populate templates dropdown for assignment
    if (typeof populateTemplatesDropdown === 'function') {
        populateTemplatesDropdown('assignTemplateSelect', false);
        populateTemplatesDropdown('inventoryTemplateFilter', true);
    }

    const [data, usersData, inventoryData] = await Promise.all([
        apiCall('/api/documents/stats'),
        apiCall('/api/users'),
        apiCall(`/api/documents/inventory?page=1&page_size=${inventoryPageSize}${document.getElementById('inventoryTemplateFilter')?.value ? `&template_id=${encodeURIComponent(document.getElementById('inventoryTemplateFilter').value)}` : ''}`),
    ]);
    renderDocumentInventory(inventoryData);
    if (data && data.status === 'ok') {
        const tbody = document.getElementById('poolStatsTableBody');
        const revocationTbody = document.getElementById('assignmentRevocationTableBody');
        const inputContainer = document.getElementById('assignInputUserCheckboxes');
        const reviewerContainer = document.getElementById('assignReviewerCheckboxes');
        if (tbody) tbody.innerHTML = '';
        if (revocationTbody) revocationTbody.innerHTML = '';
        if (inputContainer) inputContainer.innerHTML = '';
        if (reviewerContainer) reviewerContainer.innerHTML = '';

        if (data.user_stats.length === 0) {
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Chưa có nhân viên.</td></tr>';
            }
            if (revocationTbody) {
                revocationTbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Chưa có nhân viên.</td></tr>';
            }
            if (inputContainer) {
                inputContainer.innerHTML = '<span class="text-muted">Chưa có nhân viên để nhập liệu.</span>';
            }
        }

        data.user_stats.forEach(u => {
            const safeUserId = Number(u.user_id);
            const safeUsername = escapeHTML(u.username);
            const pending = Number(u.pending) || 0;
            const completed = Number(u.completed) || 0;
            const reviewPending = Number(u.review_pending) || 0;
            const totalAssigned = pending + completed;
            // Table
            if (tbody) {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${safeUsername}</td>
                    <td><span class="badge bg-warning text-dark fs-6">${pending}</span></td>
                    <td><span class="badge bg-success fs-6">${completed}</span></td>
                    <td><span class="badge bg-primary fs-6">${totalAssigned}</span></td>
                `;
                tbody.appendChild(tr);
            }

            if (revocationTbody) {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${safeUsername}</td>
                    <td><span class="badge bg-warning text-dark">${pending}</span></td>
                    <td><span class="badge bg-danger">${reviewPending}</span></td>
                    <td>
                        <div class="d-flex flex-wrap gap-2">
                            <button type="button" class="btn btn-sm btn-outline-primary" onclick="showAssignedFolders(${safeUserId})" ${pending === 0 ? 'disabled' : ''}>
                                <i class="fas fa-folder-open"></i> Tài liệu đã giao
                            </button>
                            <button type="button" class="btn btn-sm btn-outline-danger" onclick="revokeAssignments(${safeUserId}, 'reviewer')" ${reviewPending === 0 ? 'disabled' : ''}>
                                <i class="fas fa-user-check"></i> Thu hồi việc kiểm tra
                            </button>
                        </div>
                    </td>
                `;
                revocationTbody.appendChild(tr);
            }

            // Input assignee checkboxes
            if (inputContainer) {
                const div = document.createElement('div');
                div.className = 'form-check';
                div.innerHTML = `
                    <input class="form-check-input input-user-checkbox" type="checkbox" value="${safeUserId}" id="chkInputUser_${safeUserId}">
                    <label class="form-check-label" for="chkInputUser_${safeUserId}">
                        ${safeUsername} <span class="text-muted small">(Đã nhận: ${totalAssigned})</span>
                    </label>
                `;
                inputContainer.appendChild(div);
            }
        });

        const reviewerUsers = usersData && usersData.status === 'ok' ? usersData.data : [];
        if (reviewerContainer && reviewerUsers.length === 0) {
            reviewerContainer.innerHTML = '<span class="text-muted">Chưa có tài khoản để kiểm tra.</span>';
        }
        reviewerUsers.forEach(user => {
            if (!reviewerContainer) return;
            const safeUserId = Number(user.id);
            const safeUsername = escapeHTML(user.username);
            const roleLabel = user.role === 'admin' ? ' <span class="badge bg-danger">Admin</span>' : '';
            const div = document.createElement('div');
            div.className = 'form-check';
            div.innerHTML = `
                <input class="form-check-input reviewer-user-checkbox" type="checkbox" value="${safeUserId}" id="chkReviewer_${safeUserId}">
                <label class="form-check-label" for="chkReviewer_${safeUserId}">${safeUsername}${roleLabel}</label>
            `;
            reviewerContainer.appendChild(div);
        });
    }
}

let inventorySelectedFolder = '';
let inventoryPageSize = 20;

async function fetchDocumentInventory(page = 1, folderPath = inventorySelectedFolder) {
    const filter = document.getElementById('inventoryTemplateFilter');
    const templateId = filter?.value;
    const params = new URLSearchParams({ page: String(page), page_size: String(inventoryPageSize) });
    if (templateId) params.set('template_id', templateId);
    if (folderPath) params.set('folder_path', folderPath);
    const data = await apiCall(`/api/documents/inventory?${params.toString()}`);
    renderDocumentInventory(data);
}

function renderDocumentInventory(payload) {
    const summary = document.getElementById('inventorySummary');
    const tbody = document.getElementById('inventoryDocumentsTableBody');
    const tree = document.getElementById('inventoryFolderTree');
    const pagination = document.getElementById('inventoryDocumentsPagination');
    if (!tbody) return;
    const items = payload && payload.status === 'ok' && Array.isArray(payload.data)
        ? payload.data
        : [];
    const totals = payload?.summary || { total: items.length, stored: 0, missing: 0 };
    const folders = Array.isArray(payload?.folders) ? payload.folders : [];
    const selectedFolder = payload?.selected_folder || '';
    if (selectedFolder && selectedFolder !== inventorySelectedFolder) {
        inventorySelectedFolder = selectedFolder;
    }
    if (tree) {
        tree.replaceChildren();
        folders.forEach(folder => {
            const button = document.createElement('button');
            button.type = 'button';
            const depth = folder.folder_path === '__ROOT__'
                ? 0
                : String(folder.folder_path || '').split('/').filter(Boolean).length;
            const isActive = folder.folder_path === inventorySelectedFolder;
            button.className = `list-group-item list-group-item-action d-flex justify-content-between align-items-center py-2 ${isActive ? 'active' : ''}`;
            button.style.paddingLeft = `${0.75 + Math.min(depth, 12) * 1.15}rem`;
            button.title = folder.folder_path || '';
            button.innerHTML = `<span class="text-break text-truncate"><i class="fas fa-folder${isActive ? '-open' : ''} me-2"></i>${escapeHTML(folder.folder_name || folder.folder_path)}</span><span class="badge ${isActive ? 'bg-light text-primary' : 'bg-secondary'}">${Number(folder.document_count) || 0}</span>`;
            button.onclick = () => {
                inventorySelectedFolder = folder.folder_path;
                fetchDocumentInventory(1, inventorySelectedFolder);
            };
            tree.appendChild(button);
        });
        if (!folders.length) tree.innerHTML = '<div class="text-center text-muted p-3">Kho chưa có folder.</div>';
    }
    const selectedTitle = document.getElementById('inventorySelectedFolder');
    if (selectedTitle) selectedTitle.textContent = selectedFolder ? `Folder: ${selectedFolder === '__ROOT__' ? 'Thư mục gốc' : selectedFolder}` : 'Kho chưa có folder';
    if (summary) {
        summary.innerHTML = `
            <span class="badge bg-primary">Tổng tài liệu: ${Number(totals.total) || 0}</span>
            <span class="badge bg-success">Đã lưu: ${Number(totals.stored) || 0}</span>
            <span class="badge bg-danger">Thiếu file: ${Number(totals.missing) || 0}</span>
        `;
    }
    tbody.replaceChildren();
    if (!items.length) {
        const row = document.createElement('tr');
        row.innerHTML = '<td colspan="7" class="text-center text-muted py-4">Kho chưa có tài liệu.</td>';
        tbody.appendChild(row);
        return;
    }
    items.forEach(item => {
        const row = document.createElement('tr');
        const status = item.storage_exists
            ? '<span class="badge bg-success">Có file</span>'
            : '<span class="badge bg-danger">Thiếu file</span>';
        row.innerHTML = `
            <td>${escapeHTML(item.filename || '')}<div class="small text-muted">#${Number(item.id) || ''}</div></td>
            <td class="text-break small">${escapeHTML(item.relative_path || '')}</td>
            <td class="text-break small font-monospace">${escapeHTML(item.source_path || '')}</td>
            <td class="text-break small font-monospace">${escapeHTML(item.storage_path || '')}</td>
            <td>${escapeHTML(item.assigned_to || 'Chưa giao')}</td>
            <td>${escapeHTML(item.status || '')}</td>
            <td>${status}</td>
        `;
        tbody.appendChild(row);
    });
    const page = Number(payload?.pagination?.page) || 1;
    const total = Number(payload?.pagination?.total) || 0;
    renderSubmissionsPagination(
        total ? {
            ...payload.pagination,
            from: (page - 1) * inventoryPageSize + 1,
            to: Math.min(page * inventoryPageSize, total),
        } : null,
        'inventoryDocumentsPagination',
        nextPage => fetchDocumentInventory(nextPage, inventorySelectedFolder),
        {
            pageSize: inventoryPageSize,
            onPageSizeChange: size => {
                inventoryPageSize = size;
                fetchDocumentInventory(1, inventorySelectedFolder);
            },
        },
    );
}

let assignedFoldersUserId = null;

async function showAssignedFolders(userId) {
    assignedFoldersUserId = Number(userId);
    const title = document.getElementById('assignedFoldersModalTitle');
    const list = document.getElementById('assignedFoldersList');
    const statusDiv = document.getElementById('assignedFoldersStatus');
    if (title) title.textContent = 'Tài liệu đã giao';
    if (list) list.innerHTML = '<div class="text-center text-muted py-3"><i class="fas fa-spinner fa-spin"></i> Đang tải folder...</div>';
    if (statusDiv) statusDiv.innerHTML = '';

    const modalElement = document.getElementById('assignedFoldersModal');
    if (modalElement) bootstrap.Modal.getOrCreateInstance(modalElement).show();
    await loadAssignedFolders();
}

async function loadAssignedFolders() {
    if (!Number.isInteger(assignedFoldersUserId) || assignedFoldersUserId <= 0) return;
    const list = document.getElementById('assignedFoldersList');
    const title = document.getElementById('assignedFoldersModalTitle');
    const data = await apiCall(
        `/api/documents/assignments/folders?user_id=${encodeURIComponent(assignedFoldersUserId)}`,
        {},
        'Không thể tải danh sách folder đã giao',
    );
    if (!data) {
        if (list) list.innerHTML = '<div class="alert alert-danger mb-0">Không thể tải danh sách folder.</div>';
        return;
    }
    if (title) title.textContent = `Tài liệu đã giao - ${data.username || ''}`;
    renderAssignedFolders(Array.isArray(data.data) ? data.data : []);
}

function renderAssignedFolders(folders) {
    const list = document.getElementById('assignedFoldersList');
    if (!list) return;
    list.replaceChildren();
    if (folders.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'text-center text-muted py-4';
        empty.textContent = 'Nhân viên chưa có folder nào đang chờ nhập.';
        list.appendChild(empty);
        return;
    }

    folders.forEach(folder => {
        const item = document.createElement('div');
        item.className = 'list-group-item d-flex justify-content-between align-items-center gap-3';

        const info = document.createElement('div');
        info.className = 'min-w-0';
        const name = document.createElement('div');
        name.className = 'fw-semibold text-break';
        name.textContent = folder.folder_name || folder.folder_path;
        const path = document.createElement('div');
        path.className = 'small text-muted text-break';
        path.textContent = folder.folder_path;
        const counts = document.createElement('div');
        counts.className = 'small mt-1';
        counts.textContent = `${Number(folder.document_count) || 0} tài liệu`;
        if (Number(folder.submission_count) > 0) {
            counts.textContent += ` • ${Number(folder.submission_count)} hồ sơ đã có`;
        }
        info.append(name, path, counts);

        const button = document.createElement('button');
        button.type = 'button';
        button.className = folder.can_revoke
            ? 'btn btn-sm btn-outline-danger flex-shrink-0'
            : 'btn btn-sm btn-outline-secondary flex-shrink-0';
        button.disabled = !folder.can_revoke;
        button.textContent = folder.can_revoke ? 'Thu hồi' : 'Đã có hồ sơ';
        if (folder.can_revoke) {
            button.onclick = () => revokeAssignments(
                assignedFoldersUserId,
                'input',
                folder.folder_path,
            );
        }
        item.append(info, button);
        list.appendChild(item);
    });
}

async function revokeAssignments(userId, assignmentType, folderPath = null) {
    const isInput = assignmentType === 'input';
    if (isInput && !folderPath) return;
    const confirmation = isInput
        ? `Thu hồi folder "${folderPath}" khỏi nhân viên này?`
        : 'Thu hồi toàn bộ việc kiểm tra đang hoạt động của nhân viên này?';
    if (!confirm(confirmation)) return;

    const statusDiv = document.getElementById(
        isInput ? 'assignedFoldersStatus' : 'revokeAssignmentStatus'
    );
    if (statusDiv) {
        statusDiv.innerHTML = '<div class="alert alert-info"><i class="fas fa-spinner fa-spin"></i> Đang thu hồi công việc...</div>';
    }
    const data = await apiCall('/api/documents/assignments/revoke', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            user_id: Number(userId),
            assignment_type: assignmentType,
            ...(isInput ? { folder_path: folderPath } : {}),
        }),
    }, 'Không thể thu hồi công việc');
    if (!data) {
        if (statusDiv) statusDiv.innerHTML = '';
        return;
    }

    const message = isInput
        ? `Đã thu hồi folder (${Number(data.input_revoked) || 0} tài liệu).`
        : `Đã gỡ ${Number(data.review_reservations_revoked) || 0} lượt kiểm tra chưa nộp và chuyển ${Number(data.reviews_transferred_to_admin) || 0} hồ sơ về admin. ${Number(data.reviews_blocked) || 0} hồ sơ được giữ nguyên để tránh admin tự duyệt.`;
    if (statusDiv) {
        statusDiv.innerHTML = `<div class="alert alert-success">${escapeHTML(message)}</div>`;
    }
    invalidateUsersCache();
    if (isInput) await loadAssignedFolders();
    await fetchDocumentStats();
    if (typeof fetchAdminData === 'function') await fetchAdminData();
}

let reviewerReassignmentFolders = [];
let reviewerReassignmentUsers = [];

async function fetchReviewerReassignmentData() {
    const reviewerContainer = document.getElementById('reassignReviewerCheckboxes');
    const statusDiv = document.getElementById('reassignReviewerStatus');
    if (!reviewerContainer) return;
    reviewerContainer.innerHTML = '<span class="text-muted">Đang tải người kiểm tra...</span>';
    if (statusDiv) statusDiv.innerHTML = '';

    const [folderData, usersData] = await Promise.all([
        apiCall('/api/documents/reviewer-folder-assignments'),
        apiCall('/api/users'),
    ]);
    if (!folderData || !usersData) return;
    reviewerReassignmentFolders = Array.isArray(folderData.data) ? folderData.data : [];
    reviewerReassignmentUsers = Array.isArray(usersData.data) ? usersData.data : [];

    const summary = document.getElementById('reassignReviewerSummary');
    if (summary) {
        const activeDocuments = reviewerReassignmentFolders.reduce(
            (total, folder) => total + (Number(folder.active_document_count) || 0),
            0,
        );
        summary.textContent = `${Number(folderData.folder_count) || 0} folder đang có công việc kiểm tra (${activeDocuments} tài liệu/hồ sơ hoạt động).`;
    }
    renderReviewerReassignmentUsers();
}

function renderReviewerReassignmentUsers() {
    const reviewerContainer = document.getElementById('reassignReviewerCheckboxes');
    const preview = document.getElementById('reviewerFolderReassignmentPreview');
    const submitButton = document.getElementById('btnReassignDocumentReviewer');
    if (!reviewerContainer) return;
    reviewerContainer.innerHTML = '';
    reviewerReassignmentUsers.forEach(user => {
        const wrapper = document.createElement('div');
        wrapper.className = 'form-check py-1';
        const userId = Number(user.id);
        wrapper.innerHTML = `
            <input class="form-check-input reassign-reviewer-checkbox" type="checkbox" value="${userId}" id="reassignReviewer_${userId}">
            <label class="form-check-label" for="reassignReviewer_${userId}">${escapeHTML(user.username)}${user.role === 'admin' ? ' <span class="badge bg-danger">Admin</span>' : ''}</label>`;
        reviewerContainer.appendChild(wrapper);
    });
    if (!reviewerReassignmentUsers.length) {
        reviewerContainer.innerHTML = '<span class="text-muted">Không có tài khoản phù hợp.</span>';
    }
    if (preview) {
        preview.innerHTML = reviewerReassignmentFolders.length
            ? reviewerReassignmentFolders.map(folder => {
                const reviewers = (folder.reviewer_usernames || []).join(', ') || 'Chưa phân công';
                const inputs = (folder.input_usernames || []).join(', ') || 'Không xác định';
                const activeCount = Number(folder.active_submission_count) || 0;
                const canReassign = true;
                return `<label class="d-flex gap-2 align-items-start border-bottom py-2"><input type="checkbox" class="form-check-input reassign-folder-checkbox mt-1" value="${escapeHTML(folder.folder_path)}"><span class="text-break"><i class="fas fa-folder text-warning me-1"></i><strong>${escapeHTML(folder.folder_path)}</strong><br><span class="small">Người nhập: ${escapeHTML(inputs)} · hiện kiểm tra: ${escapeHTML(reviewers)}</span><br><span class="small text-success">${activeCount > 0 ? `Sẽ chuyển giao ${activeCount} hồ sơ đang kiểm tra` : 'Chưa có hồ sơ được kiểm tra'}</span></span></label>`;
            }).join('')
            : '<span class="text-muted">Không có folder đang hoạt động để chia lại.</span>';
    }
    if (submitButton) submitButton.disabled = reviewerReassignmentFolders.length === 0;
}

function toggleAllReviewerFolders() {
    const checkboxes = [...document.querySelectorAll('.reassign-folder-checkbox:not(:disabled)')];
    const selectAll = checkboxes.some(checkbox => !checkbox.checked);
    checkboxes.forEach(checkbox => { checkbox.checked = selectAll; });
    const button = document.getElementById('toggleAllReviewerFoldersBtn');
    if (button) button.innerHTML = selectAll
        ? '<i class="fas fa-times"></i> Bỏ chọn toàn bộ'
        : '<i class="fas fa-check-double"></i> Chọn toàn bộ folder';
}

async function reassignDocumentReviewer() {
    const statusDiv = document.getElementById('reassignReviewerStatus');
    const reviewerUserIds = [...document.querySelectorAll('.reassign-reviewer-checkbox:checked')]
        .map(checkbox => Number(checkbox.value))
        .filter(Boolean);
    const folderPaths = [...document.querySelectorAll('.reassign-folder-checkbox:checked')]
        .map(checkbox => checkbox.value)
        .filter(Boolean);
    if (!reviewerUserIds.length) {
        if (statusDiv) statusDiv.innerHTML = '<div class="alert alert-warning">Vui lòng chọn ít nhất một người kiểm tra.</div>';
        return;
    }
    if (!folderPaths.length) {
        if (statusDiv) statusDiv.innerHTML = '<div class="alert alert-warning">Vui lòng chọn ít nhất một folder chưa được kiểm tra.</div>';
        return;
    }
    if (!confirm(`Tự chia đều ${folderPaths.length} folder kiểm tra cho ${reviewerUserIds.length} người đã chọn?`)) return;

    const result = await apiCall('/api/documents/reviewer-folders/redistribute', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reviewer_user_ids: reviewerUserIds, folder_paths: folderPaths }),
    }, 'Không thể tự phân lại folder kiểm tra');
    if (!result) return;
    if (statusDiv) {
        const details = (result.distribution || [])
            .map(item => `${escapeHTML(item.reviewer_username)}: ${Number(item.folder_count) || 0} folder`)
            .join(' · ');
        statusDiv.innerHTML = `<div class="alert alert-success">Đã tự chia ${Number(result.folder_count) || 0} folder. ${details}. Người nhập, bản nháp và trạng thái hồ sơ không thay đổi.</div>`;
    }
    await fetchReviewerReassignmentData();
    await fetchDocumentStats();
}

const serverFolderBrowserState = {
    currentRelativePath: '',
    parentRelativePath: null,
    scan: null,
    activeJobId: null,
};

function resetServerFolderScan() {
    serverFolderBrowserState.scan = null;
    const levelSelect = document.getElementById('assignmentFolderLevel');
    const summary = document.getElementById('serverFolderScanSummary');
    const preview = document.getElementById('serverFolderPreview');
    if (levelSelect) {
        levelSelect.replaceChildren(new Option('Quét thư mục trước', ''));
        levelSelect.disabled = true;
    }
    if (summary) summary.textContent = 'Chưa quét thư mục.';
    if (preview) {
        preview.replaceChildren();
        preview.style.display = 'none';
    }
}

async function loadServerSourceFolders(relativePath = null) {
    const requestedPath = relativePath === null
        ? serverFolderBrowserState.currentRelativePath
        : relativePath;
    const list = document.getElementById('serverFolderList');
    if (!list) return;
    list.replaceChildren(new Option('Đang tải danh sách folder...', ''));

    try {
        const res = await authFetch(
            `/api/documents/server-folders?path=${encodeURIComponent(requestedPath || '')}`
        );
        if (!res) return;
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.status !== 'ok') {
            throw new Error(formatApiErrorDetail(data.detail || data.message || `HTTP ${res.status}`));
        }

        serverFolderBrowserState.currentRelativePath = data.current_relative_path || '';
        serverFolderBrowserState.parentRelativePath = data.parent_relative_path;
        const rootLabel = document.getElementById('serverSourceRoot');
        rootLabel.textContent = `Thư mục nguồn cho phép: ${data.root_path}`;
        rootLabel.className = 'form-text text-break mb-1';
        document.getElementById('serverSourcePath').value = data.current_relative_path || '(thư mục gốc)';
        list.replaceChildren();
        data.directories.forEach(directory => {
            const option = new Option(`📁 ${directory.name}`, directory.relative_path);
            list.appendChild(option);
        });
        if (data.directories.length === 0) {
            list.appendChild(new Option('(Không có folder con)', ''));
        }
        resetServerFolderScan();
    } catch (error) {
        list.replaceChildren(new Option(`Lỗi: ${error.message}`, ''));
        const rootLabel = document.getElementById('serverSourceRoot');
        if (rootLabel) {
            rootLabel.textContent = `${error.message}. Hãy cấu hình DOCUMENT_SOURCE_ROOT trên máy chủ.`;
            rootLabel.className = 'form-text text-danger text-break mb-1';
        }
    }
}

function openSelectedServerFolder() {
    const selectedPath = document.getElementById('serverFolderList')?.value;
    if (selectedPath) loadServerSourceFolders(selectedPath);
}

function goToParentServerFolder() {
    const parent = serverFolderBrowserState.parentRelativePath;
    if (parent !== null && parent !== undefined) loadServerSourceFolders(parent);
}

async function scanSelectedServerFolder() {
    const summaryElement = document.getElementById('serverFolderScanSummary');
    const preview = document.getElementById('serverFolderPreview');
    const levelSelect = document.getElementById('assignmentFolderLevel');
    summaryElement.textContent = 'Đang quét tài liệu trên máy chủ...';
    levelSelect.disabled = true;

    try {
        const res = await authFetch('/api/documents/server-folder/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                relative_path: serverFolderBrowserState.currentRelativePath,
            }),
        });
        if (!res) return;
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.status !== 'ok') {
            throw new Error(formatApiErrorDetail(data.detail || data.message || `HTTP ${res.status}`));
        }
        serverFolderBrowserState.scan = data;
        summaryElement.className = 'text-muted small mt-2';
        summaryElement.textContent = `Tìm thấy ${data.total_files} tài liệu; độ sâu folder lớn nhất: ${data.max_folder_depth}.`;

        levelSelect.replaceChildren(new Option('-- Chọn cấp folder --', ''));
        data.grouping_levels.forEach(item => {
            const examples = item.examples.length ? ` — VD: ${item.examples.join(', ')}` : '';
            levelSelect.appendChild(
                new Option(`Cấp ${item.level}: ${item.group_count} nhóm${examples}`, item.level)
            );
        });
        levelSelect.disabled = data.total_files === 0;

        preview.replaceChildren();
        data.preview.forEach(relativePath => {
            const row = document.createElement('div');
            row.className = 'text-truncate';
            row.title = relativePath;
            row.textContent = relativePath;
            preview.appendChild(row);
        });
        if (data.preview_truncated) {
            const more = document.createElement('div');
            more.className = 'text-muted fst-italic mt-1';
            more.textContent = 'Danh sách xem trước đã được rút gọn.';
            preview.appendChild(more);
        }
        preview.style.display = data.preview.length ? 'block' : 'none';
    } catch (error) {
        serverFolderBrowserState.scan = null;
        summaryElement.textContent = `Lỗi quét folder: ${error.message}`;
        summaryElement.className = 'text-danger small mt-2';
    }
}

function renderServerImportJob(job) {
    const statusDiv = document.getElementById('uploadAssignStatus');
    const alertBox = document.createElement('div');
    const terminal = ['completed', 'completed_with_errors', 'failed'].includes(job.state);
    alertBox.className = `alert ${job.state === 'completed' ? 'alert-success' : terminal ? 'alert-warning' : 'alert-info'}`;
    const summary = document.createElement('div');
    summary.className = 'fw-bold';
    summary.textContent = `Đã xử lý ${job.processed_files}/${job.total_files} — nhập mới ${job.imported_files}, đã có (chia lại nếu đang chờ) ${job.skipped_files}, lỗi ${job.failed_files}`;
    alertBox.appendChild(summary);
    if (job.current_path) {
        const current = document.createElement('div');
        current.className = 'small text-truncate mt-1';
        current.title = job.current_path;
        current.textContent = job.current_path;
        alertBox.appendChild(current);
    }
    if (job.error_message) {
        const error = document.createElement('div');
        error.className = 'small text-danger mt-1';
        error.textContent = job.error_message;
        alertBox.appendChild(error);
    }
    statusDiv.replaceChildren(alertBox);
}

async function pollServerImportJob(jobId) {
    const res = await authFetch(`/api/documents/server-folder/jobs/${jobId}`);
    if (!res) return;
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.status !== 'ok') {
        throw new Error(data.detail || data.message || `HTTP ${res.status}`);
    }
    renderServerImportJob(data.job);
    if (['completed', 'completed_with_errors', 'failed'].includes(data.job.state)) {
        serverFolderBrowserState.activeJobId = null;
        document.getElementById('btnUploadAssign').disabled = false;
        fetchDocumentStats();
        return;
    }
    window.setTimeout(() => {
        pollServerImportJob(jobId).catch(error => {
            document.getElementById('uploadAssignStatus').textContent = `Lỗi theo dõi tiến độ: ${error.message}`;
            document.getElementById('btnUploadAssign').disabled = false;
        });
    }, 1000);
}

async function uploadAndAssign() {
    const templateId = document.getElementById('assignTemplateSelect').value;
    const groupingLevel = document.getElementById('assignmentFolderLevel').value;
    const statusDiv = document.getElementById('uploadAssignStatus');
    const btn = document.getElementById('btnUploadAssign');
    const inputCheckboxes = document.querySelectorAll('.input-user-checkbox:checked');
    const reviewerCheckboxes = document.querySelectorAll('.reviewer-user-checkbox:checked');
    const inputUserIds = Array.from(inputCheckboxes).map(chk => parseInt(chk.value));
    const reviewerUserIds = Array.from(reviewerCheckboxes).map(chk => parseInt(chk.value));

    if (!templateId) {
        alert('Vui lòng chọn 1 Biểu mẫu.');
        return;
    }
    if (!serverFolderBrowserState.scan) {
        alert('Vui lòng quét thư mục nguồn trên máy chủ trước.');
        return;
    }
    if (!groupingLevel) {
        alert('Vui lòng chọn cấp folder để phân việc.');
        return;
    }
    if (inputUserIds.length === 0) {
        alert('Vui lòng chọn ít nhất 1 người nhập.');
        return;
    }
    if (reviewerUserIds.length === 0) {
        alert('Vui lòng chọn ít nhất 1 người kiểm tra.');
        return;
    }
    if (inputUserIds.some(inputId => !reviewerUserIds.some(reviewerId => reviewerId !== inputId))) {
        alert('Mỗi người nhập phải có ít nhất 1 người kiểm tra khác họ.');
        return;
    }

    btn.disabled = true;
    statusDiv.innerHTML = '<div class="alert alert-info"><i class="fas fa-spinner fa-spin"></i> Đang tự động phân công tài liệu...</div>';
    try {
        const res = await authFetch('/api/documents/server-folder/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                template_id: parseInt(templateId),
                input_user_ids: inputUserIds,
                reviewer_user_ids: reviewerUserIds,
                relative_path: serverFolderBrowserState.currentRelativePath,
                grouping_level: parseInt(groupingLevel),
            }),
        });
        if (!res) return;
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.status !== 'ok') {
            throw new Error(formatApiErrorDetail(data.detail || data.message || `HTTP ${res.status}`));
        }
        serverFolderBrowserState.activeJobId = data.job_id;
        await pollServerImportJob(data.job_id);
    } catch (error) {
        statusDiv.innerHTML = `<div class="alert alert-danger">${escapeHTML(error.message)}</div>`;
        btn.disabled = false;
    }
}
