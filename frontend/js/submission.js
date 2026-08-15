function removeLinkedPdfFromQueue(queueIndex) {
    if (!Number.isInteger(queueIndex) || queueIndex < 0 || queueIndex >= uploadedFilesQueue.length) return;

    uploadedFilesQueue.splice(queueIndex, 1);
    saveQueueState();
    renderFileQueue();

    if (uploadedFilesQueue.length > 0) {
        const nextIndex = queueIndex < uploadedFilesQueue.length ? queueIndex : 0;
        selectFileFromQueue(nextIndex);
        return;
    }

    iframeCurrentIndex = -1;
    const placeholder = document.getElementById('pdfPlaceholder');
    const iframe = document.getElementById('pdfIframe');
    if (placeholder) {
        placeholder.style.display = 'block';
        placeholder.innerHTML = 'Đã hoàn thành toàn bộ tài liệu!';
    }
    if (iframe) iframe.style.display = 'none';
    isPdfLinked = false;
    updatePdfLinkUI();
}

async function submitData(targetStatus = 'draft') {
    const inputs = document.querySelectorAll('#dataForm input[type="text"], #dataForm textarea, #dataForm select');
    const data = {};
    inputs.forEach(input => {
        data[input.name] = input.value;
    });
    
    // Attach PDF filename if linked
    if (isPdfLinked && iframeCurrentIndex >= 0 && iframeCurrentIndex < uploadedFilesQueue.length) {
        const linkedPdf = uploadedFilesQueue[iframeCurrentIndex];
        data['_pdf_filename'] = linkedPdf.name;
        if (linkedPdf.uuid) data['_pdf_uuid'] = linkedPdf.uuid;
        if (linkedPdf.url) data['_pdf_url'] = linkedPdf.url;
        if (linkedPdf.relative_path) data['_pdf_relative_path'] = linkedPdf.relative_path;
        if (linkedPdf.folder_group && linkedPdf.folder_group !== '__ROOT__') {
            data['_folder_path'] = linkedPdf.folder_group;
        }
    }
    
    const isEditing = currentEditingId !== null;
    const isReviewEdit = isEditing && window.reviewEditMode === true;
    const linkedQueueIndex = isPdfLinked
        && iframeCurrentIndex >= 0
        && iframeCurrentIndex < uploadedFilesQueue.length
        ? iframeCurrentIndex
        : -1;
    let url = isReviewEdit
        ? `/api/submissions/${currentEditingId}/review-content`
        : (isEditing ? `/api/submissions/${currentEditingId}` : '/api/submit');
    let method = isEditing ? 'PUT' : 'POST';
    
    const payload = isReviewEdit
        ? {
            data: data,
            wrong_fields: Array.from(
                document.querySelectorAll('.field-error-checkbox:checked'),
                checkbox => checkbox.dataset.field,
            ),
        }
        : {
            data: data,
            template_id: window.activeTemplateId,
            status: targetStatus
    };

    try {
        // A checkbox change auto-saves its marker. Wait for that request before
        // saving corrected content so two writes cannot overwrite data_json.
        if (isReviewEdit && window.reviewErrorSavePromise) {
            await window.reviewErrorSavePromise;
        }
        const response = await authFetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });
        if (!response) return;
        const res = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(formatApiErrorDetail(res.detail || res.message || `HTTP ${response.status}`));
        }
        
        if (res.status === 'ok') {
            alert(isReviewEdit ? 'Đã lưu chỉnh sửa của người kiểm tra!' : 'Lưu thành công!');

            if (isReviewEdit) {
                await editSubmission(currentEditingId);
                return;
            }
            
            if (isEditing) {
                cancelEdit();
                fetchSubmissions();
                // Switch back to list tab safely
                const dataTabBtn = document.getElementById('data-tab');
                if (dataTabBtn) dataTabBtn.click();
            } else {
                // Clear form and draft
                inputs.forEach(input => input.value = '');
                if (typeof removeCurrentFormDraft === 'function') removeCurrentFormDraft();
                fetchSubmissions();
            }

            // Loại PDF đã xử lý khỏi hàng chờ local cho cả hồ sơ mới và hồ sơ nháp
            // đang được cập nhật. Người kiểm tra sửa nội dung không đi qua nhánh này.
            if (!isEditing) removeLinkedPdfFromQueue(linkedQueueIndex);
        } else {
            alert('Lỗi: ' + res.message);
        }
    } catch (err) {
        alert("Không thể lưu hồ sơ: " + err.message);
    }
}

function cancelEdit() {
    if (typeof stopSubmissionView === 'function') stopSubmissionView();
    currentEditingId = null;
    isEditingFromList = false;
    const inputs = document.querySelectorAll('#dataForm input[type="text"], #dataForm textarea');
    inputs.forEach(input => input.value = '');
    if (typeof resizeDynamicFormInputs === 'function') {
        resizeDynamicFormInputs(document.getElementById('dataForm'));
    }
    // Reset dropdown visuals
    inputs.forEach(input => {
        if(input.nextElementSibling && input.nextElementSibling.classList.contains('autocomplete-items')) {
            input.nextElementSibling.innerHTML = '';
        }
    });
    // Reset UI states
    const actionBtns = document.getElementById('actionButtonsRow');
    if(actionBtns) actionBtns.classList.remove('d-none');
    const readonlyNotice = document.getElementById('readonlyNotice');
    if(readonlyNotice) readonlyNotice.style.display = 'none';
    const clearFormBtn = document.getElementById('clearFormBtn');
    if(clearFormBtn) clearFormBtn.classList.remove('d-none');
    document.getElementById('cancelEditBtn').classList.add('d-none');
    
    const adminCheckArea = document.getElementById('adminCheckArea');
    if (adminCheckArea) {
        adminCheckArea.classList.add('d-none');
    }
    
    if (typeof clearTemporaryPdfView === 'function') clearTemporaryPdfView();
    if (isPdfLinked) {
        isPdfLinked = false;
        updatePdfLinkUI();
    }
}

function resetFormData(silent = false) {
    if (!silent && !confirm('Bạn có chắc chắn muốn xóa sạch toàn bộ dữ liệu đang nhập không?')) return;
    
    // Clear all inputs and selects
    const inputs = document.querySelectorAll('#dataForm input, #dataForm textarea');
    inputs.forEach(input => {
        if (input.type !== 'button' && input.type !== 'submit') {
            input.value = '';
        }
    });
    
    const selects = document.querySelectorAll('#dataForm select');
    selects.forEach(select => select.value = '');
    if (typeof resizeDynamicFormInputs === 'function') {
        resizeDynamicFormInputs(document.getElementById('dataForm'));
    }
    
    // Reset edit state just in case
    currentEditingId = null;
    document.getElementById('submitBtn').innerText = 'Lưu hồ sơ';
    document.getElementById('cancelEditBtn').classList.add('d-none');
    
    isPdfLinked = false;
    updatePdfLinkUI();
    
    // Remove drafting if it exists
    if (typeof localStorage !== 'undefined') {
        if (typeof removeCurrentFormDraft === 'function') removeCurrentFormDraft();
    }
}

