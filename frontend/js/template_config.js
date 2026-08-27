let currentConfigTemplateId = null;
let configModalInstance = null;
let currentConfigObj = {};
let templateFields = [];
let allDictionaries = [];

function initConfigModal() {
    if (!configModalInstance) {
        const modalEl = document.getElementById('configModal');
        if (modalEl) {
            configModalInstance = new bootstrap.Modal(modalEl);
        }
    }
}

function closeConfigModal(onClosed) {
    const modalEl = document.getElementById('configModal');
    let completed = false;
    const finishClosing = () => {
        if (completed) return;
        completed = true;

        if (modalEl) {
            modalEl.classList.remove('show');
            modalEl.style.display = 'none';
            modalEl.setAttribute('aria-hidden', 'true');
            modalEl.removeAttribute('aria-modal');
            modalEl.removeAttribute('role');
        }
        const hasOpenModal = typeof document.querySelector === 'function'
            && document.querySelector('.modal.show');
        if (!hasOpenModal && document.body) {
            document.body.classList.remove('modal-open');
            document.body.style.removeProperty('overflow');
            document.body.style.removeProperty('padding-right');
            if (typeof document.querySelectorAll === 'function') {
                document.querySelectorAll('.modal-backdrop').forEach(backdrop => backdrop.remove());
            }
        }
        currentConfigTemplateId = null;
        if (typeof onClosed === 'function') onClosed();
    };

    if (!modalEl) {
        finishClosing();
        return;
    }

    const modal = configModalInstance
        || (typeof bootstrap.Modal.getInstance === 'function'
            ? bootstrap.Modal.getInstance(modalEl)
            : null);
    if (!modal) {
        finishClosing();
        return;
    }

    modalEl.addEventListener('hidden.bs.modal', finishClosing, { once: true });
    modal.hide();
    // Fallback cleanup if a blocked transition prevents Bootstrap's hidden event.
    setTimeout(finishClosing, 500);
}

async function openConfigModal(templateId, templateName) {
    initConfigModal();
    const requestedTemplateId = Number(templateId);
    currentConfigTemplateId = requestedTemplateId;
    currentDictId = null;
    const dictionaryTemplateName = document.getElementById('dictionaryTemplateName');
    if (dictionaryTemplateName) dictionaryTemplateName.textContent = templateName;
    const dictionaryEditor = document.getElementById('dictionaryItemForm');
    if (dictionaryEditor) dictionaryEditor.style.display = 'none';
    const currentDictionaryName = document.getElementById('currentDictionaryName');
    if (currentDictionaryName) currentDictionaryName.textContent = 'Chưa chọn';
    const dictionaryItemsBody = document.getElementById('dictionaryItemsTableBody');
    if (dictionaryItemsBody) {
        dictionaryItemsBody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">Vui lòng chọn 1 Từ điển bên trái</td></tr>';
    }
    const dictionaryList = document.getElementById('dictionaryListGroup');
    if (dictionaryList) {
        dictionaryList.innerHTML = '<div class="text-center p-2 text-muted">Đang tải...</div>';
    }
    resetBulkDictionaryImport();
    
    document.getElementById('configModalTitle').innerText = templateName;
    document.getElementById('configJsonError').style.display = 'none';
    
    // Clear out UI
    resetVisualUi();
    
    configModalInstance.show();
    
    // Fetch schema, dictionaries, config in parallel (silent fetch - no alert on error)
    async function silentFetch(url) {
        try {
            const res = await authFetch(url);
            if (!res) return null;
            const data = await res.json();
            return data.status === 'ok' ? data : null;
        } catch(e) { return null; }
    }

    const [schemaRes, dictRes, configRes] = await Promise.all([
        silentFetch(`/api/templates/${requestedTemplateId}/schema`),
        silentFetch(`/api/templates/${requestedTemplateId}/dictionaries`),
        silentFetch(`/api/templates/${requestedTemplateId}/config`)
    ]);

    if (currentConfigTemplateId !== requestedTemplateId) return;
    
    if (!schemaRes) {
        alert('Không thể đọc cấu trúc file Excel của biểu mẫu này. Kiểm tra lại file.');
        configModalInstance.hide();
        return;
    }

    if (schemaRes && schemaRes.data) {
        templateFields = [];
        schemaRes.data.forEach(cat => {
            cat.fields.forEach(f => {
                templateFields.push({
                    col: f.col_index + 1,
                    label: `[Cột ${f.col_index + 1}] ${f.label}`
                });
            });
        });
        populateColDropdowns();
    }
    
    if (dictRes && dictRes.data) {
        allDictionaries = dictRes.data;
        populateDictDropdowns();
    }
    
    if (configRes && configRes.data) {
        currentConfigObj = configRes.data;
        document.getElementById('configJsonInput').value = JSON.stringify(currentConfigObj, null, 2);
    } else {
        currentConfigObj = {};
        document.getElementById('configJsonInput').value = "{}";
    }
    
    renderVisualUiFromJSON();
}

