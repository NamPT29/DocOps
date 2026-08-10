async function fetchSubmissions() {
    let url = new URL('/api/submissions', window.location.origin);
    
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
        tbody.innerHTML = '<tr><td colspan="5" class="text-center">Chưa có dữ liệu</td></tr>';
        return;
    }
    
    res.data.forEach(sub => {
        const tr = document.createElement('tr');
        if (sub.has_errors || sub.status === 'rejected') {
            tr.classList.add('table-danger');
        }
        
        let statusBadge = '';
        if (sub.status === 'pending_review') statusBadge = '<span class="badge bg-warning text-dark"><i class="fas fa-hourglass-half"></i> Chờ duyệt</span>';
        else if (sub.status === 'rejected') statusBadge = '<span class="badge bg-danger"><i class="fas fa-times-circle"></i> Báo lỗi</span>';
        else if (sub.status === 'approved') statusBadge = '<span class="badge bg-success"><i class="fas fa-check-circle"></i> Đã duyệt</span>';
        else statusBadge = '<span class="badge bg-secondary"><i class="fas fa-save"></i> Lưu nháp</span>';
        
        tr.innerHTML = `
            <td>${sub.id}</td>
            <td>${sub.created_at}</td>
            <td class="fw-bold text-primary">${sub.ho_ten}</td>
            <td>${sub.so_giay_to}</td>
            <td><span class="badge bg-secondary">${sub.template}</span></td>
            <td>
                ${sub.pdf_filename ? `<span class="badge bg-success" style="cursor: pointer;" onclick="editSubmission(${sub.id})" title="Nhấn để xem PDF và sửa hồ sơ">${sub.pdf_filename}</span>` : '<span class="text-muted fst-italic">Không</span>'}
            </td>
            <td class="text-center">${statusBadge}</td>
            <td>
                <button class="btn btn-sm btn-outline-success me-1" onclick="copySubmission(${sub.id})">Nhân bản</button>
                <button class="btn btn-sm btn-outline-primary me-1" onclick="editSubmission(${sub.id})">Xem/Sửa</button>
                <button class="btn btn-sm btn-outline-danger" onclick="deleteSubmission(${sub.id})">Xóa</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

async function fetchReviewSubmissions() {
    let url = new URL('/api/submissions', window.location.origin);
    url.searchParams.append('status', 'pending_review,rejected');
    const filterTid = document.getElementById('filterReviewTemplateId');
    if (filterTid && filterTid.value) url.searchParams.append('template_id', filterTid.value);
    const res = await apiCall(url.toString());
    if (!res) return;
    renderAdminSubmissionsTable(res.data, 'reviewTableBody', true);
}

async function fetchCompletedSubmissions() {
    let url = new URL('/api/submissions', window.location.origin);
    url.searchParams.append('status', 'approved');
    const filterTid = document.getElementById('filterTemplateId');
    if (filterTid && filterTid.value) url.searchParams.append('template_id', filterTid.value);
    const startDate = document.getElementById('filterStartDate');
    if (startDate && startDate.value) url.searchParams.append('start_date', startDate.value);
    const endDate = document.getElementById('filterEndDate');
    if (endDate && endDate.value) url.searchParams.append('end_date', endDate.value);
    const res = await apiCall(url.toString());
    if (!res) return;
    renderAdminSubmissionsTable(res.data, 'submissionsTableBody', false);
}

function renderAdminSubmissionsTable(data, tbodyId, isReviewTab) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    tbody.innerHTML = '';
    if (data.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="text-center">Chưa có dữ liệu</td></tr>`;
        return;
    }
    data.forEach(sub => {
        const tr = document.createElement('tr');
        if (sub.has_errors || sub.status === 'rejected') tr.classList.add('table-danger');
        
        let statusBadge = '';
        if (sub.status === 'pending_review') statusBadge = '<span class="badge bg-warning text-dark"><i class="fas fa-hourglass-half"></i> Chờ duyệt</span>';
        else if (sub.status === 'rejected') statusBadge = '<span class="badge bg-danger"><i class="fas fa-times-circle"></i> Báo lỗi</span>';
        else if (sub.status === 'approved') statusBadge = '<span class="badge bg-success"><i class="fas fa-check-circle"></i> Đã duyệt</span>';
        
        let actions = `<a class="btn btn-sm btn-outline-primary me-1" href="index.html?check_id=${sub.id}" target="_blank" title="Mở trong tab mới để kiểm tra chi tiết"><i class="fas fa-search"></i> Kiểm tra</a>`;
        if (isReviewTab) {
            actions += `<button class="btn btn-sm btn-success me-1" onclick="approveSubmission(${sub.id})" title="Duyệt hoàn thành hồ sơ này"><i class="fas fa-check"></i> Duyệt</button>`;
        }
        actions += `<button class="btn btn-sm btn-outline-danger" onclick="deleteSubmission(${sub.id})" title="Xóa hồ sơ"><i class="fas fa-trash"></i></button>`;

        tr.innerHTML = `
            <td>${sub.id}</td>
            <td>${sub.created_at}</td>
            <td><span class="badge bg-info text-dark"><i class="fas fa-user"></i> ${sub.creator_name || 'Unknown'}</span></td>
            <td class="fw-bold text-primary">${sub.ho_ten}</td>
            <td>${sub.so_giay_to}</td>
            <td><span class="badge bg-secondary">${sub.template}</span></td>
            <td>${statusBadge}</td>
            <td>${actions}</td>
        `;
        tbody.appendChild(tr);
    });
}

