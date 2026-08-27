let formDataCache = {};
let uploadedFilesQueue = [];
let iframeCurrentIndex = -1;
let currentPdfObjectUrl = null;
let activeDocumentRelativePath = null;
let activeDocumentFolderPath = null;
let activeQueueFolderKey = null;
let relativePathObserver = null;

function normalizePdfUrl(url) {
    if (!url) return null;
    if (url.startsWith('/uploads/')) {
        return '/api/files/' + url.substring('/uploads/'.length);
    }
    return url;
}

function normalizeQueuePath(path) {
    return String(path || '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
}

function getQueuePathTail(path) {
    const parts = normalizeQueuePath(path).split('/').filter(Boolean);
    return parts[parts.length - 1] || '';
}

function getQueueDocumentName(file) {
    return getQueuePathTail(file?.name || file?.relative_path) || 'Tài liệu không tên';
}

function getQueueFolderKey(file) {
    const folderPath = normalizeQueuePath(file?.folder_group);
    if (!folderPath || folderPath === '__ROOT__') return null;
    return `${file.template_id || 0}::${folderPath}`;
}

function getLinkedPdfPathConfig() {
    const config = window.activeTemplateConfig?.linked_pdf_path;
    const col = Number(config?.col);
    if (config?.enabled !== true || !Number.isInteger(col) || col < 1) return null;
    const parsedLevels = Number(config.folder_levels);
    return {
        col,
        folderLevels: Number.isInteger(parsedLevels) ? Math.min(20, Math.max(0, parsedLevels)) : 0,
    };
}

function formatLinkedPdfPath(path, folderLevels) {
    const normalized = normalizeQueuePath(path);
    if (!normalized || folderLevels === 0) return normalized;
    const parts = normalized.split('/');
    return parts.slice(-Math.min(parts.length, folderLevels + 1)).join('/');
}

function applyDocumentRelativePathToForm() {
    const config = getLinkedPdfPathConfig();
    if (!config) return false;
    const input = document.getElementById(`col_${config.col - 1}`);
    if (!input) return false;
    const value = formatLinkedPdfPath(activeDocumentRelativePath, config.folderLevels);
    if (input.value !== value) {
        input.value = value;
        if (typeof Event === 'function') {
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }
    return true;
}

function setActiveDocumentRelativePath(relativePath, waitForTemplateRender = false) {
    activeDocumentRelativePath = typeof relativePath === 'string'
        ? normalizeQueuePath(relativePath)
        : null;
    if (relativePathObserver) {
        relativePathObserver.disconnect();
        relativePathObserver = null;
    }
    if (!waitForTemplateRender && applyDocumentRelativePathToForm()) return;
    if (!activeDocumentRelativePath) return;
    if (!waitForTemplateRender && !getLinkedPdfPathConfig()) return;

    const formContainer = document.getElementById('form-container');
    if (!formContainer || typeof MutationObserver === 'undefined') return;
    relativePathObserver = new MutationObserver(() => {
        if (applyDocumentRelativePathToForm() || !getLinkedPdfPathConfig()) {
            relativePathObserver.disconnect();
            relativePathObserver = null;
        }
    });
    relativePathObserver.observe(formContainer, { childList: true, subtree: true });
}

function saveQueueState() {
    if (!currentUser) return;
    const activeFile = uploadedFilesQueue[iframeCurrentIndex] || null;
    const persistedQueue = uploadedFilesQueue.filter(file => file.temporary_view !== true);
    const persistedIndex = activeFile && activeFile.temporary_view !== true
        ? persistedQueue.indexOf(activeFile)
        : -1;
    localStorage.setItem(`pdfQueue_${currentUser.username}`, JSON.stringify(persistedQueue));
    localStorage.setItem(`pdfIndex_${currentUser.username}`, persistedIndex);
}

function showEmptyPdfQueueState(message = 'Chưa có tài liệu trong hàng chờ.') {
    iframeCurrentIndex = -1;
    activeDocumentRelativePath = null;
    activeDocumentFolderPath = null;
    activeQueueFolderKey = null;
    window.pdfLinkState.setLinked(false);
    const iframe = document.getElementById('pdfIframe');
    const placeholder = document.getElementById('pdfPlaceholder');
    if (iframe) iframe.style.display = 'none';
    if (placeholder) {
        placeholder.style.display = 'block';
        placeholder.innerHTML = message;
    }
    updatePdfLinkUI();
}

function clearTemporaryPdfView() {
    const activeFile = uploadedFilesQueue[iframeCurrentIndex] || null;
    const activeWasTemporary = activeFile?.temporary_view === true;
    const originalLength = uploadedFilesQueue.length;
    uploadedFilesQueue = uploadedFilesQueue.filter(file => file.temporary_view !== true);
    if (uploadedFilesQueue.length === originalLength) return false;

    iframeCurrentIndex = activeFile && !activeWasTemporary
        ? uploadedFilesQueue.indexOf(activeFile)
        : -1;
    saveQueueState();
    renderFileQueue();

    if (iframeCurrentIndex >= 0) return true;
    if (uploadedFilesQueue.length > 0) {
        selectFileFromQueue(0);
        return true;
    }

    showEmptyPdfQueueState();
    return true;
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

function openQueueFolder(folderKey) {
    activeQueueFolderKey = folderKey || null;
    renderFileQueue();
}

function appendQueueFileRow(fileQueueList, file, index) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'list-group-item list-group-item-action d-flex align-items-center';
    btn.style.fontSize = '0.9rem';
    btn.title = file.relative_path || file.name;

    const reviewStatus = typeof file.review_status === 'string' ? file.review_status : '';
    const isReviewFile = reviewStatus.length > 0;
    const isCompleted = isReviewFile ? reviewStatus === 'completed' : file.completed === true;
    const statusBadge = document.createElement('span');
    const isAwaitingInput = reviewStatus === 'pending_input_confirmation';
    statusBadge.className = isCompleted
        ? 'badge bg-success me-2'
        : (isAwaitingInput ? 'badge bg-info text-dark me-2' : (isReviewFile ? 'badge bg-warning text-dark me-2' : 'badge bg-secondary me-2'));
    statusBadge.textContent = isReviewFile
        ? (isCompleted ? 'Hoàn thành' : (isAwaitingInput ? 'Chờ người nhập xác nhận' : 'Chờ kiểm duyệt'))
        : (isCompleted ? 'Đã nhập' : 'Chưa nhập');

    const icon = document.createElement('i');
    icon.className = 'fas fa-file-pdf text-danger me-2';
    const textSpan = document.createElement('span');
    textSpan.className = 'text-truncate flex-grow-1 text-start';
    textSpan.innerText = getQueueDocumentName(file);
    if (isCompleted) textSpan.classList.add('text-success', 'text-decoration-line-through');

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'btn-close btn-close-sm ms-2';
    removeBtn.style.fontSize = '0.6rem';
    removeBtn.onclick = event => {
        event.stopPropagation();
        uploadedFilesQueue.splice(index, 1);
        if (iframeCurrentIndex === index) {
            if (uploadedFilesQueue.length > 0) {
                selectFileFromQueue(Math.min(index, uploadedFilesQueue.length - 1));
            } else {
                iframeCurrentIndex = -1;
                activeDocumentRelativePath = null;
                activeDocumentFolderPath = null;
                activeQueueFolderKey = null;
                document.getElementById('pdfIframe').style.display = 'none';
                document.getElementById('pdfPlaceholder').style.display = 'block';
                document.getElementById('pdfPlaceholder').innerHTML = 'Chưa có tài liệu nào được tải lên.<br>Vui lòng chọn file PDF hoặc hình ảnh ở cột bên trái.';
                updatePdfLinkUI();
            }
        } else if (iframeCurrentIndex > index) {
            iframeCurrentIndex--;
        }
        saveQueueState();
        renderFileQueue();
    };

    btn.appendChild(statusBadge);
    btn.appendChild(icon);
    btn.appendChild(textSpan);
    btn.appendChild(removeBtn);
    if (iframeCurrentIndex === index) {
        btn.classList.add('active');
        if (isCompleted) textSpan.classList.remove('text-success');
    }
    btn.onclick = () => selectFileFromQueue(index);
    fileQueueList.appendChild(btn);
}

function renderFileQueue() {
    const fileQueueList = document.getElementById('fileQueueList');
    const breadcrumb = document.getElementById('queueExplorerCurrentFolder');
    if (!fileQueueList) return;
    fileQueueList.innerHTML = '';

    const folders = new Map();
    uploadedFilesQueue.forEach((file, index) => {
        const key = getQueueFolderKey(file);
        if (!key) return;
        if (!folders.has(key)) {
            folders.set(key, {
                key,
                path: normalizeQueuePath(file.folder_group),
                templateName: file.template_name || 'Không xác định',
                entries: [],
            });
        }
        folders.get(key).entries.push({ file, index });
    });

    if (activeQueueFolderKey && !folders.has(activeQueueFolderKey)) activeQueueFolderKey = null;
    if (breadcrumb) breadcrumb.textContent = activeQueueFolderKey
        ? ` / ${getQueuePathTail(folders.get(activeQueueFolderKey).path)}`
        : '';

    if (!activeQueueFolderKey) {
        Array.from(folders.values())
            .sort((a, b) => a.path.localeCompare(b.path, 'vi'))
            .forEach(folder => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'list-group-item list-group-item-action d-flex align-items-center text-start';
                btn.title = folder.path;
                btn.onclick = () => openQueueFolder(folder.key);

                const icon = document.createElement('i');
                icon.className = 'fas fa-folder text-warning fs-4 me-2';
                const labels = document.createElement('span');
                labels.className = 'text-truncate flex-grow-1';
                const name = document.createElement('span');
                name.className = 'd-block fw-semibold text-truncate';
                name.textContent = getQueuePathTail(folder.path) || '(folder gốc)';
                const template = document.createElement('small');
                template.className = 'd-block text-muted text-truncate';
                template.textContent = folder.templateName;
                const count = document.createElement('span');
                count.className = 'badge bg-secondary rounded-pill';
                count.textContent = String(folder.entries.length);
                labels.appendChild(name);
                labels.appendChild(template);
                btn.appendChild(icon);
                btn.appendChild(labels);
                btn.appendChild(count);
                fileQueueList.appendChild(btn);
            });

        uploadedFilesQueue.forEach((file, index) => {
            if (!getQueueFolderKey(file)) appendQueueFileRow(fileQueueList, file, index);
        });
    } else {
        const back = document.createElement('button');
        back.type = 'button';
        back.className = 'list-group-item list-group-item-action fw-semibold text-primary';
        back.innerHTML = '<i class="fas fa-level-up-alt me-2"></i>Quay lại danh sách folder';
        back.onclick = () => openQueueFolder(null);
        fileQueueList.appendChild(back);
        folders.get(activeQueueFolderKey).entries.forEach(({ file, index }) => {
            appendQueueFileRow(fileQueueList, file, index);
        });
    }

    if (uploadedFilesQueue.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'list-group-item text-muted small';
        empty.textContent = 'Chưa có tài liệu trong hàng chờ.';
        fileQueueList.appendChild(empty);
    }
}


let isEditingFromList = false;

function togglePdfLink() {
    window.pdfLinkState.toggle();
    updatePdfLinkUI();
}

function updatePdfLinkUI() {
    const btn = document.getElementById('pdfLinkBtn');
    const text = document.getElementById('pdfLinkText');
    const folderBadge = document.getElementById('folderLinkBadge');
    const folderText = document.getElementById('folderLinkText');
    if (!btn || !text) return;
    
    if (window.pdfLinkState.isLinked()) {
        btn.classList.remove('btn-outline-secondary');
        btn.classList.add('btn-success');
        text.innerText = 'Đã liên kết PDF';
    } else {
        btn.classList.remove('btn-success');
        btn.classList.add('btn-outline-secondary');
        text.innerText = 'Không liên kết PDF';
    }
    if (folderText) folderText.innerText = activeDocumentFolderPath
        ? getQueuePathTail(activeDocumentFolderPath)
        : 'Chưa có folder';
    if (folderBadge) folderBadge.title = activeDocumentFolderPath || 'PDF này không có metadata folder';
}

async function selectFileFromQueue(index, { allowSubmissionNavigation = true } = {}) {
    if (index < 0 || index >= uploadedFilesQueue.length) return;
    
    iframeCurrentIndex = index;
    saveQueueState();
    const file = uploadedFilesQueue[index];
    activeQueueFolderKey = getQueueFolderKey(file);
    activeDocumentFolderPath = file.folder_group && file.folder_group !== '__ROOT__'
        ? normalizeQueuePath(file.folder_group)
        : null;
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
    
    // Auto-switch template if needed
    let templateChanged = false;
    if (file.template_id && window.activeTemplateId !== undefined && parseInt(file.template_id) !== parseInt(window.activeTemplateId)) {
        const select = document.getElementById('templateSelect');
        if (select) {
            templateChanged = true;
            select.value = file.template_id;
            select.dispatchEvent(new Event('change'));
        }
    }
    
    // Switching the reference PDF must not erase in-progress form data.
    setActiveDocumentRelativePath(file.relative_path || null, templateChanged);
    // Tự động liên kết file PDF này với form đang nhập
    window.pdfLinkState.setLinked(true);
    updatePdfLinkUI();
    renderFileQueue();
    
    // Only a deliberate click in the review queue may navigate to another
    // submission. Programmatic selections while opening a review must stay on
    // the submission requested by the user.
    if (allowSubmissionNavigation && isEditingFromList && file.submission_id && typeof currentEditingId !== 'undefined' && currentEditingId != file.submission_id && typeof editSubmission === 'function') {
        setTimeout(() => {
            editSubmission(file.submission_id);
        }, 0);
    }
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
            const currentQueueUuids = new Set();
            queueGroups.forEach(group => {
                if (group.files) {
                    group.files.forEach(doc => {
                        if (doc.uuid) currentQueueUuids.add(String(doc.uuid));
                    });
                }
            });

            const activeFile = uploadedFilesQueue[iframeCurrentIndex] || null;
            uploadedFilesQueue = uploadedFilesQueue.filter(file => {
                if (file.temporary_view === true) return false;
                // Nếu là file được giao từ server (có template_id) 
                // nhưng lại không nằm trong danh sách queue mới nhất thì xóa khỏi hàng chờ
                if (file.template_id !== undefined && file.template_id !== null) {
                    return file.uuid && currentQueueUuids.has(String(file.uuid));
                }
                
                return true;
            });
            iframeCurrentIndex = activeFile && uploadedFilesQueue.includes(activeFile)
                ? uploadedFilesQueue.indexOf(activeFile)
                : -1;
            if (queueGroups.length === 0) {
                alert("Bạn không có tài liệu nào đang chờ xử lý.");
            } else {
                let added = 0;
                queueGroups.forEach(group => {
                    group.files.forEach(doc => {
                        const existingFile = uploadedFilesQueue.find(f => f.url === doc.url);
                        if (existingFile) {
                            existingFile.name = doc.name;
                            existingFile.uuid = doc.uuid;
                            existingFile.relative_path = doc.relative_path || null;
                            existingFile.folder_group = doc.folder_group || null;
                            existingFile.template_id = group.template_id;
                            existingFile.template_name = group.template_name;
                            existingFile.temporary_view = false;
                            existingFile.completed = doc.entered === true;
                        } else {
                            uploadedFilesQueue.push({
                                name: doc.name,
                                url: doc.url,
                                uuid: doc.uuid,
                                relative_path: doc.relative_path || null,
                                folder_group: doc.folder_group || null,
                                template_id: group.template_id,
                                template_name: group.template_name,
                                temporary_view: false,
                                completed: doc.entered === true,
                            });
                            added++;
                        }
                    });
                });
                
                uploadedFilesQueue.sort((a, b) => {
                    const templateOrder = (a.template_id || 0) - (b.template_id || 0);
                    if (templateOrder !== 0) return templateOrder;
                    return (a.relative_path || a.name).localeCompare(
                        b.relative_path || b.name,
                        'vi'
                    );
                });
                
                if (added > 0) {
                    alert(`Đã nhận thêm ${added} tài liệu vào danh sách chờ.`);
                }
                
            }

            saveQueueState();
            renderFileQueue();

            // Select first file if nothing is selected
            if (uploadedFilesQueue.length > 0 && iframeCurrentIndex === -1) {
                selectFileFromQueue(0);
            } else if (uploadedFilesQueue.length === 0) {
                showEmptyPdfQueueState();
            }
        }
        
        if(btn) btn.innerHTML = '<i class="fas fa-download"></i> Tải tài liệu được giao';
    } catch (err) {
        console.error(err);
        alert('Lỗi tải tài liệu: ' + err.message);
    }
}

