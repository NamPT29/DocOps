async function submitData(targetStatus = 'draft') {
    const inputs = document.querySelectorAll('#dataForm input[type="text"]');
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
    }
    
    const isEditing = currentEditingId !== null;
    let url = isEditing ? `/api/submissions/${currentEditingId}` : '/api/submit';
    let method = isEditing ? 'PUT' : 'POST';
    
    const payload = {
        data: data,
        template_id: window.activeTemplateId,
        status: targetStatus
    };

    try {
        const response = await authFetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });
        const res = await response.json();
        
        if (res.status === 'ok') {
            alert('Lưu thành công!');
            
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
                
                // Xử lý hàng đợi: loại bỏ file hiện tại khỏi queue vì đã nhập xong
                if (uploadedFilesQueue.length > 0 && iframeCurrentIndex >= 0) {
                    uploadedFilesQueue.splice(iframeCurrentIndex, 1);
                    saveQueueState();
                    renderFileQueue();
                    
                    // Nếu vẫn còn file, tự động chọn file tiếp theo (lúc này index không đổi do file trước bị xóa)
                    if (uploadedFilesQueue.length > 0) {
                        let nextIndex = iframeCurrentIndex;
                        if (nextIndex >= uploadedFilesQueue.length) nextIndex = 0;
                        selectFileFromQueue(nextIndex);
                    } else {
                        // Đã hết file
                        iframeCurrentIndex = -1;
                        document.getElementById('pdfPlaceholder').style.display = 'block';
                        document.getElementById('pdfPlaceholder').innerHTML = 'Đã hoàn thành toàn bộ tài liệu!';
                        document.getElementById('pdfIframe').style.display = 'none';
                        isPdfLinked = false;
                        updatePdfLinkUI();
                    }
                }
            }
        } else {
            alert('Lỗi: ' + res.message);
        }
    } catch (err) {
        alert("Lỗi kết nối máy chủ: " + err);
    }
}

function cancelEdit() {
    currentEditingId = null;
    isEditingFromList = false;
    const inputs = document.querySelectorAll('#dataForm input[type="text"]');
    inputs.forEach(input => input.value = '');
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
    
    if (isPdfLinked) {
        isPdfLinked = false;
        updatePdfLinkUI();
    }
}

function resetFormData(silent = false) {
    if (!silent && !confirm('Bạn có chắc chắn muốn xóa sạch toàn bộ dữ liệu đang nhập không?')) return;
    
    // Clear all inputs and selects
    const inputs = document.querySelectorAll('#dataForm input');
    inputs.forEach(input => {
        if (input.type !== 'button' && input.type !== 'submit') {
            input.value = '';
        }
    });
    
    const selects = document.querySelectorAll('#dataForm select');
    selects.forEach(select => select.value = '');
    
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