async function approveSubmission(id) {
    const res = await apiCall(`/api/submissions/${id}/toggle_check`, { method: 'PUT' });
    if (res && res.status === 'ok') {
        fetchReviewSubmissions();
    }
}

async function toggleCheckSubmission(id, checkbox) {
    const res = await apiCall(`/api/submissions/${id}/toggle_check`, { method: 'PUT' });
    if (res && res.status === 'ok') {
        if (window.location.pathname.includes('admin.html')) {
            fetchReviewSubmissions();
            fetchCompletedSubmissions();
        }
    } else {
        checkbox.checked = !checkbox.checked; // revert
    }
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
            editSubmission(res.new_id);
        }
    }
}

async function editSubmission(id) {
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
    
    // Set editing state
    currentEditingId = id;
    isEditingFromList = true;
    
    // Handle readonly state
    const actionBtns = document.getElementById('actionButtonsRow');
    const readonlyNotice = document.getElementById('readonlyNotice');
    const clearFormBtn = document.getElementById('clearFormBtn');
    
    const isAdmin = currentUser && currentUser.role === 'admin';
    const isLocked = !isAdmin && (res.submission_status === 'pending_review' || res.submission_status === 'approved');
    
    if (isLocked) {
        if(actionBtns) actionBtns.classList.add('d-none');
        if(clearFormBtn) clearFormBtn.classList.add('d-none');
        if(readonlyNotice) readonlyNotice.style.display = 'block';
    } else {
        if(actionBtns) actionBtns.classList.remove('d-none');
        if(clearFormBtn) clearFormBtn.classList.remove('d-none');
        if(readonlyNotice) readonlyNotice.style.display = 'none';
        
        // Cập nhật text nút
        const draftBtn = document.getElementById('draftBtn');
        const submitBtn = document.getElementById('submitBtn');
        if (draftBtn) draftBtn.innerHTML = '<i class="fas fa-save"></i> Cập nhật Nháp';
        if (submitBtn) submitBtn.innerHTML = '<i class="fas fa-paper-plane"></i> Nộp duyệt lại';
    }
    
    document.getElementById('cancelEditBtn').classList.remove('d-none');
    
    // Check if there are saved errors
    const wrongSections = data._wrong_sections || [];
    document.querySelectorAll('.error-checkbox').forEach(cb => {
        const sectionContainer = cb.closest('.form-section').querySelector('.form-section-title');
        if (wrongSections.includes(cb.dataset.section)) {
            cb.checked = true;
            sectionContainer.classList.add('bg-danger', 'bg-opacity-10');
        } else {
            cb.checked = false;
            sectionContainer.classList.remove('bg-danger', 'bg-opacity-10');
        }
    });
    
    if (currentUser && currentUser.role === 'admin') {
        const adminCheckArea = document.getElementById('adminCheckArea');
        if (adminCheckArea) {
            adminCheckArea.classList.remove('d-none');
            document.getElementById('adminFormCheckToggle').checked = !!res.is_checked;
        }
        
        // Hide update buttons
        const btnSubmit = document.getElementById('submitBtn');
        if (btnSubmit) btnSubmit.classList.add('d-none');
        
        const btnClear = document.getElementById('clearFormBtn');
        if (btnClear) btnClear.classList.add('d-none');
        
        const btnCancel = document.getElementById('cancelEditBtn');
        if (btnCancel) btnCancel.style.setProperty('display', 'none', 'important');
        
        const pdfLinkBtn = document.getElementById('pdfLinkBtn');
        if (pdfLinkBtn) pdfLinkBtn.classList.add('d-none');
        
        // Hide clear category buttons
        document.querySelectorAll('.clear-category-btn').forEach(btn => btn.classList.add('d-none'));
        
        // Make all form fields read-only
        const inputs = document.querySelectorAll('#dataForm input, #dataForm select');
        inputs.forEach(input => {
            if (input.id !== 'adminFormCheckToggle' && !input.classList.contains('error-checkbox')) {
                input.disabled = true;
            }
        });
        
        // Unhide the error checkboxes and add auto-save logic
        document.querySelectorAll('.admin-error-check').forEach(el => el.classList.remove('d-none'));
        document.querySelectorAll('.error-checkbox').forEach(cb => {
            cb.onchange = async () => {
                const wrong = [];
                document.querySelectorAll('.error-checkbox:checked').forEach(c => wrong.push(c.dataset.section));
                
                // Toggle visual highlight
                const sectionContainer = cb.closest('.form-section').querySelector('.form-section-title');
                if (cb.checked) {
                    sectionContainer.classList.add('bg-danger', 'bg-opacity-10');
                } else {
                    sectionContainer.classList.remove('bg-danger', 'bg-opacity-10');
                }
                
                await apiCall(`/api/submissions/${id}/errors`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ wrong_sections: wrong })
                });
            };
        });
    } else {
        // For employee, only show the "Lỗi Sai" indicator if it's checked
        document.querySelectorAll('.admin-error-check').forEach(el => {
            const cb = el.querySelector('.error-checkbox');
            if (cb.checked) {
                el.classList.remove('d-none');
                cb.disabled = true; // employee cannot untick it
            } else {
                el.classList.add('d-none');
            }
        });
    }
    
    // Check if there is an attached PDF
    const attachedPdf = data._pdf_filename;
    if (attachedPdf) {
        addFileToQueueAndSelect(attachedPdf);
    } else {
        isPdfLinked = false;
    }
    updatePdfLinkUI();
}

