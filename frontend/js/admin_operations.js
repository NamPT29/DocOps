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
                            <button type="button" class="btn btn-sm btn-outline-primary" data-admin-generated-action="show-assigned-folders" data-user-id="${safeUserId}" ${pending === 0 ? 'disabled' : ''}>
                                <i class="fas fa-folder-open"></i> Tài liệu đã giao
                            </button>
                            <button type="button" class="btn btn-sm btn-outline-danger" data-admin-generated-action="revoke-reviewer-assignments" data-user-id="${safeUserId}" ${reviewPending === 0 ? 'disabled' : ''}>
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

        const reviewerUsers = usersData && usersData.status === 'ok'
            ? usersData.data.filter(user => user.role !== 'admin')
            : [];
        if (reviewerContainer && reviewerUsers.length === 0) {
            reviewerContainer.innerHTML = '<span class="text-muted">Chưa có tài khoản để kiểm tra.</span>';
        }
        reviewerUsers.forEach(user => {
            if (!reviewerContainer) return;
            const safeUserId = Number(user.id);
            const safeUsername = escapeHTML(user.username);
            const div = document.createElement('div');
            div.className = 'form-check';
            div.innerHTML = `
                <input class="form-check-input reviewer-user-checkbox" type="checkbox" value="${safeUserId}" id="chkReviewer_${safeUserId}">
                <label class="form-check-label" for="chkReviewer_${safeUserId}">${safeUsername}</label>
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
            const pdfRange = item.min_pdf_count === item.max_pdf_count
                ? `${item.min_pdf_count} PDF/nhóm`
                : `${item.min_pdf_count}–${item.max_pdf_count} PDF/nhóm`;
            levelSelect.appendChild(
                new Option(
                    `Cấp ${item.level}: ${item.group_count} nhóm; ${pdfRange}; TB ${item.average_pdf_count}${examples}`,
                    item.level
                )
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