function populateColDropdowns() {
    // Render the unified table rows
    const unifiedBody = document.getElementById('unifiedColConfigBody');
    if (unifiedBody) {
        unifiedBody.innerHTML = templateFields.map(f => {
            const col = Number(f.col);
            return `
                <tr>
                    <td class="fw-bold text-nowrap">${escapeHTML(f.label)}</td>
                    <td class="text-center"><input class="form-check-input unified-chk-hidden generated-checkbox-emphasis" type="checkbox" value="${col}" id="chk_hidden_${col}"></td>
                    <td class="text-center"><input class="form-check-input unified-chk-ro generated-checkbox-emphasis" type="checkbox" value="${col}" id="chk_ro_${col}"></td>
                    <td class="text-center"><input class="form-check-input unified-chk-date generated-checkbox-emphasis" type="checkbox" value="${col}" id="chk_date_${col}"></td>
                    <td class="text-center"><input class="form-check-input unified-chk-year generated-checkbox-emphasis" type="checkbox" value="${col}" id="chk_year_${col}"></td>
                    <td class="text-center"><input class="form-check-input unified-chk-cover generated-checkbox-emphasis" type="checkbox" value="${col}" id="chk_cover_${col}"></td>
                    <td class="text-center"><input class="form-check-input unified-chk-required generated-checkbox-emphasis" type="checkbox" value="${col}" id="chk_required_${col}"></td>
                    <td><input type="text" class="form-control form-control-sm placeholder-rule-text" data-col="${col}" placeholder="Nhập gợi ý..." maxlength="255"></td>
                </tr>
            `;
        }).join('');
    }

    // Single selects / col-dropdowns in other tabs
    const optionsHtml = templateFields.map(f => `<option value="${Number(f.col)}">${escapeHTML(f.label)}</option>`).join('');
    const singles = document.querySelectorAll('.col-dropdown');
    singles.forEach(sel => {
        // Preserve the first placeholder option if it exists, else use generic
        const firstOpt = sel.querySelector('option[value=""]');
        const placeholder = firstOpt ? firstOpt.textContent : '-- Chọn --';
        sel.innerHTML = `<option value="">${escapeHTML(placeholder)}</option>` + optionsHtml;
    });
}

function populateDictDropdowns() {
    const optionsHtml = allDictionaries.map(d => {
        const description = d.description && d.description !== d.name
            ? ` (${escapeHTML(d.description)})`
            : '';
        return `<option value="${escapeHTML(d.name)}">${escapeHTML(d.name)}${description}</option>`;
    }).join('');
    const singles = document.querySelectorAll('.dict-dropdown');
    singles.forEach(sel => {
        const firstOpt = sel.querySelector('option[value=""]');
        const placeholder = firstOpt ? firstOpt.textContent : '-- Chọn Từ Điển --';
        sel.innerHTML = `<option value="">${escapeHTML(placeholder)}</option>` + optionsHtml;
    });
}

function resetVisualUi() {
    // Reset unified checkboxes and inputs
    document.querySelectorAll('.unified-chk-hidden, .unified-chk-ro, .unified-chk-date, .unified-chk-year, .unified-chk-cover, .unified-chk-required').forEach(cb => cb.checked = false);
    document.querySelectorAll('.placeholder-rule-text').forEach(input => input.value = '');
    
    document.getElementById('dictRulesBody').innerHTML = '<tr><td colspan="4" class="text-center text-muted">Chưa có luật nào</td></tr>';
    document.getElementById('syncRulesList').innerHTML = '';
    document.getElementById('concatRulesList').innerHTML = '';
}

function clearCheckboxes(panelId) {
    const el = document.getElementById(panelId);
    if (el) el.querySelectorAll('input[type=checkbox]').forEach(cb => cb.checked = false);
}

function getFieldName(colIdx) {
    const f = templateFields.find(x => x.col == colIdx);
    return f ? f.label : `[Cột ${colIdx}]`;
}

