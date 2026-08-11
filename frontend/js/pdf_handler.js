let formDataCache = {};
let uploadedFilesQueue = [];
let iframeCurrentIndex = -1;
let currentPdfObjectUrl = null;

function normalizePdfUrl(url) {
    if (!url) return null;
    if (url.startsWith('/uploads/')) {
        return '/api/files/' + url.substring('/uploads/'.length);
    }
    return url;
}

function saveQueueState() {
    if (!currentUser) return;
    localStorage.setItem(`pdfQueue_${currentUser.username}`, JSON.stringify(uploadedFilesQueue));
    localStorage.setItem(`pdfIndex_${currentUser.username}`, iframeCurrentIndex);
}

function restoreQueue() {
    if (!currentUser) return;
    try {
        const storedQueue = localStorage.getItem(`pdfQueue_${currentUser.username}`);
        const storedIndex = localStorage.getItem(`pdfIndex_${currentUser.username}`);
        if (storedQueue) {
            uploadedFilesQueue = JSON.parse(storedQueue);
            if (storedIndex !== null) {
                iframeCurrentIndex = parseInt(storedIndex);
            }
            if (uploadedFilesQueue.length > 0) {
                renderFileQueue();
                if (iframeCurrentIndex >= 0 && iframeCurrentIndex < uploadedFilesQueue.length) {
                    selectFileFromQueue(iframeCurrentIndex);
                }
            }
        }
    } catch (e) {
        console.error("Lỗi phục hồi hàng chờ:", e);
    }
}

function setupPdfUpload() {
    const uploadInput = document.getElementById('pdfUploadInput');
    const iframe = document.getElementById('pdfIframe');
    const placeholder = document.getElementById('pdfPlaceholder');
    const fileQueueList = document.getElementById('fileQueueList');
    
    uploadInput.addEventListener('change', async function() {
        if (!this.files || this.files.length === 0) return;
        
        // Disable input while uploading
        uploadInput.disabled = true;
        
        for (let i = 0; i < this.files.length; i++) {
            const file = this.files[i];
            const formData = new FormData();
            formData.append("file", file);
            
            // Show loading placeholder if this is the first file
            if (uploadedFilesQueue.length === 0) {
                iframe.style.display = 'none';
                placeholder.style.display = 'block';
                placeholder.textContent = `Đang tải ${file.name}...`;
            }
            
            try {
                const response = await authFetch('/api/upload-pdf', {
                    method: 'POST',
                    body: formData
                });
                if (!response) return;
                const res = await response.json();
                
                if (res.status === 'ok') {
                    const fileItem = {
                        name: res.name || file.name,
                        url: res.url,
                        uuid: res.uuid
                    };
                    uploadedFilesQueue.push(fileItem);
                    saveQueueState();
                    renderFileQueue();
                    
                    // Automatically load the first uploaded file
                    if (uploadedFilesQueue.length === 1) {
                        selectFileFromQueue(0);
                    }
                } else {
                    console.error("Lỗi tải file: " + res.message);
                }
            } catch (err) {
                console.error("Lỗi kết nối: " + err);
            }
        }
        
        // Re-enable and clear input
        uploadInput.disabled = false;
        uploadInput.value = '';
    });
}

