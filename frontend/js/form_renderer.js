let debounceTimer;
async function debounceProcessField(fieldName, value, callback) {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(async () => {
        if (!window.activeTemplateId) return;
        const res = await apiCall(`/api/templates/${window.activeTemplateId}/process-field`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ field_name: fieldName, value: value })
        }, "Lỗi xử lý tự động điền");
        if (res && res.data) {
            callback(res.data);
        }
    }, 500);
}

async function fetchSchema() {
    const loadingEl = document.getElementById('loading');
    const dataForm = document.getElementById('dataForm');
    
    if (!window.activeTemplateId) {
        if (loadingEl) {
            loadingEl.innerHTML = '<div class="alert alert-info text-center mt-4">Vui lòng chọn Biểu mẫu nhập liệu ở menu phía trên để bắt đầu.</div>';
            loadingEl.style.display = 'block';
        }
        if (dataForm) dataForm.style.display = 'none';
        return;
    }
    
    if (loadingEl) {
        loadingEl.innerHTML = 'Đang tải cấu trúc biểu mẫu, vui lòng đợi...';
        loadingEl.style.display = 'block';
    }
    if (dataForm) dataForm.style.display = 'none';
    
    const data = await apiCall(`/api/templates/${window.activeTemplateId}/schema`);
    if (loadingEl) loadingEl.style.display = 'none';
    
    if (data) {
        renderForm(data.data);
        if (dataForm) dataForm.style.display = 'block';
    }
}

async function onTemplateSelected() {
    const select = document.getElementById('templateSelect');
    if (select && select.value) {
        window.activeTemplateId = select.value;
        if (typeof cancelEdit === 'function') cancelEdit();
        await fetchSchema();
    } else {
        window.activeTemplateId = null;
        if (typeof cancelEdit === 'function') cancelEdit();
        await fetchSchema(); // will hide form
    }
}

function renderForm(schema) {
    const container = document.getElementById('form-container');
    if (!container) return; // Guard for pages without form-container
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
        clearCategoryBtn.className = 'btn btn-sm btn-outline-danger clear-category-btn';
        clearCategoryBtn.innerHTML = `<i class="fas fa-eraser me-1"></i>Xóa sạch`;
        clearCategoryBtn.title = `Làm sạch dữ liệu mục ${category.category}`;
        
        const titleRight = document.createElement('div');
        titleRight.className = 'd-flex align-items-center';

        const errorCheckWrapper = document.createElement('div');
        errorCheckWrapper.className = 'form-check me-3 admin-error-check d-none';
        errorCheckWrapper.innerHTML = `
            <input class="form-check-input error-checkbox" type="checkbox" id="error_cat_${index}" data-section="${category.category}" style="cursor: pointer; transform: scale(1.2);">
            <label class="form-check-label text-danger fw-bold ms-1" for="error_cat_${index}" style="cursor: pointer;">Lỗi Sai</label>
        `;
        
        titleRight.appendChild(errorCheckWrapper);
        titleRight.appendChild(clearCategoryBtn);
        
        titleContainer.appendChild(titleLeft);
        titleContainer.appendChild(titleRight);
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
            if (['col_2', 'col_19', 'col_36', 'col_21', 'col_38', 'col_93', 'col_105'].includes(field.name)) {
                input.readOnly = true;
                input.style.backgroundColor = '#e9ecef';
            }
            
            if (field.name === 'col_101') {
                input.addEventListener('input', function() {
                    const col105 = document.getElementById('col_105');
                    if (col105) {
                        col105.value = this.value;
                    }
                });
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
                    
                    debounceProcessField(field.name, val, (data) => {
                        if (data && data.formatted) {
                            input.value = data.formatted;
                            
                            if (field.name === 'col_20') {
                                let maXa = document.getElementById('col_19');
                                if (maXa) maXa.value = data.code;
                                
                                let f19 = document.getElementById('col_18');
                                let f22 = document.getElementById('col_21');
                                if (f22) {
                                    let parts = [];
                                    if (f19 && f19.value.trim()) parts.push(f19.value.trim());
                                    parts.push(data.formatted);
                                    f22.value = parts.join(', ');
                                }
                            }
                            
                            if (field.name === 'col_37') {
                                let maXa = document.getElementById('col_36');
                                if (maXa) maXa.value = data.code;
                                
                                let f36 = document.getElementById('col_35');
                                let f39 = document.getElementById('col_38');
                                if (f39) {
                                    let parts = [];
                                    if (f36 && f36.value.trim()) parts.push(f36.value.trim());
                                    parts.push(data.formatted);
                                    f39.value = parts.join(', ');
                                }
                            }
                            
                            if (field.name === 'col_92') {
                                let f92 = document.getElementById('col_91');
                                let f94 = document.getElementById('col_93');
                                if (f94) {
                                    let parts = [];
                                    if (f92 && f92.value.trim()) parts.push(f92.value.trim());
                                    parts.push(data.formatted);
                                    f94.value = parts.join(', ');
                                }
                                
                                let f47 = document.getElementById('col_46');
                                let f50 = document.getElementById('col_49');
                                if (f47 && data.don_vi_do) {
                                    f47.value = data.don_vi_do;
                                    if (f50 && data.ngay_hoan_thanh) f50.value = data.ngay_hoan_thanh;
                                }
                            }
                            
                            if (typeof saveFormDraft === 'function') saveFormDraft();
                        }
                    });
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
    const appTabs = document.getElementById('appTabs');
    if (appTabs) appTabs.style.display = 'flex';
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