async function deleteSubmission(id) {
    if (!confirm('Bạn có chắc chắn muốn xóa hồ sơ này vĩnh viễn không?')) return;
    
    const res = await apiCall(`/api/submissions/${id}`, { method: 'DELETE' });
    if (res) {
        fetchSubmissions();
    }
}

function exportExcel(mode) {
    const tableBody = document.getElementById('submissionsTableBody');
    if (!tableBody || tableBody.innerText.includes('Chưa có dữ liệu')) {
        alert("Chưa có hồ sơ nào được nhập. Vui lòng nhập dữ liệu trước khi xuất báo cáo.");
        return;
    }
    
    if (mode === 'new') {
        if (confirm("Hệ thống sẽ tạo một BÁO CÁO MỚI từ toàn bộ dữ liệu trong CSDL. Bấm OK để tiếp tục.")) {
            window.location.href = '/api/export?mode=new';
        }
    }
}

async function exportExcelAppend(inputEl) {
    if (!inputEl.files || inputEl.files.length === 0) return;
    
    const tableBody = document.getElementById('submissionsTableBody');
    if (!tableBody || tableBody.innerText.includes('Chưa có dữ liệu')) {
        alert("Chưa có hồ sơ nào được nhập. Vui lòng nhập dữ liệu trước khi thêm vào báo cáo.");
        inputEl.value = '';
        return;
    }
    
    const file = inputEl.files[0];
    if (!confirm(`Hệ thống sẽ THÊM dữ liệu mới vào file "${file.name}". Bấm OK để tiếp tục.`)) {
        inputEl.value = '';
        return;
    }
    
    const formData = new FormData();
    formData.append("file", file);
    
    try {
        const response = await authFetch('/api/export-append', {
            method: 'POST',
            body: formData
        });
        
        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = file.name.replace('.xlsx', '_BoSung.xlsx');
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
            alert('Đã xuất file báo cáo bổ sung thành công!');
        } else {
            const res = await response.json();
            alert('Lỗi: ' + res.message);
        }
    } catch (err) {
        alert('Lỗi kết nối máy chủ: ' + err);
    }
    
    inputEl.value = '';
}


function filterSubmissions() {
    const filter = document.getElementById('searchInput').value.toLowerCase();
    const rows = document.querySelectorAll('#submissionsTableBody tr');
    
    rows.forEach(row => {
        if (row.cells.length === 1) return;
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(filter) ? '' : 'none';
    });
}