function renderFileQueue() {
    const fileQueueList = document.getElementById('fileQueueList');
    fileQueueList.innerHTML = '';
    
    let currentTemplateId = -1;
    uploadedFilesQueue.forEach((file, index) => {
        if (file.template_id && file.template_id !== currentTemplateId) {
            const header = document.createElement('div');
            header.className = 'list-group-item bg-light fw-bold text-primary px-2 py-1 mt-1';
            header.style.fontSize = '0.85rem';
            const icon = document.createElement('i');
            icon.className = 'fas fa-folder-open';
            header.appendChild(icon);
            header.appendChild(document.createTextNode(` Biểu mẫu: ${file.template_name || 'Không xác định'}`));
            fileQueueList.appendChild(header);
            currentTemplateId = file.template_id;
        }

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'list-group-item list-group-item-action d-flex align-items-center';
        btn.style.fontSize = '0.9rem';
        btn.title = file.name;
        
        // Manual Checkbox
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'form-check-input me-2 mt-0';
        checkbox.checked = file.completed || false;
        checkbox.onclick = (e) => {
            e.stopPropagation(); // Prevent triggering the row click
            file.completed = checkbox.checked;
            saveQueueState();
            renderFileQueue();
        };
        
        // Filename text
        const textSpan = document.createElement('span');
        textSpan.className = 'text-truncate flex-grow-1';
        textSpan.innerText = file.name;
        
        if (file.completed) {
            textSpan.classList.add('text-success', 'text-decoration-line-through');
        }
        
        // Remove Button (x)
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'btn-close btn-close-sm ms-2';
        removeBtn.style.fontSize = '0.6rem';
        removeBtn.onclick = (e) => {
            e.stopPropagation(); // Prevent triggering the row click
            uploadedFilesQueue.splice(index, 1);
            
            // Adjust iframeCurrentIndex if needed
            if (iframeCurrentIndex === index) {
                // If we removed the currently viewed file, try to show the next one, or previous
                if (uploadedFilesQueue.length > 0) {
                    selectFileFromQueue(Math.min(index, uploadedFilesQueue.length - 1));
                } else {
                    // No files left
                    iframeCurrentIndex = -1;
                    document.getElementById('pdfIframe').style.display = 'none';
                    document.getElementById('pdfPlaceholder').style.display = 'block';
                    document.getElementById('pdfPlaceholder').innerHTML = 'Chưa có tài liệu nào được tải lên.<br>Vui lòng chọn file PDF hoặc hình ảnh ở cột bên trái.';
                }
            } else if (iframeCurrentIndex > index) {
                // If we removed a file before the current one, the current one shifted left
                iframeCurrentIndex--;
            }
            saveQueueState();
            renderFileQueue();
        };
        
        btn.appendChild(checkbox);
        btn.appendChild(textSpan);
        btn.appendChild(removeBtn);
        
        // Mark active
        if (iframeCurrentIndex === index) {
            btn.classList.add('active');
            if (file.completed) textSpan.classList.remove('text-success'); // White text when active
        }
        
        btn.onclick = () => selectFileFromQueue(index);
        fileQueueList.appendChild(btn);
    });
}


let isPdfLinked = false;
let isEditingFromList = false;

function togglePdfLink() {
    isPdfLinked = !isPdfLinked;
    updatePdfLinkUI();
}

function updatePdfLinkUI() {
    const btn = document.getElementById('pdfLinkBtn');
    const text = document.getElementById('pdfLinkText');
    if (!btn || !text) return;
    
    if (isPdfLinked) {
        btn.classList.remove('btn-outline-secondary');
        btn.classList.add('btn-success');
        text.innerText = 'Đã liên kết';
    } else {
        btn.classList.remove('btn-success');
        btn.classList.add('btn-outline-secondary');
        text.innerText = 'Không liên kết';
    }
}

async function selectFileFromQueue(index) {
    if (index < 0 || index >= uploadedFilesQueue.length) return;
    
    iframeCurrentIndex = index;
    saveQueueState();
    const file = uploadedFilesQueue[index];
    const iframe = document.getElementById('pdfIframe');
    const placeholder = document.getElementById('pdfPlaceholder');

    const protectedUrl = normalizePdfUrl(file.url);
    if (!protectedUrl) return;
    placeholder.style.display = 'block';
    placeholder.textContent = 'Đang tải tài liệu...';
    iframe.style.display = 'none';

    try {
        const response = await authFetch(protectedUrl);
        if (!response) return;
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const blob = await response.blob();
        if (currentPdfObjectUrl) URL.revokeObjectURL(currentPdfObjectUrl);
        currentPdfObjectUrl = URL.createObjectURL(blob);
        iframe.src = currentPdfObjectUrl;
    } catch (error) {
        placeholder.textContent = 'Không thể tải tài liệu.';
        console.error('Lỗi tải tài liệu:', error);
        return;
    }
    iframe.onload = () => {
        placeholder.style.display = 'none';
        iframe.style.display = 'block';
    };
    
    renderFileQueue(); // Re-render to update the active class
    
    // Auto-switch template if needed
    if (file.template_id && window.activeTemplateId !== undefined && parseInt(file.template_id) !== parseInt(window.activeTemplateId)) {
        const select = document.getElementById('templateSelect');
        if (select) {
            select.value = file.template_id;
            select.dispatchEvent(new Event('change'));
        }
    }
    
    // Check if we are currently editing from the list. If not, clicking a PDF should start a fresh form.
    if (!currentEditingId || !isEditingFromList) {
        if (typeof resetFormData === 'function') resetFormData(true);
    }
    // Tự động liên kết file PDF này với form đang nhập
    isPdfLinked = true;
    updatePdfLinkUI();
}