// ---------------- UI -> JSON ----------------
function buildConfigFromUI() {
    // Basic cols
    // Basic cols - read from unified table
    const getMultiValsByClass = (className) => {
        return Array.from(document.querySelectorAll(`.${className}:checked`)).map(cb => parseInt(cb.value, 10));
    };
    currentConfigObj.readonly_cols = getMultiValsByClass('unified-chk-ro');
    currentConfigObj.date_cols = getMultiValsByClass('unified-chk-date');
    document.querySelectorAll('.placeholder-rule-text').forEach(input => input.value = '');
    
    document.getElementById('dictRulesBody').innerHTML = '<tr><td colspan="4" class="text-center text-muted">Chưa có luật nào</td></tr>';
    document.getElementById('syncRulesList').innerHTML = '';
    document.getElementById('concatRulesList').innerHTML = '';
}

function clearCheckboxes(panelId) {
    const el = document.getElementById(panelId);
    if (el) el.querySelectorAll('input[type=checkbox]').forEach(cb => cb.checked = false);
}

function getFieldName(colIdx) {
    const f = templateFields.find(x => x.col == colIdx);
    return f ? f.label : `[Cột ${colIdx}]`;
}

// ---------------- UI -> JSON ----------------
function buildConfigFromUI() {
    // Basic cols
    // Basic cols - read from unified table
    const getMultiValsByClass = (className) => {
        return Array.from(document.querySelectorAll(`.${className}:checked`)).map(cb => parseInt(cb.value, 10));
    };
    currentConfigObj.readonly_cols = getMultiValsByClass('unified-chk-ro');
    currentConfigObj.date_cols = getMultiValsByClass('unified-chk-date');
    currentConfigObj.year_cols = getMultiValsByClass('unified-chk-year');
    currentConfigObj.hidden_cols = getMultiValsByClass('unified-chk-hidden');
    currentConfigObj.cover_cols = getMultiValsByClass('unified-chk-cover');
    currentConfigObj.required_cols = getMultiValsByClass('unified-chk-required');
    
    currentConfigObj.placeholder_rules = Array.from(document.querySelectorAll('.placeholder-rule-text'))
        .map(input => {
            const col = parseInt(input.getAttribute('data-col'), 10);
            return { col, text: input.value.trim() };
        })
        .filter(rule => Number.isInteger(rule.col) && rule.text.length > 0);
    
    const coverFolderLevels = parseInt(document.getElementById('coverFolderLevels')?.value || '0', 10);
    currentConfigObj.cover_folder_level = Number.isInteger(coverFolderLevels) ? Math.min(20, Math.max(0, coverFolderLevels)) : 0;

    const linkedPathCol = parseInt(document.getElementById('linkedPdfPathCol')?.value || '', 10);
    const folderLevels = parseInt(document.getElementById('linkedPdfPathFolderLevels')?.value || '0', 10);
    currentConfigObj.linked_pdf_path = {
        enabled: !!document.getElementById('linkedPdfPathEnabled')?.checked,
        col: Number.isInteger(linkedPathCol) ? linkedPathCol : null,
        folder_levels: Number.isInteger(folderLevels) ? Math.min(20, Math.max(0, folderLevels)) : 0,
    };
    
    // (Dict, Sync, Concat are already updated in real-time within currentConfigObj arrays when added/deleted)
    
    document.getElementById('configJsonInput').value = JSON.stringify(currentConfigObj, null, 2);
}