// === POOL & ASSIGNMENT LOGIC ===
async function fetchDocumentStats() {
    // Populate templates dropdown for assignment
    if (typeof populateTemplatesDropdown === 'function') {
        populateTemplatesDropdown('assignTemplateSelect', false);
    }
    
    const data = await apiCall('/api/documents/stats');
    if (data && data.status === 'ok') {
        const tbody = document.getElementById('poolStatsTableBody');
        const checkboxesContainer = document.getElementById('assignUserCheckboxes');
        if (tbody) tbody.innerHTML = '';
        if (checkboxesContainer) checkboxesContainer.innerHTML = '';
        
        data.user_stats.forEach(u => {
            const totalAssigned = u.pending + u.completed;
            // Table
            if (tbody) {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${u.username}</td>
                    <td><span class="badge bg-primary fs-6">${totalAssigned}</span></td>
                `;
                tbody.appendChild(tr);
            }
            
            // Checkboxes
            if (checkboxesContainer) {
                const div = document.createElement('div');
                div.className = 'form-check';
                div.innerHTML = `
                    <input class="form-check-input user-checkbox" type="checkbox" value="${u.user_id}" id="chkUser_${u.user_id}">
                    <label class="form-check-label" for="chkUser_${u.user_id}">
                        ${u.username} <span class="text-muted small">(Đã nhận: ${totalAssigned})</span>
                    </label>
                `;
                checkboxesContainer.appendChild(div);
            }
        });
    }
}

// Lắng nghe sự kiện chọn file
document.addEventListener('DOMContentLoaded', () => {
    const fileInput = document.getElementById('assignFilesInput');
    const countDiv = document.getElementById('assignFilesCount');
    if (fileInput && countDiv) {
        fileInput.addEventListener('change', () => {
            const count = fileInput.files.length;
            if (count > 0) {
                countDiv.innerHTML = `<span class="text-success fw-bold">Đã chọn ${count} file PDF.</span>`;
            } else {
                countDiv.innerHTML = 'Chưa chọn file nào.';
            }
        });
    }
});

async function uploadAndAssign() {
    const templateId = document.getElementById('assignTemplateSelect').value;
    const fileInput = document.getElementById('assignFilesInput');
    const statusDiv = document.getElementById('uploadAssignStatus');
    const btn = document.getElementById('btnUploadAssign');
    
    // Get checked users
    const checkboxes = document.querySelectorAll('.user-checkbox:checked');
    const userIds = Array.from(checkboxes).map(chk => chk.value);
    
    if (!templateId) {
        alert('Vui lòng chọn 1 Biểu mẫu.');
        return;
    }
    if (!fileInput.files || fileInput.files.length === 0) {
        alert('Vui lòng chọn ít nhất 1 file PDF.');
        return;
    }
    if (userIds.length === 0) {
        alert('Vui lòng chọn ít nhất 1 nhân viên để giao việc.');
        return;
    }
    
    btn.disabled = true;
    statusDiv.innerHTML = '<div class="alert alert-info"><div class="spinner-border spinner-border-sm"></div> Đang xử lý... Tải lên và phân công...</div>';
    
    const formData = new FormData();
    formData.append('template_id', templateId);
    formData.append('user_ids', userIds.join(','));
    for (let i = 0; i < fileInput.files.length; i++) {
        formData.append('files', fileInput.files[i]);
    }
    
    try {
        const res = await authFetch('/api/documents/upload-assign', {
            method: 'POST',
            body: formData
        });
        if (!res) return;
        
        const data = await res.json();
        
        if (data.status === 'ok') {
            statusDiv.innerHTML = `<div class="alert alert-success"><i class="fas fa-check-circle"></i> ${data.message}</div>`;
            fileInput.value = ''; // clear
            document.getElementById('assignFilesCount').innerHTML = 'Chưa chọn file nào.';
            fetchDocumentStats(); // Refresh stats
        } else {
            statusDiv.innerHTML = `<div class="alert alert-danger">${data.message}</div>`;
        }
    } catch (err) {
        statusDiv.innerHTML = `<div class="alert alert-danger">Lỗi kết nối: ${err.message}</div>`;
    } finally {
        btn.disabled = false;
    }
    if (data) {
        alert(data.message);
        document.getElementById('assignCountInput').value = 1;
        fetchDocumentPool(); // Refresh stats
    }
}