async function fetchMyQueue() {
    try {
        const btn = document.getElementById('btnFetchQueue');
        if(btn) btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Đang tải...';
        
        const res = await authFetch('/api/documents/my-queue');
        if (!res) return;
        const data = await res.json();
        
        if (data.status === 'ok') {
            const queueGroups = data.data;
            if (queueGroups.length === 0) {
                alert("Bạn không có tài liệu nào đang chờ xử lý.");
            } else {
                let added = 0;
                queueGroups.forEach(group => {
                    group.files.forEach(doc => {
                        if (!uploadedFilesQueue.find(f => f.url === doc.url)) {
                            uploadedFilesQueue.push({
                                name: doc.name,
                                url: doc.url,
                                uuid: doc.uuid,
                                template_id: group.template_id,
                                template_name: group.template_name
                            });
                            added++;
                        }
                    });
                });
                
                uploadedFilesQueue.sort((a, b) => (a.template_id || 0) - (b.template_id || 0));
                
                saveQueueState();
                renderFileQueue();
                
                if (added > 0) {
                    alert(`Đã nhận thêm ${added} tài liệu vào danh sách chờ.`);
                }
                
                // Select first file if nothing is selected
                if (uploadedFilesQueue.length > 0 && iframeCurrentIndex === -1) {
                    selectFileFromQueue(0);
                }
            }
        }
        
        if(btn) btn.innerHTML = '<i class="fas fa-download"></i> Tải tài liệu được giao';
    } catch (err) {
        console.error(err);
        alert('Lỗi tải tài liệu: ' + err.message);
    }
}

function addFileToQueueAndSelect(attachedPdf, attachedPdfUuid, attachedPdfUrl) {
    if (!attachedPdf) return;

    const resolvedUrl = attachedPdfUrl || (attachedPdfUuid
        ? `/api/files/${encodeURIComponent(attachedPdfUuid)}`
        : null);
    if (!resolvedUrl) {
        alert(`Không tìm thấy file PDF đã liên kết: ${attachedPdf}`);
        return;
    }

    let fileIndex = uploadedFilesQueue.findIndex(f =>
        (attachedPdfUuid && f.uuid === attachedPdfUuid) || f.url === resolvedUrl
    );
    if (fileIndex === -1) {
        const legacyMatches = uploadedFilesQueue
            .map((file, index) => ({ file, index }))
            .filter(({ file }) => file.name === attachedPdf && !file.uuid);
        if (legacyMatches.length === 1) {
            fileIndex = legacyMatches[0].index;
        }
    }
    if (fileIndex === -1) {
        uploadedFilesQueue.push({
            name: attachedPdf,
            uuid: attachedPdfUuid,
            url: resolvedUrl
        });
        fileIndex = uploadedFilesQueue.length - 1;
        renderFileQueue();
        saveQueueState();
    } else {
        uploadedFilesQueue[fileIndex].uuid = attachedPdfUuid || uploadedFilesQueue[fileIndex].uuid;
        uploadedFilesQueue[fileIndex].url = resolvedUrl;
        saveQueueState();
    }
    
    selectFileFromQueue(fileIndex);
    isPdfLinked = true;
}