// ---------------- JSON -> UI ----------------
function renderVisualUiFromJSON() {
    const obj = currentConfigObj;
    
    // Basic
    // Basic - set unified table from saved values
    const setMultiValsByClass = (className, arr) => {
        const selectedValues = new Set((Array.isArray(arr) ? arr : []).map(Number).filter(Number.isInteger));
        document.querySelectorAll(`.${className}`).forEach(cb => {
            cb.checked = selectedValues.has(parseInt(cb.value, 10));
        });
    };
    
    setMultiValsByClass('unified-chk-ro', obj.readonly_cols);
    setMultiValsByClass('unified-chk-date', obj.date_cols);
    setMultiValsByClass('unified-chk-year', obj.year_cols);
    setMultiValsByClass('unified-chk-hidden', obj.hidden_cols);
    setMultiValsByClass('unified-chk-cover', obj.cover_cols);
    setMultiValsByClass('unified-chk-required', obj.required_cols);

    const coverLevels = document.getElementById('coverFolderLevels');
    if (coverLevels) {
        coverLevels.value = Number.isInteger(obj.cover_folder_level) ? String(Math.min(20, Math.max(0, obj.cover_folder_level))) : '0';
    }

    const rules = Array.isArray(obj.placeholder_rules) ? obj.placeholder_rules : [];
    document.querySelectorAll('.placeholder-rule-text').forEach(input => input.value = '');
    rules.forEach(rule => {
        const col = Number(rule.col);
        const input = document.querySelector(`.placeholder-rule-text[data-col="${col}"]`);
        if (input && typeof rule.text === 'string' && rule.text.trim()) {
            input.value = rule.text.trim();
        }
    });

    const linkedPath = obj.linked_pdf_path || {};
    const linkedPathEnabled = document.getElementById('linkedPdfPathEnabled');
    const linkedPathCol = document.getElementById('linkedPdfPathCol');
    const linkedPathLevels = document.getElementById('linkedPdfPathFolderLevels');
    if (linkedPathEnabled) linkedPathEnabled.checked = linkedPath.enabled === true;
    if (linkedPathCol) linkedPathCol.value = linkedPath.col || '';
    if (linkedPathLevels) linkedPathLevels.value = Number.isInteger(linkedPath.folder_levels)
        ? String(Math.min(20, Math.max(0, linkedPath.folder_levels)))
        : '0';

    // Dicts
    const dictBody = document.getElementById('dictRulesBody');
    dictBody.innerHTML = '';
    if (obj.dropdown_rules && obj.dropdown_rules.length > 0) {
        obj.dropdown_rules.forEach((r, idx) => {
            dictBody.innerHTML += `
                <tr>
                    <td>${escapeHTML(getFieldName(r.col))}</td>
                    <td><span class="badge bg-success">${escapeHTML(r.dictionary)}</span></td>
                    <td>${r.extract_mode === 'left' ? 'Bên trái' : r.extract_mode === 'right' ? 'Bên phải' : 'Cả hai'}</td>
                    <td><button class="btn btn-sm btn-danger py-0" data-template-action="remove-rule" data-rule-type="dropdown_rules" data-rule-index="${idx}"><i class="fas fa-times"></i></button></td>
                </tr>
            `;
        });
    } else {
        dictBody.innerHTML = '<tr><td colspan="4" class="text-center text-muted">Chưa có luật nào</td></tr>';
    }
    
    // Syncs
    const syncBody = document.getElementById('syncRulesList');
    syncBody.innerHTML = '';
    if (obj.sync_cols && obj.sync_cols.length > 0) {
        obj.sync_cols.forEach((r, idx) => {
            syncBody.innerHTML += `
                <li class="list-group-item d-flex justify-content-between align-items-center py-1">
                    <span>${escapeHTML(getFieldName(r.source))} <i class="fas fa-arrow-right text-muted mx-2"></i> ${escapeHTML(getFieldName(r.target))}</span>
                    <button class="btn btn-sm btn-outline-danger py-0 px-2" data-template-action="remove-rule" data-rule-type="sync_cols" data-rule-index="${idx}"><i class="fas fa-times"></i></button>
                </li>
            `;
        });
    }
    
    // Concat
    const concatBody = document.getElementById('concatRulesList');
    concatBody.innerHTML = '';
    if (obj.concat_rules && obj.concat_rules.length > 0) {
        obj.concat_rules.forEach((r, idx) => {
            concatBody.innerHTML += `
                <li class="list-group-item d-flex justify-content-between align-items-center py-1">
                    <span>${escapeHTML(getFieldName(r.source_1))} <b class="text-warning">+</b> ${escapeHTML(getFieldName(r.source_2))} <i class="fas fa-arrow-right text-muted mx-2"></i> <b>${escapeHTML(getFieldName(r.target))}</b></span>
                    <button class="btn btn-sm btn-outline-danger py-0 px-2" data-template-action="remove-rule" data-rule-type="concat_rules" data-rule-index="${idx}"><i class="fas fa-times"></i></button>
                </li>
            `;
        });
    }
}

// ---------------- ADD/REMOVE RULES ----------------
function removeRule(ruleType, idx) {
    if (currentConfigObj[ruleType] && currentConfigObj[ruleType].length > idx) {
        currentConfigObj[ruleType].splice(idx, 1);
        renderVisualUiFromJSON();
        buildConfigFromUI();
    }
}

function addRuleDict() {
    const col = document.getElementById('dictNewCol').value;
    const dict = document.getElementById('dictNewDict').value;
    const mode = document.getElementById('dictNewMode').value;
    
    if (!col || !dict) return alert("Vui lòng chọn Cột và Từ điển");
    
    if (!currentConfigObj.dropdown_rules) currentConfigObj.dropdown_rules = [];
    currentConfigObj.dropdown_rules.push({
        col: parseInt(col),
        dictionary: dict,
        extract_mode: mode
    });
    
    renderVisualUiFromJSON();
    buildConfigFromUI();
}