function addFileToQueueAndSelect(attachedPdf, attachedPdfUuid, attachedPdfUrl, metadata = {}) {
    if (!attachedPdf) return;

    const resolvedUrl = attachedPdfUrl || (attachedPdfUuid
        ? `/api/files/${encodeURIComponent(attachedPdfUuid)}`
        : null);
    if (!resolvedUrl) {
        alert(`Không tìm thấy file PDF đã liên kết: ${attachedPdf}`);
        return;
    }

    const normalizedResolvedUrl = normalizePdfUrl(resolvedUrl);
    const targetRelativePath = normalizeQueuePath(metadata.relative_path);
    const targetFolderPath = normalizeQueuePath(metadata.folder_group);
    const targetDocumentName = getQueuePathTail(attachedPdf);
    const identityMatches = uploadedFilesQueue
        .map((file, index) => ({ file, index }))
        .filter(({ file }) =>
            (attachedPdfUuid && file.uuid === attachedPdfUuid)
            || normalizePdfUrl(file.url) === normalizedResolvedUrl
            || (targetRelativePath && normalizeQueuePath(file.relative_path) === targetRelativePath)
            || (
                targetFolderPath
                && normalizeQueuePath(file.folder_group) === targetFolderPath
                && getQueueDocumentName(file) === targetDocumentName
            )
        );
    let fileIndex = identityMatches.length > 0 ? identityMatches[0].index : -1;
    if (fileIndex === -1) {
        const legacyMatches = uploadedFilesQueue
            .map((file, index) => ({ file, index }))
            .filter(({ file }) => getQueueDocumentName(file) === targetDocumentName && !file.uuid);
        if (legacyMatches.length === 1) {
            fileIndex = legacyMatches[0].index;
        }
    }
    if (fileIndex === -1) {
        uploadedFilesQueue.push({
            name: attachedPdf,
            uuid: attachedPdfUuid,
            url: resolvedUrl,
            relative_path: metadata.relative_path || null,
            folder_group: metadata.folder_group || null,
            template_id: metadata.template_id || null,
            template_name: metadata.template_name || null,
            temporary_view: metadata.temporary_view === true,
        });
        fileIndex = uploadedFilesQueue.length - 1;
        renderFileQueue();
        saveQueueState();
    } else {
        uploadedFilesQueue[fileIndex].name = attachedPdf || uploadedFilesQueue[fileIndex].name;
        uploadedFilesQueue[fileIndex].uuid = attachedPdfUuid || uploadedFilesQueue[fileIndex].uuid;
        uploadedFilesQueue[fileIndex].url = resolvedUrl;
        uploadedFilesQueue[fileIndex].relative_path = metadata.relative_path || uploadedFilesQueue[fileIndex].relative_path || null;
        uploadedFilesQueue[fileIndex].folder_group = metadata.folder_group || uploadedFilesQueue[fileIndex].folder_group || null;
        uploadedFilesQueue[fileIndex].template_id = metadata.template_id || uploadedFilesQueue[fileIndex].template_id || null;
        uploadedFilesQueue[fileIndex].template_name = metadata.template_name || uploadedFilesQueue[fileIndex].template_name || null;
        uploadedFilesQueue[fileIndex].temporary_view = metadata.temporary_view === true;
        const duplicateIndexes = identityMatches
            .map(match => match.index)
            .filter(index => index !== fileIndex)
            .sort((a, b) => b - a);
        duplicateIndexes.forEach(index => {
            uploadedFilesQueue.splice(index, 1);
            if (index < fileIndex) fileIndex--;
        });
        if (duplicateIndexes.length > 0) renderFileQueue();
        saveQueueState();
    }
    
    selectFileFromQueue(fileIndex);
    window.pdfLinkState.setLinked(true);
}

