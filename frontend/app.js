document.addEventListener("DOMContentLoaded", () => {
    fetchMaXaMapping();
    fetchDonViDoMapping();
    fetchSchema();
    setupPdfUpload();
    restoreQueue();
});

let maXaMapping = null;
let donViDoMapping = null;

async function fetchMaXaMapping() {
    try {
        const response = await fetch('/api/maxa_mapping');
        const res = await response.json();
        if (res.status === 'ok') {
            maXaMapping = res.data;
        }
    } catch (err) {
        console.error("Lỗi tải mapping mã xã: " + err);
    }
}

async function fetchDonViDoMapping() {
    try {
        const response = await fetch('/api/don-vi-do-mapping');
        const res = await response.json();
        if (res.status === 'ok') {
            donViDoMapping = res.data;
        }
    } catch (err) {
        console.error("Lỗi tải mapping đơn vị đo: " + err);
    }
}

let formDataCache = {};
let uploadedFilesQueue = [];
let iframeCurrentIndex = -1;

function saveQueueState() {
    localStorage.setItem('pdfQueue', JSON.stringify(uploadedFilesQueue));
    localStorage.setItem('pdfIndex', iframeCurrentIndex);
}

function restoreQueue() {
    try {
        const storedQueue = localStorage.getItem('pdfQueue');
        const storedIndex = localStorage.getItem('pdfIndex');
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
                placeholder.innerHTML = `Đang tải ${file.name}...`;
            }
            
            try {
                const response = await fetch('/api/upload-pdf', {
                    method: 'POST',
                    body: formData
                });
                const res = await response.json();
                
                if (res.status === 'ok') {
                    const fileItem = {
                        name: file.name,
                        url: res.url
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
    
    uploadedFilesQueue.forEach((file, index) => {
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
    
    iframe.src = file.url;
    iframe.onload = () => {
        placeholder.style.display = 'none';
        iframe.style.display = 'block';
    };
    
    renderFileQueue(); // Re-render to update the active class
    
    // Check if this PDF is linked to a submission
    try {
        const response = await fetch(`/api/submissions/by-pdf?filename=${encodeURIComponent(file.name)}`);
        const res = await response.json();
        
        if (res.status === 'ok' && res.data) {
            // Load the data into the form
            const data = res.data;
            for (const [key, value] of Object.entries(data)) {
                const input = document.getElementById(key);
                if (input) {
                    input.value = value;
                }
            }
            
            // Set editing state
            currentEditingId = res.id;
            document.getElementById('submitBtn').innerText = 'Cập nhật Hồ sơ';
            document.getElementById('cancelEditBtn').classList.remove('d-none');
            
            // Set link active
            isPdfLinked = true;
            updatePdfLinkUI();
        } else {
            // No linked submission, clear the form
            resetFormData(true);
        }
    } catch (err) {
        console.error("Error checking PDF link: ", err);
    }
}

async function fetchSchema() {
    try {
        const response = await fetch('/api/schema');
        const res = await response.json();
        if (res.status === 'ok') {
            renderForm(res.data);
        } else {
            alert("Lỗi tải dữ liệu: " + res.message);
        }
    } catch (err) {
        alert("Lỗi kết nối máy chủ: " + err);
    }
}

function renderForm(schema) {
    const container = document.getElementById('form-container');
    container.innerHTML = '';
    
    // Load draft from localStorage
    let draftData = {};
    try {
        const stored = localStorage.getItem('formDraft');
        if (stored) draftData = JSON.parse(stored);
    } catch (e) {}
    
    schema.forEach((category, index) => {
        const section = document.createElement('div');
        section.className = 'form-section';
        
        // Category Title with Collapsible Icon
        const titleContainer = document.createElement('div');
        titleContainer.className = 'form-section-title d-flex justify-content-between align-items-center mb-0 pb-2 border-bottom border-2 border-primary mb-3';
        
        const titleLeft = document.createElement('div');
        titleLeft.className = 'd-flex align-items-center text-primary fw-bold fs-5';
        titleLeft.style.cursor = 'pointer';
        titleLeft.innerHTML = `<i class="fas fa-chevron-down me-2 transition-icon" style="width: 20px; transition: transform 0.2s;"></i>${category.category}`;
        
        const clearCategoryBtn = document.createElement('button');
        clearCategoryBtn.type = 'button';
        clearCategoryBtn.className = 'btn btn-sm btn-outline-danger';
        clearCategoryBtn.innerHTML = `<i class="fas fa-eraser me-1"></i>Xóa sạch`;
        clearCategoryBtn.title = `Làm sạch dữ liệu mục ${category.category}`;
        
        titleContainer.appendChild(titleLeft);
        titleContainer.appendChild(clearCategoryBtn);
        section.appendChild(titleContainer);
        
        const categoryContent = document.createElement('div');
        categoryContent.className = 'category-content mt-3';
        
        // Collapse all categories by default except the first one (index 0)
        if (index !== 0) {
            categoryContent.classList.add('d-none');
            titleLeft.querySelector('i').classList.replace('fa-chevron-down', 'fa-chevron-right');
        }
        
        titleLeft.addEventListener('click', () => {
            categoryContent.classList.toggle('d-none');
            const icon = titleLeft.querySelector('i');
            if (categoryContent.classList.contains('d-none')) {
                icon.classList.replace('fa-chevron-down', 'fa-chevron-right');
            } else {
                icon.classList.replace('fa-chevron-right', 'fa-chevron-down');
            }
        });
        
        clearCategoryBtn.addEventListener('click', () => {
            if (!confirm(`Bạn có chắc chắn muốn xóa sạch dữ liệu trong mục "${category.category}"?`)) return;
            const inputs = categoryContent.querySelectorAll('input');
            inputs.forEach(input => {
                if (input.type !== 'button' && input.type !== 'submit') {
                    input.value = '';
                }
            });
            const selects = categoryContent.querySelectorAll('select');
            selects.forEach(select => select.value = '');
            if (typeof saveFormDraft === 'function') saveFormDraft();
        });
        
        let row = document.createElement('div');
        row.className = 'row g-3';
        categoryContent.appendChild(row);
        
        let activeGroupEnd = -1;
        let activeGroupRow = null;
        
        category.fields.forEach(field => {
            // Check if active group has ended
            if (activeGroupEnd !== -1 && (field.col_index + 1) > activeGroupEnd) {
                activeGroupEnd = -1;
                activeGroupRow = null;
            }
            
            if (field.separator_above) {
                const sepWrapper = document.createElement('div');
                sepWrapper.className = 'col-12 mt-4 mb-1';
                
                const sepTitle = document.createElement('h5');
                sepTitle.className = 'text-primary border-bottom pb-2 d-flex align-items-center';
                sepTitle.style.cursor = 'pointer';
                sepTitle.innerHTML = `<i class="fas fa-chevron-right me-2 text-secondary fs-6 transition-icon" style="width: 15px; transition: transform 0.2s;"></i>${field.separator_above}`;
                
                const subRow = document.createElement('div');
                subRow.className = 'row g-3 p-2 mt-1 d-none';
                subRow.style.borderLeft = '3px solid #e9ecef';
                subRow.style.marginLeft = '5px';
                
                sepTitle.addEventListener('click', () => {
                    subRow.classList.toggle('d-none');
                    const icon = sepTitle.querySelector('i');
                    if (subRow.classList.contains('d-none')) {
                        icon.classList.replace('fa-chevron-down', 'fa-chevron-right');
                    } else {
                        icon.classList.replace('fa-chevron-right', 'fa-chevron-down');
                    }
                });
                
                sepWrapper.appendChild(sepTitle);
                sepWrapper.appendChild(subRow);
                row.appendChild(sepWrapper);
                
                if (field.group_end) {
                    activeGroupEnd = field.group_end;
                    activeGroupRow = subRow;
                } else {
                    activeGroupEnd = 9999; 
                    activeGroupRow = subRow;
                }
            }
            
            const targetRow = activeGroupRow ? activeGroupRow : row;
            
            const col = document.createElement('div');
            col.className = 'col-12';
            
            const formGroup = document.createElement('div');
            formGroup.className = 'position-relative';
            
            const label = document.createElement('label');
            label.className = 'form-label fw-semibold';
            label.innerText = field.label;
            formGroup.appendChild(label);
            
            const input = document.createElement('input');
            input.type = 'text';
            input.className = 'form-control';
            input.name = field.name;
            input.id = field.name;
            input.setAttribute('autocomplete', 'off');
            
            // Make auto-generated fields read-only
            if (['col_2', 'col_19', 'col_36', 'col_21', 'col_38', 'col_93'].includes(field.name)) {
                input.readOnly = true;
                input.style.backgroundColor = '#e9ecef';
            }
            
            if (field.name === 'col_2' || field.name === 'col_3') {
                // Real-time autofill as user types/scans
                if (field.name === 'col_3') {
                    input.addEventListener('input', function() {
                        let val = this.value.replace(/\s+/g, '');
                        const col2Input = document.getElementById('col_2');
                        if (col2Input) {
                            if (val.length >= 6) {
                                col2Input.value = val.slice(-6);
                            } else {
                                col2Input.value = ''; // Xóa trắng khi chuỗi ngắn hơn 6 ký tự
                            }
                        }
                    });
                }
                
                input.addEventListener('blur', function() {
                    this.value = this.value.replace(/\s+/g, '');
                    if (typeof saveFormDraft === 'function') saveFormDraft();
                });
            }
            
            // Tự động nối Địa chỉ đầy đủ (22, 39, và 94)
            if (['col_18', 'col_20', 'col_35', 'col_37', 'col_91', 'col_92'].includes(field.name)) {
                input.addEventListener('input', function() {
                    if (field.name === 'col_18' || field.name === 'col_20') {
                        let f19 = document.getElementById('col_18');
                        let f21 = document.getElementById('col_20');
                        let f22 = document.getElementById('col_21');
                        if (f22) {
                            let parts = [];
                            if (f19 && f19.value.trim()) parts.push(f19.value.trim());
                            if (f21 && f21.value.trim()) parts.push(f21.value.trim());
                            f22.value = parts.join(', ');
                        }
                    }
                    if (field.name === 'col_35' || field.name === 'col_37') {
                        let f36 = document.getElementById('col_35');
                        let f38 = document.getElementById('col_37');
                        let f39 = document.getElementById('col_38');
                        if (f39) {
                            let parts = [];
                            if (f36 && f36.value.trim()) parts.push(f36.value.trim());
                            if (f38 && f38.value.trim()) parts.push(f38.value.trim());
                            f39.value = parts.join(', ');
                        }
                    }
                    if (field.name === 'col_91' || field.name === 'col_92') {
                        let f92 = document.getElementById('col_91');
                        let f93 = document.getElementById('col_92');
                        let f94 = document.getElementById('col_93');
                        if (f94) {
                            let parts = [];
                            if (f92 && f92.value.trim()) parts.push(f92.value.trim());
                            if (f93 && f93.value.trim()) parts.push(f93.value.trim());
                            f94.value = parts.join(', ');
                        }
                    }
                });
            }

            if (['col_20', 'col_37', 'col_92'].includes(field.name)) {
                input.addEventListener('input', function() {
                    if (!maXaMapping) return;
                    
                    let val = this.value.trim();
                    if (!val) {
                        if (field.name === 'col_20') {
                            let t = document.getElementById('col_19');
                            if (t) t.value = '';
                        }
                        if (field.name === 'col_37') {
                            let t = document.getElementById('col_36');
                            if (t) t.value = '';
                        }
                        return;
                    }
                    
                    let normalizedVal = val.toLowerCase().replace(/[^a-z0-9áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ]/g, '');
                    
                    let matchedKey = null;
                    let matchObj = null;
                    
                    for (let key in maXaMapping.mapping_3_cap) {
                        if (normalizedVal.endsWith(key)) {
                            if (!matchedKey || key.length > matchedKey.length) {
                                matchedKey = key;
                                matchObj = maXaMapping.mapping_3_cap[key];
                            }
                        }
                    }
                    for (let key in maXaMapping.mapping_2_cap) {
                        if (normalizedVal.endsWith(key)) {
                            if (!matchedKey || key.length > matchedKey.length) {
                                matchedKey = key;
                                matchObj = maXaMapping.mapping_2_cap[key];
                            }
                        }
                    }
                    
                    if (matchObj) {
                        let prefixNormLen = normalizedVal.length - matchedKey.length;
                        let count = 0;
                        let splitIdx = 0;
                        for (let i = 0; i < val.length; i++) {
                            if (count === prefixNormLen) {
                                splitIdx = i;
                                break;
                            }
                            let charNorm = val[i].toLowerCase().replace(/[^a-z0-9áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ]/g, '');
                            if (charNorm) count++;
                        }
                        
                        let prefixOriginal = val.substring(0, splitIdx).trim();
                        prefixOriginal = prefixOriginal.replace(/(^[\s,]+)|([\s,]+$)/g, '');
                        
                        let finalStr = prefixOriginal ? (prefixOriginal + ", " + matchObj.formatted) : matchObj.formatted;
                        
                        this.value = finalStr;
                        
                        if (field.name === 'col_20') {
                            let maXa = document.getElementById('col_19');
                            if (maXa) maXa.value = matchObj.code;
                            
                            let f19 = document.getElementById('col_18');
                            let f22 = document.getElementById('col_21');
                            if (f22) {
                                let parts = [];
                                if (f19 && f19.value.trim()) parts.push(f19.value.trim());
                                parts.push(finalStr);
                                f22.value = parts.join(', ');
                            }
                        }
                        
                        if (field.name === 'col_37') {
                            let maXa = document.getElementById('col_36');
                            if (maXa) maXa.value = matchObj.code;
                            
                            let f36 = document.getElementById('col_35');
                            let f39 = document.getElementById('col_38');
                            if (f39) {
                                let parts = [];
                                if (f36 && f36.value.trim()) parts.push(f36.value.trim());
                                parts.push(finalStr);
                                f39.value = parts.join(', ');
                            }
                        }
                        
                        if (field.name === 'col_92') {
                            // Không có mã xã cho mục 93
                            
                            let f92 = document.getElementById('col_91');
                            let f94 = document.getElementById('col_93');
                            if (f94) {
                                let parts = [];
                                if (f92 && f92.value.trim()) parts.push(f92.value.trim());
                                parts.push(finalStr);
                                f94.value = parts.join(', ');
                            }
                            
                            // Mục 47 = Tên đơn vị đo
                            let f47 = document.getElementById('col_46');
                            if (f47 && donViDoMapping) {
                                let searchStr = (matchObj.formatted || finalStr).replace(/(, Tỉnh Quảng Ninh)/g, '');
                                let key = searchStr.toLowerCase().replace(/[^a-z0-9áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ]/g, '');
                                if (donViDoMapping[key]) {
                                    f47.value = donViDoMapping[key];
                                } else {
                                    // Try to match only the ward part in case District is omitted in mapping
                                    let wardStr = searchStr.split(',')[0].toLowerCase().replace(/[^a-z0-9áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ]/g, '');
                                    let found = false;
                                    for (let mapKey in donViDoMapping) {
                                        if (mapKey.startsWith(wardStr)) {
                                            f47.value = donViDoMapping[mapKey];
                                            found = true;
                                            break;
                                        }
                                    }
                                    // Optionally clear if not found, or leave it
                                }
                            }
                        }
                    }
                });
            }
            
            if (field.name === 'col_10' || field.name === 'col_27') {
                input.placeholder = 'dd/mm/yyyy';
                input.maxLength = 10;
                input.addEventListener('blur', function() {
                    let v = this.value.replace(/\D/g, '');
                    if (v.length >= 4) {
                        this.value = v.slice(0, 2) + '/' + v.slice(2, 4) + '/' + v.slice(4, 8);
                    } else if (v.length >= 2) {
                        this.value = v.slice(0, 2) + '/' + v.slice(2);
                    }
                    if (typeof saveFormDraft === 'function') saveFormDraft();
                });
            }
            
            if (field.name === 'col_11' || field.name === 'col_28') {
                input.placeholder = 'yyyy';
                input.maxLength = 4;
                input.addEventListener('input', function() {
                    this.value = this.value.replace(/\D/g, '');
                    if (typeof saveFormDraft === 'function') saveFormDraft();
                });
            }
            
            if (draftData[field.name]) {
                input.value = draftData[field.name];
            }
            
            formGroup.appendChild(input);
            col.appendChild(formGroup);
            targetRow.appendChild(col);
            
            if (field.type === 'dropdown' && field.options) {
                autocomplete(input, field.options, field.extract_mode);
            }
        });
        
        section.appendChild(categoryContent);
        container.appendChild(section);
    });
    
    // Attach listener for real-time draft saving
    document.getElementById('dataForm').addEventListener('input', saveFormDraft);
    
    // Auto-update Nguồn gốc chi tiết từ Mã
    const linkedPairs = [[59, 60], [67, 68], [75, 76], [83, 84]];
    linkedPairs.forEach(pair => {
        let colA = document.getElementById('col_' + pair[0]);
        let colB = document.getElementById('col_' + pair[1]);
        if (colA && colB) {
            colB.readOnly = true;
            colB.style.backgroundColor = "#e9ecef";
            colB.placeholder = "Tự động lấy theo Mã nguồn gốc";
            
            let colAField = null;
            schema.forEach(cat => {
                cat.fields.forEach(f => {
                    if (f.name === 'col_' + pair[0]) colAField = f;
                });
            });
            
            if (colAField && colAField.options) {
                let opts = colAField.options;
                const updateColB = function() {
                    let val = this.value;
                    let matched = opts.find(o => o.startsWith(val + " - "));
                    if (matched) {
                        colB.value = matched.split(" - ").slice(1).join(" - ").trim();
                        saveFormDraft();
                    } else {
                        colB.value = "";
                        saveFormDraft();
                    }
                };
                colA.addEventListener('change', updateColB);
                colA.addEventListener('input', updateColB);
            }
        }
    });
    
    document.getElementById('loading').style.display = 'none';
    document.getElementById('appTabs').style.display = 'flex';
    document.getElementById('dataForm').style.display = 'block';
}

function saveFormDraft() {
    // Do not save draft if we are editing an existing record
    if (currentEditingId !== null) return;
    
    const inputs = document.querySelectorAll('#dataForm input[type="text"]');
    const data = {};
    inputs.forEach(input => {
        data[input.name] = input.value;
    });
    localStorage.setItem('formDraft', JSON.stringify(data));
}

function autocomplete(inp, arr, extractMode = "none") {
    let currentFocus;
    
    inp.addEventListener("input", function(e) {
        let a, b, i, val = this.value;
        closeAllLists();
        if (!val) {
            showFullList(this);
            return;
        }
        currentFocus = -1;
        
        a = document.createElement("DIV");
        a.setAttribute("id", this.id + "autocomplete-list");
        a.setAttribute("class", "autocomplete-items");
        this.parentNode.appendChild(a);
        
        for (i = 0; i < arr.length; i++) {
            if (arr[i].toLowerCase().includes(val.toLowerCase())) {
                b = document.createElement("DIV");
                let matchIdx = arr[i].toLowerCase().indexOf(val.toLowerCase());
                b.innerHTML = arr[i].substr(0, matchIdx) + "<strong>" + arr[i].substr(matchIdx, val.length) + "</strong>" + arr[i].substr(matchIdx + val.length);
                b.innerHTML += "<input type='hidden' value='" + arr[i] + "'>";
                b.addEventListener("mousedown", function(e) {
                    e.preventDefault(); // Prevent blur from firing
                    let selectedVal = this.getElementsByTagName("input")[0].value;
                    
                    if (extractMode === "left") {
                        if (selectedVal.includes(" - ")) selectedVal = selectedVal.split(" - ")[0].trim();
                    } else if (extractMode === "right") {
                        if (selectedVal.includes(" - ")) selectedVal = selectedVal.split(" - ").slice(1).join(" - ").trim();
                    } else if (extractMode === "ABCD") {
                        let match = selectedVal.match(/Loai\s+([A-Z])/i);
                        if (match) selectedVal = match[1].toUpperCase();
                    }
                    
                    inp.value = selectedVal;
                    closeAllLists();
                    // Trigger draft save
                    saveFormDraft();
                    inp.dispatchEvent(new Event('change'));
                });
                a.appendChild(b);
            }
        }
    });
    
    inp.addEventListener("keydown", function(e) {
        let x = document.getElementById(this.id + "autocomplete-list");
        if (x) x = x.getElementsByTagName("div");
        if (e.keyCode == 40) { // Down
            currentFocus++;
            addActive(x);
        } else if (e.keyCode == 38) { // Up
            currentFocus--;
            addActive(x);
        } else if (e.keyCode == 9) { // Tab
            if (currentFocus > -1 && x) {
                let event = new MouseEvent('mousedown', {
                    view: window,
                    bubbles: true,
                    cancelable: true
                });
                x[currentFocus].dispatchEvent(event);
            }
            closeAllLists();
        } else if (e.keyCode == 13) { // Enter
            e.preventDefault();
            if (currentFocus > -1) {
                if (x) {
                    let event = new MouseEvent('mousedown', {
                        view: window,
                        bubbles: true,
                        cancelable: true
                    });
                    x[currentFocus].dispatchEvent(event);
                }
            }
        }
    });
    
    function addActive(x) {
        if (!x) return false;
        removeActive(x);
        if (currentFocus >= x.length) currentFocus = 0;
        if (currentFocus < 0) currentFocus = (x.length - 1);
        x[currentFocus].classList.add("autocomplete-active");
        x[currentFocus].scrollIntoView({ block: "nearest" });
    }
    
    function removeActive(x) {
        for (let i = 0; i < x.length; i++) {
            x[i].classList.remove("autocomplete-active");
        }
    }
    
    function closeAllLists(elmnt) {
        let x = document.getElementsByClassName("autocomplete-items");
        for (let i = 0; i < x.length; i++) {
            if (elmnt != x[i] && elmnt != inp) {
                x[i].parentNode.removeChild(x[i]);
            }
        }
    }
    
    function showFullList(inputEl) {
        closeAllLists();
        currentFocus = -1;
        
        let a = document.createElement("DIV");
        a.setAttribute("id", inputEl.id + "autocomplete-list");
        a.setAttribute("class", "autocomplete-items");
        inputEl.parentNode.appendChild(a);
        
        for (let i = 0; i < arr.length; i++) {
            let b = document.createElement("DIV");
            b.innerHTML = arr[i];
            b.innerHTML += "<input type='hidden' value='" + arr[i] + "'>";
            b.addEventListener("mousedown", function(e) {
                e.preventDefault();
                let selectedVal = this.getElementsByTagName("input")[0].value;
                
                if (extractMode === "left") {
                    if (selectedVal.includes(" - ")) selectedVal = selectedVal.split(" - ")[0].trim();
                } else if (extractMode === "right") {
                    if (selectedVal.includes(" - ")) selectedVal = selectedVal.split(" - ").slice(1).join(" - ").trim();
                } else if (extractMode === "ABCD") {
                    let match = selectedVal.match(/Loai\s+([A-Z])/i);
                    if (match) selectedVal = match[1].toUpperCase();
                }
                
                inputEl.value = selectedVal;
                closeAllLists();
                saveFormDraft();
                inputEl.dispatchEvent(new Event('change'));
            });
            a.appendChild(b);
        }
    }
    
    // Close when clicking outside
    document.addEventListener("mousedown", function(e) {
        let lists = document.getElementsByClassName("autocomplete-items");
        let isInside = false;
        for (let i = 0; i < lists.length; i++) {
            if (lists[i].contains(e.target) || e.target === inp) {
                isInside = true;
                break;
            }
        }
        if (!isInside) {
            closeAllLists();
        }
    });
    
    // Show full list on focus if empty
    inp.addEventListener("focus", function(e) {
        if (arr && arr.length > 0) {
            if (this.value === "") {
                showFullList(this);
            } else {
                // Trigger input event to show filtered list
                this.dispatchEvent(new Event('input'));
            }
        }
    });
}

let currentEditingId = null;

async function submitData() {
    const inputs = document.querySelectorAll('#dataForm input[type="text"]');
    const data = {};
    inputs.forEach(input => {
        data[input.name] = input.value;
    });
    
    // Attach PDF filename if linked
    if (isPdfLinked && iframeCurrentIndex >= 0 && iframeCurrentIndex < uploadedFilesQueue.length) {
        data['_pdf_filename'] = uploadedFilesQueue[iframeCurrentIndex].name;
    }
    
    const isEditing = currentEditingId !== null;
    const url = isEditing ? `/api/submissions/${currentEditingId}` : '/api/submit';
    const method = isEditing ? 'PUT' : 'POST';
    
    try {
        const response = await fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ data: data })
        });
        const res = await response.json();
        
        if (res.status === 'ok') {
            alert('Lưu thành công!');
            
            // Mark the file as completed in the queue
            if (isPdfLinked && iframeCurrentIndex >= 0) {
                uploadedFilesQueue[iframeCurrentIndex].completed = true;
                saveQueueState();
                renderFileQueue();
            }
            
            if (isEditing) {
                cancelEdit();
                fetchSubmissions();
                // Switch back to list tab
                const listTab = new bootstrap.Tab(document.getElementById('list-tab'));
                listTab.show();
            } else {
                // Clear form and draft
                inputs.forEach(input => input.value = '');
                localStorage.removeItem('formDraft');
                fetchSubmissions();
                
                // Auto-advance to next PDF if available
                if (uploadedFilesQueue.length > 0 && iframeCurrentIndex >= 0 && iframeCurrentIndex < uploadedFilesQueue.length - 1) {
                    selectFileFromQueue(iframeCurrentIndex + 1);
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
    const inputs = document.querySelectorAll('#dataForm input[type="text"]');
    inputs.forEach(input => input.value = '');
    
    document.getElementById('submitBtn').innerText = 'Lưu hồ sơ';
    document.getElementById('cancelEditBtn').classList.add('d-none');
    
    isPdfLinked = false;
    updatePdfLinkUI();
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
        localStorage.removeItem('formDraft');
    }
}

async function fetchSubmissions() {
    try {
        const response = await fetch('/api/submissions');
        const res = await response.json();
        
        const tbody = document.getElementById('submissionsTableBody');
        tbody.innerHTML = '';
        
        if (res.status === 'ok') {
            if (res.data.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" class="text-center">Chưa có dữ liệu</td></tr>';
                return;
            }
            
            res.data.forEach(sub => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td>${sub.id}</td>
                    <td>${sub.created_at}</td>
                    <td class="fw-bold text-primary">${sub.ho_ten}</td>
                    <td>${sub.so_giay_to}</td>
                    <td>
                        ${sub.pdf_filename ? `<span class="badge bg-success" style="cursor: pointer;" onclick="editSubmission(${sub.id})" title="Nhấn để xem PDF và sửa hồ sơ">${sub.pdf_filename}</span>` : '<span class="text-muted fst-italic">Không</span>'}
                    </td>
                    <td>
                        <button class="btn btn-sm btn-outline-success me-1" onclick="copySubmission(${sub.id})">Nhân bản</button>
                        <button class="btn btn-sm btn-outline-primary me-1" onclick="editSubmission(${sub.id})">Sửa</button>
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteSubmission(${sub.id})">Xóa</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        }
    } catch (err) {
        console.error("Lỗi tải danh sách: " + err);
    }
}

async function copySubmission(id) {
    if (!confirm('Bạn có chắc muốn nhân bản hồ sơ này? Bản sao sẽ được tạo ngay lập tức.')) return;
    try {
        const response = await fetch(`/api/submissions/${id}/copy`, { method: 'POST' });
        const res = await response.json();
        if (res.status === 'ok') {
            fetchSubmissions();
        } else {
            alert('Lỗi: ' + res.message);
        }
    } catch (err) {
        alert('Lỗi kết nối: ' + err);
    }
}

async function editSubmission(id) {
    try {
        const response = await fetch(`/api/submissions/${id}`);
        const res = await response.json();
        
        if (res.status === 'ok') {
            // Switch to form tab
            const formTab = new bootstrap.Tab(document.getElementById('form-tab'));
            formTab.show();
            
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
            document.getElementById('submitBtn').innerText = 'Cập nhật Hồ sơ';
            document.getElementById('cancelEditBtn').classList.remove('d-none');
            
            // Check if there is an attached PDF
            const attachedPdf = data._pdf_filename;
            if (attachedPdf) {
                // Find in the queue
                const fileIndex = uploadedFilesQueue.findIndex(f => f.name === attachedPdf);
                if (fileIndex !== -1) {
                    selectFileFromQueue(fileIndex);
                    isPdfLinked = true;
                } else {
                    alert(`Không tìm thấy file PDF đính kèm "${attachedPdf}" trong danh sách tài liệu hiện tại.`);
                    isPdfLinked = false;
                }
            } else {
                isPdfLinked = false;
            }
            updatePdfLinkUI();
            
        } else {
            alert('Lỗi lấy dữ liệu: ' + res.message);
        }
    } catch (err) {
        alert('Lỗi kết nối máy chủ: ' + err);
    }
}

async function deleteSubmission(id) {
    if (!confirm('Bạn có chắc chắn muốn xóa hồ sơ này vĩnh viễn không?')) return;
    
    try {
        const response = await fetch(`/api/submissions/${id}`, { method: 'DELETE' });
        const res = await response.json();
        
        if (res.status === 'ok') {
            fetchSubmissions();
        } else {
            alert('Lỗi xóa: ' + res.message);
        }
    } catch (err) {
        alert('Lỗi kết nối máy chủ: ' + err);
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
        const response = await fetch('/api/export-append', {
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
