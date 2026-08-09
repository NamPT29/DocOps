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
    tbody.innerHTML = '';
    
    if (res.data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-center">Chưa có dữ liệu</td></tr>';
        return;
    }
    
    res.data.forEach(sub => {
        const tr = document.createElement('tr');
        if (sub.has_errors) {
            tr.classList.add('table-danger');
        }
        tr.innerHTML = `
            <td>${sub.id}</td>
            <td>${sub.created_at}</td>
            ${window.location.pathname.includes('admin.html') ? `<td><span class="badge bg-info text-dark"><i class="fas fa-user"></i> ${sub.creator_name || 'Unknown'}</span></td>` : ''}
            <td class="fw-bold text-primary">${sub.ho_ten}</td>
            <td>${sub.so_giay_to}</td>
            <td><span class="badge bg-secondary">${sub.template}</span></td>
            <td>
                ${sub.pdf_filename ? `<span class="badge bg-success" ${window.location.pathname.includes('admin.html') ? '' : `style="cursor: pointer;" onclick="editSubmission(${sub.id})" title="Nhấn để xem PDF và sửa hồ sơ"`}>${sub.pdf_filename}</span>` : '<span class="text-muted fst-italic">Không</span>'}
            </td>
            <td class="text-center">
                ${window.location.pathname.includes('admin.html') ? `
                    <div class="form-check d-flex justify-content-center mb-0">
                        <input class="form-check-input" type="checkbox" ${sub.is_checked ? 'checked' : ''} onchange="toggleCheckSubmission(${sub.id}, this)" style="cursor: pointer; transform: scale(1.3);">
                    </div>
                ` : `
                    ${sub.is_checked ? '<span class="badge bg-primary"><i class="fas fa-check"></i> Đã duyệt</span>' : '<span class="badge bg-secondary">Chưa duyệt</span>'}
                `}
            </td>
            <td>
                ${window.location.pathname.includes('admin.html') ? `
                    <a class="btn btn-sm btn-outline-primary me-1" href="index.html?check_id=${sub.id}">Xem & Kiểm tra</a>
                ` : `
                    <button class="btn btn-sm btn-outline-success me-1" onclick="copySubmission(${sub.id})">Nhân bản</button>
                    <button class="btn btn-sm btn-outline-primary me-1" onclick="editSubmission(${sub.id})">Sửa</button>
                `}
                <button class="btn btn-sm btn-outline-danger" onclick="deleteSubmission(${sub.id})">Xóa</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

async function toggleCheckSubmission(id, checkbox) {
    const res = await apiCall(`/api/submissions/${id}/toggle_check`, { method: 'PUT' });
    if (res) {
        // Also update the UI if we are on the admin page list
        if (window.location.pathname.includes('admin.html')) {
            fetchAdminData();
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
        await fetchMaXaMapping();
        await fetchDonViDoMapping();
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
    document.getElementById('submitBtn').innerText = 'Cập nhật Hồ sơ';
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
        // Find in the queue
        let fileIndex = uploadedFilesQueue.findIndex(f => f.name === attachedPdf);
        if (fileIndex === -1) {
            // Add it to the queue so we can view and preserve it
            uploadedFilesQueue.push({
                name: attachedPdf,
                url: `/uploads/${attachedPdf}`
            });
            fileIndex = uploadedFilesQueue.length - 1;
            renderFileQueue();
            saveQueueState();
        }
        
        selectFileFromQueue(fileIndex);
        isPdfLinked = true;
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
async function fetchDocumentPool() {
    const data = await apiCall('/api/documents/pool');
    if (data) {
        document.getElementById('unassignedCount').innerText = data.unassigned_count;
        const assignCountInput = document.getElementById('assignCountInput');
        if(assignCountInput) {
            assignCountInput.max = data.unassigned_count;
        }
        
        const tbody = document.getElementById('poolStatsTableBody');
        const select = document.getElementById('assignUserSelect');
        if (tbody) tbody.innerHTML = '';
        if (select) select.innerHTML = '';
        
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
            
            // Select
            if (select) {
                const opt = document.createElement('option');
                opt.value = u.user_id;
                opt.innerText = `${u.username} (Đã giao: ${totalAssigned})`;
                select.appendChild(opt);
            }
        });
    }
}

async function uploadBatchDocuments() {
    const fileInput = document.getElementById('batchUploadInput');
    const statusDiv = document.getElementById('batchUploadStatus');
    const btn = document.getElementById('btnBatchUpload');
    
    if (!fileInput.files || fileInput.files.length === 0) {
        alert('Vui lòng chọn ít nhất 1 file!');
        return;
    }
    
    btn.disabled = true;
    statusDiv.innerHTML = '<div class="spinner-border spinner-border-sm text-primary"></div> Đang tải lên...';
    
    const formData = new FormData();
    for (let i = 0; i < fileInput.files.length; i++) {
        formData.append('files', fileInput.files[i]);
    }
    
    try {
        const res = await authFetch('/api/documents/batch-upload', {
            method: 'POST',
            body: formData
        });
        if (!res) return; // authFetch tự động xử lý lỗi 401 và trả về null
        
        const data = await res.json();
        
        if (data.status === 'ok') {
            statusDiv.innerHTML = `<div class="alert alert-success">${data.message}</div>`;
            fileInput.value = '';
            fetchDocumentPool(); // Refresh stats
        } else {
            const errorMsg = data.message || data.detail || 'Lỗi không xác định';
            statusDiv.innerHTML = `<div class="alert alert-danger">${errorMsg}</div>`;
        }
    } catch (err) {
        statusDiv.innerHTML = `<div class="alert alert-danger">Lỗi kết nối: ${err.message}</div>`;
    } finally {
        btn.disabled = false;
    }
}

async function assignDocuments() {
    const userId = document.getElementById('assignUserSelect').value;
    const count = document.getElementById('assignCountInput').value;
    
    if (!userId) {
        alert('Vui lòng chọn nhân viên.');
        return;
    }
    if (!count || parseInt(count) <= 0) {
        alert('Số lượng phải lớn hơn 0.');
        return;
    }
    
    const unassignedCount = parseInt(document.getElementById('unassignedCount').innerText);
    if (parseInt(count) > unassignedCount) {
        alert(`Kho chỉ còn ${unassignedCount} tài liệu, không thể giao ${count} tài liệu.`);
        return;
    }
    
    const data = await apiCall('/api/documents/assign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            user_id: parseInt(userId),
            count: parseInt(count)
        })
    });
    
    if (data) {
        alert(data.message);
        document.getElementById('assignCountInput').value = 1;
        fetchDocumentPool(); // Refresh stats
    }
}