function addRuleSync() {
    const s = document.getElementById('syncSourceCol').value;
    const t = document.getElementById('syncTargetCol').value;
    if (!s || !t) return alert("Vui lòng chọn đầy đủ cột nguồn và đích");
    
    if (!currentConfigObj.sync_cols) currentConfigObj.sync_cols = [];
    currentConfigObj.sync_cols.push({
        source: parseInt(s),
        target: parseInt(t)
    });
    
    renderVisualUiFromJSON();
    buildConfigFromUI();
}

function addRuleConcat() {
    const s1 = document.getElementById('concatSource1').value;
    const s2 = document.getElementById('concatSource2').value;
    const t = document.getElementById('concatTarget').value;
    if (!s1 || !s2 || !t) return alert("Vui lòng chọn đầy đủ 2 nguồn và 1 đích");
    
    if (!currentConfigObj.concat_rules) currentConfigObj.concat_rules = [];
    currentConfigObj.concat_rules.push({
        source_1: parseInt(s1),
        source_2: parseInt(s2),
        target: parseInt(t)
    });
    
    renderVisualUiFromJSON();
    buildConfigFromUI();
}

// ---------------- SAVE API ----------------

function formatConfigJson() {
    const el = document.getElementById('configJsonInput');
    const errEl = document.getElementById('configJsonError');
    errEl.style.display = 'none';
    
    try {
        const obj = JSON.parse(el.value);
        el.value = JSON.stringify(obj, null, 2);
        currentConfigObj = obj;
        renderVisualUiFromJSON(); // sync UI back from JSON
        alert("Đã áp dụng mã JSON sang giao diện trực quan!");
    } catch (e) {
        errEl.innerText = "Lỗi cú pháp JSON: " + e.message;
        errEl.style.display = 'block';
    }
}

function generateDefaultConfig() {
    currentConfigObj = {
        "readonly_cols": [2, 19, 36, 21, 38, 93, 105],
        "date_cols": [10, 27],
        "year_cols": [11, 28],
        "sync_cols": [
            { "source": 101, "target": 105 }
        ],
        "slice_cols": [
            { "source": 3, "target": 2, "length": 6 }
        ],
        "concat_rules": [
            { "source_1": 18, "source_2": 20, "target": 21 },
            { "source_1": 35, "source_2": 37, "target": 38 },
            { "source_1": 91, "source_2": 92, "target": 93 }
        ],
        "address_autofill_rules": [
            { "trigger": 20, "maxa": 19, "concat_target": 21, "concat_source_1": 18 },
            { "trigger": 37, "maxa": 36, "concat_target": 38, "concat_source_1": 35 },
            { "trigger": 92, "maxa": 91, "concat_target": 93, "concat_source_1": 91, "don_vi_do": 46, "ngay_hoan_thanh": 49 }
        ],
        "linked_pairs": [
            { "source": 59, "target": 60 },
            { "source": 67, "target": 68 },
            { "source": 75, "target": 76 },
            { "source": 83, "target": 84 }
        ],
        "dropdown_rules": [
            {"col": 60, "dictionary": "DM_NguonGocSuDungDat", "extract_mode": "left"},
            {"col": 68, "dictionary": "DM_NguonGocSuDungDat", "extract_mode": "left"},
            {"col": 76, "dictionary": "DM_NguonGocSuDungDat", "extract_mode": "left"},
            {"col": 84, "dictionary": "DM_NguonGocSuDungDat", "extract_mode": "left"},
            {"col": 97, "dictionary": "DM_Hardcoded_SuDungChung", "extract_mode": "left"},
            {"col": 104, "dictionary": "DM_Hardcoded_UyQuyen", "extract_mode": "left"},
            {"col": 105, "dictionary": "DM_Hardcoded_KyThay", "extract_mode": "left"}
        ],
        "separators": {
            "17": { "title": "Địa chỉ sử dụng", "group_end": 22 },
            "34": { "title": "Địa chỉ vợ (chồng)", "group_end": 39 },
            "86": { "title": "Diện tích hành lang", "group_end": 89 },
            "90": { "title": "Địa chỉ thửa đất", "group_end": 94 },
            "111": { "title": "Hạn chế quyền", "group_end": 117 },
            "118": { "title": "Nghĩa vụ tài chính", "group_end": 123 },
            "124": { "title": "Miễn giảm nghĩa vụ tài chính", "group_end": 128 },
            "129": { "title": "Nợ nghĩa vụ tài chính", "group_end": 133 },
            "134": { "title": "Nhà ở riêng lẻ", "group_end": 141 },
            "142": { "title": "Công trình, hạng mục công trình xây dựng", "group_end": 154 },
            "155": { "title": "Công trình ngầm", "group_end": 162 },
            "163": { "title": "Rừng trồng", "group_end": 165 },
            "166": { "title": "Cây lâu năm", "group_end": 168 },
            "179": { "title": "Thông tin lưu kho vật lý hồ sơ", "group_end": 182 }
        }
    };
    
    document.getElementById('configJsonInput').value = JSON.stringify(currentConfigObj, null, 2);
    document.getElementById('configJsonError').style.display = 'none';
    renderVisualUiFromJSON();
}

