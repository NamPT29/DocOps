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
    window.pdfLinkState.setLinked(false);
    updatePdfLinkUI();
}

function setSubmissionModeButtons(canSubmit = false, isResubmission = false) {
    const draftContainer = document.getElementById('draftButtonContainer');
    const submitContainer = document.getElementById('submitButtonContainer');
    const draftBtn = document.getElementById('draftBtn');
    const submitBtn = document.getElementById('submitBtn');
    if (draftContainer) {
        draftContainer.classList.toggle('col-12', !canSubmit);
        draftContainer.classList.toggle('col-6', canSubmit);
    }
    if (submitContainer) submitContainer.classList.toggle('d-none', !canSubmit);
    if (draftBtn) draftBtn.innerHTML = canSubmit
        ? '<i class="fas fa-save"></i> Cập nhật nháp'
        : '<i class="fas fa-save"></i> Lưu nháp';
    if (submitBtn) {
        submitBtn.classList.toggle('d-none', !canSubmit);
        submitBtn.innerHTML = isResubmission
            ? '<i class="fas fa-paper-plane"></i> Nộp duyệt lại'
            : '<i class="fas fa-paper-plane"></i> Nộp duyệt';
    }
}

function collectSubmissionFormData() {
    const inputs = document.querySelectorAll('#dataForm input[type="text"], #dataForm textarea, #dataForm select');
    const data = {};
    inputs.forEach(input => {
        data[input.name] = input.value;
    });
    return data;
}

function getCopiedSubmissionPathFieldName() {
    const config = typeof getLinkedPdfPathConfig === 'function'
        ? getLinkedPdfPathConfig()
        : null;
    return config ? `col_${config.col - 1}` : null;
}

function normalizeCopiedSubmissionValue(value) {
    if (value === null || value === undefined) return '';
    if (typeof value === 'string') return value.trim();
    if (Array.isArray(value)) return value.map(normalizeCopiedSubmissionValue);
    if (typeof value === 'object') {
        return Object.keys(value).sort().reduce((normalized, key) => {
            normalized[key] = normalizeCopiedSubmissionValue(value[key]);
            return normalized;
        }, {});
    }
    return value;
}

function hasCopiedSubmissionBusinessChanges(sourceData, currentData) {
    const ignoredPathField = getCopiedSubmissionPathFieldName();
    const keys = new Set([
        ...Object.keys(sourceData || {}),
        ...Object.keys(currentData || {}),
    ]);
    const comparableKeys = Array.from(keys)
        .filter(key => typeof key === 'string' && !key.startsWith('_') && key !== ignoredPathField)
        .sort();
    return comparableKeys.some(key => (
        JSON.stringify(normalizeCopiedSubmissionValue(sourceData?.[key]))
        !== JSON.stringify(normalizeCopiedSubmissionValue(currentData?.[key]))
    ));
}

