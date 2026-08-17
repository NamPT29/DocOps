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
    const draftBtn = document.getElementById('draftBtn');
    const submitBtn = document.getElementById('submitBtn');
    
    // Prevent double submissions
    if (draftBtn && draftBtn.disabled && submitBtn && submitBtn.disabled) return;

    if (draftBtn) draftBtn.disabled = true;
    if (submitBtn) submitBtn.disabled = true;

    try {
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
            
        // Duplicate check for copied submissions
        if (window.isCopiedSubmissionEdit && window.originalEditingData) {
            if (JSON.stringify(data) === window.originalEditingData) {
                if (!confirm("Cảnh báo: Bạn chưa sửa đổi trường dữ liệu nào từ bản gốc. Nếu lưu sẽ gây trùng lặp báo cáo. Bạn có chắc chắn muốn lưu lại không? (Nhấn Hủy để kiểm tra lại)")) {
                    return;
                }
            }
        }
        
        let updateCover = false;
        const coverCols = window.activeTemplateConfig && window.activeTemplateConfig.cover_cols ? window.activeTemplateConfig.cover_cols : [];
        const coverFolderLevels = window.activeTemplateConfig && window.activeTemplateConfig.cover_folder_level ? window.activeTemplateConfig.cover_folder_level : 0;
        
        if (coverCols.length > 0 && coverFolderLevels > 0 && !isReviewEdit) {
            const currentCoverData = {};
            coverCols.forEach(c => {
                const key = `col_${c-1}`;
                currentCoverData[key] = data[key] || '';
            });
            
            const initialCover = window.initialCoverData || {};
            let isChanged = false;
            if (!isEditing) {
                // For new form, it's changed if any cover field is non-empty
                isChanged = Object.values(currentCoverData).some(v => v.trim() !== '');
            } else {
                // For edit form, it's changed if different from initial
                isChanged = JSON.stringify(currentCoverData) !== JSON.stringify(initialCover);
            }
            
            if (isChanged) {
                if (confirm("Bạn đã thay đổi dữ liệu của các trường bìa. Bấm OK để tự động cập nhật dữ liệu này cho tất cả các báo cáo khác trong cùng thư mục (nếu có), hoặc Cancel để chỉ lưu cho báo cáo này.")) {
                    updateCover = true;
                }
            }
        }

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
                status: targetStatus,
                sync_cover: updateCover
        };

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
                // Clear form and draft, but preserve cover columns
                const coverCols = window.activeTemplateConfig && window.activeTemplateConfig.cover_cols ? window.activeTemplateConfig.cover_cols : [];
                inputs.forEach(input => {
                    const match = input.name ? input.name.match(/^col_(\d+)$/) : null;
                    const colIndex = match ? parseInt(match[1], 10) + 1 : -1;
                    if (!coverCols.includes(colIndex)) {
                        input.value = '';
                    }
                });
                // Clear autocomplete dropdown visuals
                inputs.forEach(input => {
                    if(input.nextElementSibling && input.nextElementSibling.classList.contains('autocomplete-items')) {
                        input.nextElementSibling.innerHTML = '';
                    }
                });
                
                if (typeof removeCurrentFormDraft === 'function') removeCurrentFormDraft();
                
                // Set initialCoverData for the next new form to the preserved cover values
                window.initialCoverData = {};
                inputs.forEach(input => {
                    const match = input.name ? input.name.match(/^col_(\d+)$/) : null;
                    const colIndex = match ? parseInt(match[1], 10) + 1 : -1;
                    if (coverCols.includes(colIndex)) {
                        window.initialCoverData[input.name] = input.value;
                    }
                });
                
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
    } finally {
        if (draftBtn) draftBtn.disabled = false;
        if (submitBtn) submitBtn.disabled = false;
    }
}

function cancelEdit() {
    if (typeof stopSubmissionView === 'function') stopSubmissionView();
    currentEditingId = null;
    isEditingFromList = false;
    window.isCopiedSubmissionEdit = false;
    window.originalEditingData = null;
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
    
    window.initialCoverData = {};
    
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

