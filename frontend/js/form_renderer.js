function escapeHTML(str) {
    if (!str) return '';
    return String(str).replace(/[&<>"']/g, function(match) {
        const escape = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        };
        return escape[match];
    });
}

function getDraftStorageKey() {
    const userKey = currentUser && (currentUser.id || currentUser.username);
    const templateKey = window.activeTemplateId || 'none';
    return `formDraft_${userKey || 'anonymous'}_${templateKey}`;
}

function removeCurrentFormDraft() {
    localStorage.removeItem(getDraftStorageKey());
}

function applySyncRule(rule, sourceValue) {
    const targetInput = document.getElementById('col_' + (rule.target - 1));
    if (targetInput) targetInput.value = sourceValue;
}

function applyConcatRule(rule) {
    const source1 = document.getElementById('col_' + (rule.source_1 - 1));
    const source2 = document.getElementById('col_' + (rule.source_2 - 1));
    const target = document.getElementById('col_' + (rule.target - 1));
    if (!target) return;

    target.value = [source1, source2]
        .filter(source => source && source.value.trim())
        .map(source => source.value.trim())
        .join(', ');
}

function getConfiguredPlaceholder(config, colNumber, fallback = '') {
    const rules = Array.isArray(config && config.placeholder_rules)
        ? config.placeholder_rules
        : [];
    const rule = rules.find(item => Number(item.col) === Number(colNumber));
    if (!rule || typeof rule.text !== 'string') return fallback;
    return rule.text.trim() || fallback;
}

function getConfiguredRequiredCols(config = window.activeTemplateConfig || {}) {
    return new Set(
        (Array.isArray(config.required_cols) ? config.required_cols : [])
            .map(Number)
            .filter(col => Number.isInteger(col) && col > 0),
    );
}