async function saveTemplateConfig() {
    // Luôn build config từ UI trước khi lưu để đảm bảo đồng bộ
    buildConfigFromUI();
    
    const el = document.getElementById('configJsonInput');
    const errEl = document.getElementById('configJsonError');
    errEl.style.display = 'none';
    
    let obj;
    try {
        obj = JSON.parse(el.value);
    } catch (e) {
        errEl.innerText = "Lỗi cú pháp JSON: Không thể lưu. Vui lòng sửa lỗi trước khi lưu.";
        errEl.style.display = 'block';
        return;
    }
    
    const res = await apiCall(`/api/templates/${currentConfigTemplateId}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(obj)
    });
    
    if (res) {
        closeConfigModal(() => alert('Đã lưu cấu hình biểu mẫu thành công!'));
    }
}

// ==========================================
// THÊM: QUẢN LÝ TỪ ĐIỂN RIÊNG CỦA BIỂU MẪU
// ==========================================
let currentDictId = null;

async function fetchTemplateDictionaries() {
    if (!currentConfigTemplateId) return;
    const res = await apiCall(`/api/templates/${currentConfigTemplateId}/dictionaries`);
    if (res && res.status === 'ok') {
        allDictionaries = res.data;
        const listGroup = document.getElementById('dictionaryListGroup');
        if (listGroup) {
            listGroup.innerHTML = '';
            if (res.data.length === 0) {
                listGroup.innerHTML = '<div class="text-center p-3 text-muted">Chưa có từ điển nào</div>';
            } else {
                res.data.forEach(d => {
                    const safeId = Number(d.id);
                    const row = document.createElement('div');
                    row.className = `list-group-item list-group-item-action d-flex justify-content-between align-items-center ${currentDictId === safeId ? 'active' : ''}`;
                    row.setAttribute('role', 'button');
                    const label = document.createElement('strong');
                    label.textContent = d.name;
                    const deleteButton = document.createElement('button');
                    deleteButton.type = 'button';
                    deleteButton.className = 'btn btn-sm btn-outline-danger';
                    deleteButton.setAttribute('aria-label', 'Xóa từ điển');
                    deleteButton.innerHTML = '<i class="fas fa-trash"></i>';
                    deleteButton.onclick = event => deleteDictionary(safeId, event);
                    row.onclick = () => selectDictionary(safeId, d.name);
                    row.appendChild(label);
                    row.appendChild(deleteButton);
                    listGroup.appendChild(row);
                });
            }
        }
        populateDictDropdowns();
    }
}

function selectDictionary(id, name) {
    currentDictId = Number(id);
    const nameEl = document.getElementById('currentDictionaryName');
    const formEl = document.getElementById('dictionaryItemForm');
    if (nameEl) nameEl.innerText = name;
    if (formEl) formEl.style.display = 'block';
    resetBulkDictionaryImport();
    fetchTemplateDictionaries(); // Re-render to show active
    fetchDictionaryItems();
}

async function createDictionary() {
    const name = document.getElementById('newDictionaryName').value.trim();
    if (!name) return alert("Vui lòng nhập tên từ điển");
    
    const data = await apiCall(`/api/templates/${currentConfigTemplateId}/dictionaries`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, description: name })
    });
    
    if (data) {
        document.getElementById('newDictionaryName').value = '';
        fetchTemplateDictionaries();
    }
}

async function deleteDictionary(id, e) {
    if (e) e.stopPropagation();
    if (!confirm('Bạn có chắc chắn muốn xóa từ điển này? Toàn bộ giá trị bên trong sẽ bị xóa.')) return;
    
    const data = await apiCall(`/api/dictionaries/${id}`, { method: 'DELETE' });
    if (data) {
        if (currentDictId === id) {
            currentDictId = null;
            document.getElementById('currentDictionaryName').innerText = 'Chưa chọn';
            document.getElementById('dictionaryItemForm').style.display = 'none';
            document.getElementById('dictionaryItemsTableBody').innerHTML = '<tr><td colspan="3" class="text-center text-muted">Vui lòng chọn 1 Từ điển bên trái</td></tr>';
        }
        fetchTemplateDictionaries();
    }
}

async function fetchDictionaryItems() {
    if (!currentDictId) return;
    const requestedDictionaryId = currentDictId;
    const pageSize = 100;
    const data = await apiCall(
        `/api/dictionaries/${requestedDictionaryId}/items?page=1&page_size=${pageSize}`
    );
    if (data) {
        const items = Array.isArray(data.data) ? [...data.data] : [];
        const totalPages = Math.max(1, Number(data.pagination?.total_pages) || 1);
        for (let page = 2; page <= totalPages; page += 1) {
            const nextPage = await apiCall(
                `/api/dictionaries/${requestedDictionaryId}/items?page=${page}&page_size=${pageSize}`
            );
            if (!nextPage) return;
            items.push(...(Array.isArray(nextPage.data) ? nextPage.data : []));
        }
        if (currentDictId !== requestedDictionaryId) return;

        const tbody = document.getElementById('dictionaryItemsTableBody');
        if (!tbody) return;
        tbody.innerHTML = '';
        if (items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">Chưa có giá trị nào</td></tr>';
            return;
        }
        items.forEach(item => {
            const safeId = Number(item.id);
            tbody.innerHTML += `
                <tr>
                    <td>${escapeHTML(item.code || '')}</td>
                    <td>${escapeHTML(item.value)}</td>
                    <td>
                        <button class="btn btn-sm btn-outline-danger" data-template-action="delete-dictionary-item" data-item-id="${safeId}"><i class="fas fa-trash"></i></button>
                    </td>
                </tr>
            `;
        });
    }
}

async function createDictionaryItem() {
    if (!currentDictId) return;
    const code = document.getElementById('newDictItemCode').value.trim();
    const val = document.getElementById('newDictItemValue').value.trim();
    if (!val) return alert("Giá trị là bắt buộc");
    
    const data = await apiCall(`/api/dictionaries/${currentDictId}/items`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: code, value: val })
    });
    
    if (data) {
        document.getElementById('newDictItemCode').value = '';
        document.getElementById('newDictItemValue').value = '';
        fetchDictionaryItems();
    }
}

function parseBulkDictionaryText(text) {
    const lines = String(text || '').split(/\r?\n/);
    const items = [];
    const errors = [];
    const seenCodes = new Map();

    if (lines.length > 5000) {
        return { items, errors: ['Mỗi lần chỉ được nhập tối đa 5.000 dòng.'] };
    }

    lines.forEach((rawLine, index) => {
        const lineNumber = index + 1;
        const line = rawLine.trim();
        if (!line) return;

        let code = '';
        let value = '';
        const match = line.match(/^(.*?)\s+-\s+(.+?)$/);
        if (match) {
            code = match[1].trim();
            value = match[2].trim();
        } else if (line.includes('\t')) {
            const tabIndex = line.indexOf('\t');
            code = line.slice(0, tabIndex).trim();
            value = line.slice(tabIndex + 1).trim();
        } else {
            errors.push(`Dòng ${lineNumber}: cần định dạng "id - value".`);
            return;
        }

        if (!code) {
            errors.push(`Dòng ${lineNumber}: id không được để trống.`);
            return;
        }
        if (!value) {
            errors.push(`Dòng ${lineNumber}: value không được để trống.`);
            return;
        }
        if (code.length > 50) {
            errors.push(`Dòng ${lineNumber}: id vượt quá 50 ký tự.`);
            return;
        }
        if (value.length > 255) {
            errors.push(`Dòng ${lineNumber}: value vượt quá 255 ký tự.`);
            return;
        }

        const normalizedCode = code.toLocaleLowerCase('vi');
        if (seenCodes.has(normalizedCode)) {
            errors.push(`Dòng ${lineNumber}: id "${code}" trùng với dòng ${seenCodes.get(normalizedCode)}.`);
            return;
        }
        seenCodes.set(normalizedCode, lineNumber);
        items.push({ code, value, lineNumber });
    });

    if (items.length === 0 && errors.length === 0) {
        errors.push('Không có dữ liệu để nhập.');
    }
    return { items, errors };
}

function renderBulkDictionaryPreview(parsed) {
    const tbody = document.getElementById('bulkDictionaryPreviewBody');
    const status = document.getElementById('bulkDictionaryStatus');
    const importButton = document.getElementById('bulkDictionaryImportButton');
    if (!tbody || !status || !importButton) return;

    tbody.replaceChildren();
    parsed.items.slice(0, 200).forEach(item => {
        const row = document.createElement('tr');
        const lineCell = document.createElement('td');
        const codeCell = document.createElement('td');
        const valueCell = document.createElement('td');
        lineCell.textContent = item.lineNumber;
        codeCell.textContent = item.code;
        valueCell.textContent = item.value;
        row.appendChild(lineCell);
        row.appendChild(codeCell);
        row.appendChild(valueCell);
        tbody.appendChild(row);
    });

    if (parsed.errors.length > 0) {
        status.className = 'small text-danger mt-2';
        status.textContent = parsed.errors.slice(0, 10).join(' ');
        if (parsed.errors.length > 10) {
            status.textContent += ` Và ${parsed.errors.length - 10} lỗi khác.`;
        }
        importButton.disabled = true;
        return;
    }

    status.className = 'small text-success mt-2';
    status.textContent = `Hợp lệ ${parsed.items.length} dòng`;
    if (parsed.items.length > 200) {
        status.textContent += ' (bảng xem trước hiển thị 200 dòng đầu).';
    }
    importButton.disabled = parsed.items.length === 0;
}

function previewBulkDictionaryItems() {
    const textarea = document.getElementById('bulkDictionaryText');
    const parsed = parseBulkDictionaryText(textarea ? textarea.value : '');
    renderBulkDictionaryPreview(parsed);
    return parsed;
}

function resetBulkDictionaryImport() {
    const textarea = document.getElementById('bulkDictionaryText');
    const status = document.getElementById('bulkDictionaryStatus');
    const tbody = document.getElementById('bulkDictionaryPreviewBody');
    const importButton = document.getElementById('bulkDictionaryImportButton');
    if (textarea) textarea.value = '';
    if (status) {
        status.className = 'small text-muted mt-2';
        status.textContent = 'Dán dữ liệu rồi nhấn Xem trước.';
    }
    if (tbody) tbody.replaceChildren();
    if (importButton) importButton.disabled = true;
}

async function importBulkDictionaryItems() {
    if (!currentConfigTemplateId || !currentDictId) return;
    const textarea = document.getElementById('bulkDictionaryText');
    const duplicateMode = document.getElementById('bulkDictionaryDuplicateMode');
    const status = document.getElementById('bulkDictionaryStatus');
    const parsed = previewBulkDictionaryItems();
    if (parsed.errors.length > 0 || parsed.items.length === 0) return;

    const data = await apiCall(
        `/api/templates/${currentConfigTemplateId}/dictionaries/${currentDictId}/items/bulk`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                text: textarea.value,
                duplicate_mode: duplicateMode ? duplicateMode.value : 'skip',
            }),
        },
        'Lỗi nhập hàng loạt từ điển'
    );
    if (!data) return;

    const result = data.data;
    if (status) {
        status.className = 'small text-success mt-2';
        status.textContent = `Đã thêm ${result.added}, cập nhật ${result.updated}, bỏ qua ${result.skipped}.`;
    }
    if (textarea) textarea.value = '';
    const previewBody = document.getElementById('bulkDictionaryPreviewBody');
    if (previewBody) previewBody.replaceChildren();
    const importButton = document.getElementById('bulkDictionaryImportButton');
    if (importButton) importButton.disabled = true;
    fetchDictionaryItems();
}

async function deleteDictionaryItem(id) {
    if (!confirm("Xóa giá trị này?")) return;
    const data = await apiCall(`/api/dictionaries/items/${id}`, { method: 'DELETE' });
    if (data) {
        fetchDictionaryItems();
    }
}

if (typeof document.addEventListener === 'function') {
    document.addEventListener('click', event => {
        const trigger = event.target?.closest?.('[data-template-action]');
        if (!trigger) return;
        if (trigger.dataset.templateAction === 'remove-rule') {
            removeRule(trigger.dataset.ruleType, Number(trigger.dataset.ruleIndex));
        } else if (trigger.dataset.templateAction === 'delete-dictionary-item') {
            deleteDictionaryItem(Number(trigger.dataset.itemId));
        }
    });
}