async function submitData(targetStatus = 'draft') {
    const draftBtn = document.getElementById('draftBtn');
    const submitBtn = document.getElementById('submitBtn');
    
    if (targetStatus === 'pending_review' && currentEditingId === null) {
        alert('Hãy lưu nháp và mở hồ sơ trong mục Hồ sơ đã nhập trước khi nộp duyệt.');
        return;
    }

    // Prevent double submissions
    if (draftBtn && draftBtn.disabled && submitBtn && submitBtn.disabled) return;

    if (draftBtn) draftBtn.disabled = true;
    if (submitBtn) submitBtn.disabled = true;

    try {
        const inputs = document.querySelectorAll('#dataForm input[type="text"], #dataForm textarea, #dataForm select');
        const data = collectSubmissionFormData();

        if (
            window.isCopiedSubmissionEdit
            && window.originalEditingData
            && !hasCopiedSubmissionBusinessChanges(window.originalEditingData, data)
        ) {
            alert('Không thể lưu: ngoài trường đường dẫn PDF, bạn phải sửa ít nhất một trường dữ liệu so với báo cáo nguồn.');
            return;
        }
        
        // Attach PDF filename if linked
        if (window.pdfLinkState.isLinked() && iframeCurrentIndex >= 0 && iframeCurrentIndex < uploadedFilesQueue.length) {
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
        const linkedQueueIndex = window.pdfLinkState.isLinked()
            && iframeCurrentIndex >= 0
            && iframeCurrentIndex < uploadedFilesQueue.length
            ? iframeCurrentIndex
            : -1;
            
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
            ? { data: data }
            : {
                data: data,
                template_id: window.activeTemplateId,
                status: targetStatus,
                sync_cover: updateCover
        };
        if (!isReviewEdit && window.isCopiedSubmissionEdit && Number.isInteger(Number(window.copySourceSubmissionId))) {
            payload.copy_source_submission_id = Number(window.copySourceSubmissionId);
        }

        // A checkbox change auto-saves its marker. Wait for that request before
        // saving corrected content so two writes cannot overwrite data_json.
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
            if (res.detail && res.detail.code === 'duplicate_submission') {
                throw new Error(res.detail.message || `Có ${res.detail.duplicate_count} báo cáo trùng.`);
            }
            if (res.detail && res.detail.code === 'copy_unchanged') {
                throw new Error(res.detail.message || 'Báo cáo nhân bản chưa có thay đổi ngoài đường dẫn PDF.');
            }
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

            if (!isEditing && window.isCopiedSubmissionEdit) {
                window.isCopiedSubmissionEdit = false;
                window.originalEditingData = null;
                window.copySourceSubmissionId = null;
            }

            // Tài liệu đã nhập vẫn được giữ trong hàng chờ và chỉ đổi trạng thái.
            if (!isEditing && linkedQueueIndex >= 0 && uploadedFilesQueue[linkedQueueIndex]) {
                uploadedFilesQueue[linkedQueueIndex].completed = true;
                saveQueueState();
                renderFileQueue();
            }
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
    window.copySourceSubmissionId = null;
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
    setSubmissionModeButtons(false);
    
    const adminCheckArea = document.getElementById('adminCheckArea');
    if (adminCheckArea) {
        adminCheckArea.classList.add('d-none');
    }
    
    if (typeof clearTemporaryPdfView === 'function') clearTemporaryPdfView();
    if (window.pdfLinkState.isLinked()) {
        window.pdfLinkState.setLinked(false);
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
    setSubmissionModeButtons(false);
    document.getElementById('cancelEditBtn').classList.add('d-none');
    
    window.pdfLinkState.setLinked(false);
    updatePdfLinkUI();
    
    // Remove drafting if it exists
    if (typeof localStorage !== 'undefined') {
        if (typeof removeCurrentFormDraft === 'function') removeCurrentFormDraft();
    }
}

function setSubmissionUnreadBadge(value) {
    const badge = document.getElementById('submissionUnreadBadge');
    if (!badge) return;
    const count = Math.max(0, Number(value) || 0);
    badge.dataset.count = String(count);
    badge.textContent = count > 99 ? '99+' : String(count || '');
    badge.classList.toggle('d-none', count === 0);
    badge.setAttribute(
        'aria-label',
        count > 0 ? `${count} hồ sơ có thay đổi chưa xem` : ''
    );
}

async function refreshSubmissionUnreadBadge() {
    const response = await apiCall('/api/submissions?page=1&page_size=1');
    if (response) setSubmissionUnreadBadge(response.unread_review_count);
    return response;
}

function configureInputCorrectionFromDetail(detail) {
    const quality = detail?.quality;
    if (typeof applySubmissionQualityFieldStyles === 'function') {
        applySubmissionQualityFieldStyles(quality);
    }

    const reviewedChanges = Array.isArray(quality?.reviewed_changes)
        ? quality.reviewed_changes.filter(name => typeof name === 'string')
        : [];
    const correctedFields = Array.isArray(quality?.corrected_fields)
        ? quality.corrected_fields.filter(name => typeof name === 'string')
        : [];
    const canCorrect = (
        detail?.submission_status === 'pending_input_confirmation'
        && quality != null
        && correctedFields.length === 0
        && detail?.can_review !== true
    );
    window.inputCorrectionMode = canCorrect;
    window.inputCorrectionFields = canCorrect ? reviewedChanges : [];

    if (!canCorrect) return;

    const actionButtons = document.getElementById('actionButtonsRow');
    const draftContainer = document.getElementById('draftButtonContainer');
    const submitContainer = document.getElementById('submitButtonContainer');
    const draftButton = document.getElementById('draftBtn');
    const readonlyNotice = document.getElementById('readonlyNotice');
    const clearButton = document.getElementById('clearFormBtn');
    const pdfLinkButton = document.getElementById('pdfLinkBtn');

    if (actionButtons) actionButtons.classList.remove('d-none');
    if (draftContainer) {
        draftContainer.classList.remove('col-6');
        draftContainer.classList.add('col-12');
    }
    if (submitContainer) submitContainer.classList.add('d-none');
    if (draftButton) {
        draftButton.classList.remove('d-none');
        draftButton.innerHTML = '<i class="fas fa-check-circle"></i> Xác nhận hoàn thành';
    }
    if (readonlyNotice) {
        readonlyNotice.style.display = 'block';
        readonlyNotice.textContent = reviewedChanges.length > 0
            ? 'Kiểm tra lại nội dung người kiểm duyệt. Bạn có thể sửa các trường màu đỏ trước khi xác nhận hoàn thành.'
            : 'Kiểm tra lại nội dung người kiểm duyệt và xác nhận để hoàn thành hồ sơ.';
    }
    if (clearButton) clearButton.classList.add('d-none');
    if (pdfLinkButton) pdfLinkButton.classList.add('d-none');
    document.querySelectorAll('.clear-category-btn').forEach(button => {
        button.classList.add('d-none');
    });
    document.querySelectorAll('#dataForm input, #dataForm textarea, #dataForm select').forEach(input => {
        input.disabled = !reviewedChanges.includes(input.id);
    });
}

async function submitInputCorrection() {
    const submissionId = Number(currentEditingId);
    if (!Number.isInteger(submissionId) || submissionId <= 0) return;

    const data = {};
    (window.inputCorrectionFields || []).forEach(fieldName => {
        const input = document.getElementById(fieldName);
        if (input) data[fieldName] = input.value;
    });
    const draftButton = document.getElementById('draftBtn');
    if (draftButton) draftButton.disabled = true;

    try {
        const response = await authFetch(`/api/submissions/${submissionId}/input-confirmation`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ data }),
        });
        if (!response) return;
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(formatApiErrorDetail(result.detail || result.message || `HTTP ${response.status}`));
        }
        window.inputCorrectionMode = false;
        window.inputCorrectionFields = [];
        alert('Hồ sơ đã hoàn thành.');
        if (typeof window.editSubmission === 'function') {
            await window.editSubmission(submissionId);
        }
    } catch (error) {
        alert(`Không thể xác nhận hoàn thành: ${error.message}`);
    } finally {
        if (draftButton) draftButton.disabled = false;
    }
}