function loadReviewFolderFiles(folderFiles, selectedUuid) {
    if (!Array.isArray(folderFiles) || folderFiles.length === 0) return false;

    const folderPath = normalizeQueuePath(folderFiles[0].folder_group);
    if (folderPath) {
        uploadedFilesQueue = uploadedFilesQueue.filter(file =>
            file.temporary_view !== true
            || normalizeQueuePath(file.folder_group) !== folderPath
        );
    }

    folderFiles.forEach(file => {
        uploadedFilesQueue.push({
            name: file.name,
            uuid: file.uuid,
            url: file.url,
            relative_path: file.relative_path || null,
            folder_group: file.folder_group || null,
            template_id: file.template_id || null,
            template_name: file.template_name || null,
            submission_id: file.submission_id || null,
            review_status: file.review_status || null,
            temporary_view: true,
        });
    });
    uploadedFilesQueue.sort((a, b) =>
        (a.relative_path || a.name || '').localeCompare(
            b.relative_path || b.name || '',
            'vi'
        )
    );
    let selectedIndex = selectedUuid
        ? uploadedFilesQueue.findIndex(file => String(file.uuid) === String(selectedUuid))
        : -1;
    if (selectedIndex < 0 && typeof currentEditingId !== 'undefined' && currentEditingId !== null) {
        selectedIndex = uploadedFilesQueue.findIndex(file =>
            file.temporary_view === true
            && file.submission_id !== null
            && String(file.submission_id) === String(currentEditingId)
        );
    }
    const fallbackIndex = uploadedFilesQueue.findIndex(file =>
        file.temporary_view === true
        && normalizeQueuePath(file.folder_group) === folderPath
    );
    const displayIndex = selectedIndex >= 0 ? selectedIndex : fallbackIndex;
    if (displayIndex < 0) return false;
    activeQueueFolderKey = getQueueFolderKey(uploadedFilesQueue[displayIndex]);
    renderFileQueue();
    saveQueueState();
    selectFileFromQueue(displayIndex, { allowSubmissionNavigation: false });
    window.pdfLinkState.setLinked(selectedIndex >= 0);
    return true;
}