function validateRequiredFields(showMessage = true) {
    const missing = [];
    getConfiguredRequiredCols().forEach(col => {
        const input = document.getElementById(`col_${col - 1}`);
        if (!input) return;
        const isMissing = !String(input.value || '').trim();
        input.classList.toggle('is-invalid', isMissing);
        if (isMissing) missing.push(input);
    });
    if (missing.length && showMessage) {
        missing[0].focus();
        alert(`Vui lòng nhập ${missing.length} trường bắt buộc trước khi lưu hồ sơ.`);
    }
    return missing.length === 0;
}

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
    
    const activeWorkspace = window.activeProjectWorkspace;
    const data = activeWorkspace
        && Number(activeWorkspace.project?.id) === Number(window.activeProjectId)
        ? {
            status: 'ok',
            data: Array.isArray(activeWorkspace.schema) ? activeWorkspace.schema : [],
            config: activeWorkspace.config || {},
        }
        : await apiCall(`/api/templates/${window.activeTemplateId}/schema`);
    if (loadingEl) loadingEl.style.display = 'none';
    
    if (data) {
        window.activeTemplateConfig = data.config || {};
        renderForm(data.data, data.config || {});
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

function getVisibleFormSchema(schema, config = {}) {
    const hiddenCols = new Set(
        (Array.isArray(config.hidden_cols) ? config.hidden_cols : [])
            .map(Number)
            .filter(col => Number.isInteger(col) && col > 0),
    );

    return (Array.isArray(schema) ? schema : [])
        .map(category => ({
            ...category,
            fields: (Array.isArray(category.fields) ? category.fields : [])
                .filter(field => !hiddenCols.has(Number(field.col_index) + 1)),
        }))
        .filter(category => category.fields.length > 0);
}

function resizeDynamicFormInput(input) {
    if (!input || !input.classList || !input.classList.contains('dynamic-height-input')) return;

    let minHeight = Number(input.dataset.dynamicMinHeight) || 0;
    if (!minHeight) {
        minHeight = Number(input.clientHeight) || 0;
        if (minHeight > 0) input.dataset.dynamicMinHeight = String(minHeight);
    }

    // Reset first so the field can shrink when text is removed, then fit wrapped content.
    input.style.height = 'auto';
    const contentHeight = Number(input.scrollHeight) || 0;
    const targetHeight = Math.max(minHeight, contentHeight > minHeight ? contentHeight + 2 : contentHeight);
    if (targetHeight > 0) input.style.height = `${Math.ceil(targetHeight)}px`;
}

function resizeDynamicFormInputs(root = document) {
    if (!root || typeof root.querySelectorAll !== 'function') return;
    root.querySelectorAll('.dynamic-height-input').forEach(resizeDynamicFormInput);
}

function renderForm(schema, config = {}) {
    const container = document.getElementById('form-container');
    if (!container) return; // Guard for pages without form-container
    container.innerHTML = '';
    
    // Load draft from localStorage
    let draftData = {};
    try {
        const stored = localStorage.getItem(getDraftStorageKey());
        if (stored) draftData = JSON.parse(stored);
    } catch (e) {}
    
    getVisibleFormSchema(schema, config).forEach((category, index) => {
        const section = _buildCategorySection(category, index, schema, config, draftData);
        container.appendChild(section);
        const categoryContent = section.querySelector('.category-content');
        if (categoryContent) resizeDynamicFormInputs(categoryContent);
    });
    
    // Attach listener for real-time draft saving
    const dataForm = document.getElementById('dataForm');
    if (dataForm) {
        dataForm.addEventListener('input', saveFormDraft);
    }
    
    // Auto-update Nguồn gốc chi tiết từ Mã (Linked Pairs)
    _applyLinkedPairs(schema, config);
    
    const loading = document.getElementById('loading');
    if (loading) loading.style.display = 'none';
    const appTabs = document.getElementById('appTabs');
    if (appTabs) appTabs.style.display = 'flex';
    if (dataForm) dataForm.style.display = 'block';
}

function _buildCategorySection(category, index, schema, config, draftData) {
    const section = document.createElement('div');
    section.className = 'form-section';
    
    // Category Title with Collapsible Icon
    const titleContainer = document.createElement('div');
    titleContainer.className = 'form-section-title d-flex justify-content-between align-items-center mb-0 pb-2 border-bottom border-2 border-primary mb-3';
    
    const titleLeft = document.createElement('div');
    titleLeft.className = 'd-flex align-items-center text-primary fw-bold fs-5';
    titleLeft.style.cursor = 'pointer';
    const safeCategory = escapeHTML(category.category);
    titleLeft.innerHTML = `<i class="fas fa-chevron-down me-2 transition-icon" style="width: 20px; transition: transform 0.2s;"></i>${safeCategory}`;
    
    const clearCategoryBtn = document.createElement('button');
    clearCategoryBtn.type = 'button';
    clearCategoryBtn.className = 'btn btn-sm btn-outline-danger clear-category-btn';
    clearCategoryBtn.innerHTML = `<i class="fas fa-eraser me-1"></i>Xóa sạch`;
    clearCategoryBtn.title = `Làm sạch dữ liệu mục ${safeCategory}`;
    
    const titleRight = document.createElement('div');
    titleRight.className = 'd-flex align-items-center';
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
        titleContainer.classList.remove('mb-3', 'border-bottom', 'border-2', 'border-primary', 'pb-2');
        section.style.paddingBottom = '5px';
    }
    
    titleLeft.addEventListener('click', () => {
        categoryContent.classList.toggle('d-none');
        const icon = titleLeft.querySelector('i');
        if (categoryContent.classList.contains('d-none')) {
            icon.classList.replace('fa-chevron-down', 'fa-chevron-right');
            titleContainer.classList.remove('mb-3', 'border-bottom', 'border-2', 'border-primary', 'pb-2');
            section.style.paddingBottom = '5px';
        } else {
            icon.classList.replace('fa-chevron-right', 'fa-chevron-down');
            titleContainer.classList.add('mb-3', 'border-bottom', 'border-2', 'border-primary', 'pb-2');
            section.style.paddingBottom = '';
            resizeDynamicFormInputs(categoryContent);
        }
    });
    
    clearCategoryBtn.addEventListener('click', () => {
        if (!confirm(`Bạn có chắc chắn muốn xóa sạch dữ liệu trong mục "${safeCategory}"?`)) return;
        const inputs = categoryContent.querySelectorAll('input, textarea');
        inputs.forEach(input => {
            if (input.type !== 'button' && input.type !== 'submit') {
                input.value = '';
                resizeDynamicFormInput(input);
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
            const safeSeparator = escapeHTML(field.separator_above);
            sepTitle.innerHTML = `<i class="fas fa-chevron-right me-2 text-secondary fs-6 transition-icon" style="width: 15px; transition: transform 0.2s;"></i>${safeSeparator}`;
            
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
        const col = _buildFieldGroup(field, config, draftData);
        targetRow.appendChild(col);
    });
    
    section.appendChild(categoryContent);
    return section;
}

function _buildFieldGroup(field, config, draftData) {
    const col = document.createElement('div');
    col.className = 'col-12';
    
    const formGroup = document.createElement('div');
    formGroup.className = 'position-relative';
    
    const labelRow = document.createElement('div');
    labelRow.className = 'd-flex justify-content-between align-items-center gap-2';

    const label = document.createElement('label');
    label.className = 'form-label fw-semibold';
    label.innerText = field.label;
    label.htmlFor = field.name;
    if (getConfiguredRequiredCols(config).has(field.col_index + 1)) {
        const requiredMark = document.createElement('span');
        requiredMark.className = 'text-danger ms-1';
        requiredMark.textContent = '*';
        requiredMark.title = 'Trường bắt buộc';
        label.appendChild(requiredMark);
    }
    labelRow.appendChild(label);

    const errorCheckWrapper = document.createElement('div');
    errorCheckWrapper.className = 'form-check review-field-error-check d-none flex-shrink-0';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'form-check-input field-error-checkbox';
    checkbox.id = `error_field_${field.col_index}`;
    checkbox.dataset.field = field.name;
    const checkboxLabel = document.createElement('label');
    checkboxLabel.className = 'form-check-label text-danger fw-semibold ms-1';
    checkboxLabel.htmlFor = checkbox.id;
    checkboxLabel.textContent = 'Lỗi sai';
    errorCheckWrapper.appendChild(checkbox);
    errorCheckWrapper.appendChild(checkboxLabel);
    labelRow.appendChild(errorCheckWrapper);
    formGroup.appendChild(labelRow);
    
    const input = document.createElement('textarea');
    input.className = 'form-control dynamic-height-input';
    input.name = field.name;
    input.id = field.name;
    input.rows = 1;
    input.setAttribute('autocomplete', 'off');
    input.style.width = '100%';
    input.style.resize = 'none';
    input.style.overflowY = 'hidden';
    input.style.transition = 'height 0.12s ease';
    if (getConfiguredRequiredCols(config).has(field.col_index + 1)) {
        input.dataset.required = 'true';
        input.setAttribute('aria-required', 'true');
        input.addEventListener('input', () => input.classList.remove('is-invalid'));
    }
    
    const resizeInput = () => resizeDynamicFormInput(input);
    input.addEventListener('input', resizeInput);
    input.addEventListener('change', resizeInput);
    input.addEventListener('focus', resizeInput);
    
    // Make auto-generated fields read-only based on config
    const roCols = config.readonly_cols || [];
    const linkedPathConfig = config.linked_pdf_path || {};
    const isLinkedPdfPath = linkedPathConfig.enabled === true
        && Number(linkedPathConfig.col) === field.col_index + 1;
        
    let inputContainer = formGroup;
    let linkButton = null;
    let updateLinkBtnState = null;

    if (isLinkedPdfPath) {
        inputContainer = document.createElement('div');
        inputContainer.className = 'input-group';
        formGroup.appendChild(inputContainer);
        
        linkButton = document.createElement('button');
        linkButton.className = 'btn btn-outline-primary';
        linkButton.type = 'button';
        linkButton.innerHTML = '<i class="fas fa-link me-1"></i>Lưu liên kết';
        linkButton.style.zIndex = '0'; // Prevent overlap with absolute elements if any
        
        input.readOnly = true;
        input.style.backgroundColor = '#e9ecef';
        
        updateLinkBtnState = () => {
            if (input.value.trim() !== '') {
                linkButton.className = 'btn btn-outline-danger';
                linkButton.innerHTML = '<i class="fas fa-unlink me-1"></i>Hủy liên kết';
            } else {
                linkButton.className = 'btn btn-outline-primary';
                linkButton.innerHTML = '<i class="fas fa-link me-1"></i>Lưu liên kết';
            }
        };

        linkButton.addEventListener('click', () => {
            if (input.value.trim() !== '') {
                input.value = '';
                updateLinkBtnState();
                if (typeof saveFormDraft === 'function') saveFormDraft();
                resizeDynamicFormInput(input);
                if (typeof window.isPdfLinked !== 'undefined') window.isPdfLinked = false;
            } else {
                if (typeof activeDocumentRelativePath !== 'undefined' && activeDocumentRelativePath) {
                    const levels = Number.isInteger(Number(linkedPathConfig.folder_levels)) ? Math.min(20, Math.max(0, Number(linkedPathConfig.folder_levels))) : 0;
                    input.value = typeof formatLinkedPdfPath === 'function' ? formatLinkedPdfPath(activeDocumentRelativePath, levels) : activeDocumentRelativePath;
                    updateLinkBtnState();
                    if (typeof saveFormDraft === 'function') saveFormDraft();
                    resizeDynamicFormInput(input);
                    if (typeof window.isPdfLinked !== 'undefined') window.isPdfLinked = true;
                } else {
                    alert('Vui lòng chọn một file PDF trước khi lưu liên kết.');
                }
            }
        });
        
        input.addEventListener('change', updateLinkBtnState);
        input.addEventListener('input', updateLinkBtnState);
    } else if (roCols.includes(field.col_index + 1)) {
        input.readOnly = true;
        input.style.backgroundColor = '#e9ecef';
    }
    
    _applyFieldRules(input, field, config);
    
    input.placeholder = getConfiguredPlaceholder(
        config,
        field.col_index + 1,
        input.placeholder,
    );

    if (draftData[field.name]) {
        input.value = draftData[field.name];
    }
    
    inputContainer.appendChild(input);
    if (linkButton) {
        inputContainer.appendChild(linkButton);
        updateLinkBtnState(); // Initialize state after draft data is applied
    }
    col.appendChild(formGroup);
    
    if (field.type === 'dropdown' && field.options) {
        autocomplete(input, field.options, field.extract_mode);
    }
    
    return col;
}

function _applyFieldRules(input, field, config) {
    // Sync columns logic
    const syncRules = config.sync_cols || [];
    syncRules.forEach(rule => {
        if (field.col_index + 1 === rule.source) {
            const applyRule = () => applySyncRule(rule, input.value);
            input.addEventListener('input', applyRule);
            input.addEventListener('change', applyRule);
        }
    });
    
    // Slice columns (CMND real-time cut)
    const sliceRules = config.slice_cols || [];
    sliceRules.forEach(rule => {
        if (field.col_index + 1 === rule.source) {
            input.addEventListener('input', function() {
                let val = this.value.replace(/\s+/g, '');
                const targetId = 'col_' + (rule.target - 1);
                const targetInput = document.getElementById(targetId);
                if (targetInput) {
                    if (val.length >= rule.length) {
                        targetInput.value = val.slice(-rule.length);
                    } else {
                        targetInput.value = '';
                    }
                }
            });
            
            input.addEventListener('blur', function() {
                this.value = this.value.replace(/\s+/g, '');
                if (typeof saveFormDraft === 'function') saveFormDraft();
            });
        }
    });
    
    // Concatenation Rules
    const concatRules = config.concat_rules || [];
    concatRules.forEach(rule => {
        if (field.col_index + 1 === rule.source_1 || field.col_index + 1 === rule.source_2) {
            const applyRule = () => applyConcatRule(rule);
            input.addEventListener('input', applyRule);
            input.addEventListener('change', applyRule);
        }
    });

    // Address Autofill Rules
    const addressRules = config.address_autofill_rules || [];
    addressRules.forEach(rule => {
        if (field.col_index + 1 === rule.trigger) {
            input.addEventListener('input', function() {
                let val = this.value.trim();
                if (!val) {
                    let maxa = document.getElementById('col_' + (rule.maxa - 1));
                    if (maxa) maxa.value = '';
                    return;
                }
                
                debounceProcessField(field.name, val, (data) => {
                    if (data && data.formatted) {
                        input.value = data.formatted;
                        
                        let maXa = document.getElementById('col_' + (rule.maxa - 1));
                        if (maXa) maXa.value = data.code;
                        
                        if (rule.concat_target) {
                            let cTarget = document.getElementById('col_' + (rule.concat_target - 1));
                            if (cTarget) {
                                let parts = [];
                                if (rule.concat_source_1) {
                                    let s1 = document.getElementById('col_' + (rule.concat_source_1 - 1));
                                    if (s1 && s1.value.trim()) parts.push(s1.value.trim());
                                }
                                parts.push(data.formatted);
                                cTarget.value = parts.join(', ');
                            }
                        }
                        
                        if (rule.don_vi_do) {
                            let f_dvd = document.getElementById('col_' + (rule.don_vi_do - 1));
                            if (f_dvd && data.don_vi_do) f_dvd.value = data.don_vi_do;
                        }
                        
                        if (rule.ngay_hoan_thanh) {
                            let f_nht = document.getElementById('col_' + (rule.ngay_hoan_thanh - 1));
                            if (f_nht && data.ngay_hoan_thanh) f_nht.value = data.ngay_hoan_thanh;
                        }
                        
                        if (typeof saveFormDraft === 'function') saveFormDraft();
                    }
                });
            });
        }
    });
    
    // Date fields
    const dateCols = config.date_cols || [];
    if (dateCols.includes(field.col_index + 1)) {
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
    
    // Year fields
    const yearCols = config.year_cols || [];
    if (yearCols.includes(field.col_index + 1)) {
        input.placeholder = 'yyyy';
        input.maxLength = 4;
        input.addEventListener('input', function() {
            this.value = this.value.replace(/\D/g, '');
            if (typeof saveFormDraft === 'function') saveFormDraft();
        });
    }
}

function _applyLinkedPairs(schema, config) {
    const linkedPairs = config.linked_pairs || [];
    linkedPairs.forEach(pair => {
        let colA = document.getElementById('col_' + (pair.source - 1));
        let colB = document.getElementById('col_' + (pair.target - 1));
        if (colA && colB) {
            colB.readOnly = true;
            colB.style.backgroundColor = "#e9ecef";
            colB.placeholder = "Tự động lấy theo dữ liệu nguồn";
            
            let colAField = null;
            schema.forEach(cat => {
                cat.fields.forEach(f => {
                    if (f.col_index + 1 === pair.source) colAField = f;
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
}


function saveFormDraft() {
    const dataForm = document.getElementById('dataForm');
    if (typeof resizeDynamicFormInputs === 'function') resizeDynamicFormInputs(dataForm);

    // Do not save draft if we are editing an existing record
    if (currentEditingId !== null) return;
    
    const inputs = document.querySelectorAll('#dataForm input[type="text"], #dataForm textarea');
    const data = {};
    inputs.forEach(input => {
        data[input.name] = input.value;
    });
    localStorage.setItem(getDraftStorageKey(), JSON.stringify(data));
}

function applyExtractMode(selectedVal, extractMode) {
    if (extractMode === "left") {
        if (selectedVal.includes(" - ")) return selectedVal.split(" - ")[0].trim();
    } else if (extractMode === "right") {
        if (selectedVal.includes(" - ")) return selectedVal.split(" - ").slice(1).join(" - ").trim();
    } else if (extractMode === "ABCD") {
        let match = selectedVal.match(/Loai\s+([A-Z])/i);
        if (match) return match[1].toUpperCase();
    }
    return selectedVal;
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
                let safeTextBefore = escapeHTML(arr[i].substr(0, matchIdx));
                let safeTextMatch = escapeHTML(arr[i].substr(matchIdx, val.length));
                let safeTextAfter = escapeHTML(arr[i].substr(matchIdx + val.length));
                b.innerHTML = safeTextBefore + "<strong>" + safeTextMatch + "</strong>" + safeTextAfter;
                b.innerHTML += "<input type='hidden' value='" + escapeHTML(arr[i]) + "'>";
                const selectHandler = function(e) {
                    e.preventDefault(); // Prevent default action
                    e.stopPropagation();
                    let hiddenInput = this.getElementsByTagName("input")[0];
                    if (!hiddenInput) return;
                    let selectedVal = hiddenInput.value;
                    
                    selectedVal = applyExtractMode(selectedVal, extractMode);
                    
                    inp.value = selectedVal;
                    closeAllLists();
                    inp.dispatchEvent(new Event('change'));
                    if (typeof saveFormDraft === 'function') saveFormDraft();
                };
                b.addEventListener("mousedown", selectHandler);
                b.addEventListener("touchstart", selectHandler);
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
                let event = new MouseEvent('click', {
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
                    let event = new MouseEvent('click', {
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
            b.innerHTML = escapeHTML(arr[i]);
            b.innerHTML += "<input type='hidden' value='" + escapeHTML(arr[i]) + "'>";
            const selectHandler = function(e) {
                e.preventDefault();
                e.stopPropagation();
                let hiddenInput = this.getElementsByTagName("input")[0];
                if (!hiddenInput) return;
                let selectedVal = hiddenInput.value;
                
                selectedVal = applyExtractMode(selectedVal, extractMode);
                
                inputEl.value = selectedVal;
                closeAllLists();
                inputEl.dispatchEvent(new Event('change'));
                if (typeof saveFormDraft === 'function') saveFormDraft();
            };
            b.addEventListener("mousedown", selectHandler);
            b.addEventListener("touchstart", selectHandler);
            a.appendChild(b);
        }
    }
    
    // Close when clicking outside
    document.addEventListener("click", function(e) {
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