function installSubmissionQualityIntegration() {
    if (window.submissionQualityIntegrationInstalled === true) return;
    window.submissionQualityIntegrationInstalled = true;

    const baseEditSubmission = window.editSubmission;
    if (typeof baseEditSubmission === 'function') {
        window.editSubmission = async function qualityAwareEditSubmission(id, isCopied = false) {
            const result = await baseEditSubmission.call(this, id, isCopied);
            if (isCopied || Number(currentEditingId) !== Number(id)) return result;

            const detail = await apiCall(`/api/submissions/${Number(id)}`);
            if (detail) {
                configureInputCorrectionFromDetail(detail);
                if (detail.quality) await refreshSubmissionUnreadBadge();
            }
            return result;
        };
    }

    const baseFetchSubmissions = window.fetchSubmissions;
    if (typeof baseFetchSubmissions === 'function') {
        window.fetchSubmissions = async function qualityAwareFetchSubmissions(...args) {
            const result = await baseFetchSubmissions.apply(this, args);
            await refreshSubmissionUnreadBadge();
            return result;
        };
    }

    const baseSubmitData = window.submitData;
    if (typeof baseSubmitData === 'function') {
        window.submitData = function qualityAwareSubmitData(targetStatus = 'draft') {
            if (window.inputCorrectionMode === true) return submitInputCorrection();
            return baseSubmitData.call(this, targetStatus);
        };
    }

    if (typeof currentUserCanInput !== 'function' || currentUserCanInput()) {
        refreshSubmissionUnreadBadge();
    }
}

if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
    window.addEventListener('load', installSubmissionQualityIntegration, { once: true });
}

