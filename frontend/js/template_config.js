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

async function openConfigModal(templateId, templateName) {
    initConfigModal();
    currentConfigTemplateId = templateId;
    
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
        silentFetch(`/api/templates/${templateId}/schema`),
        silentFetch(`/api/templates/${templateId}/dictionaries`),
        silentFetch(`/api/templates/${templateId}/config`)
    ]);
    
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
    // Render checkboxes for the 3 special-col panels
    const checkboxPanels = ['roColSelect', 'dateColSelect', 'yearColSelect'];
    checkboxPanels.forEach(panelId => {
        const container = document.getElementById(panelId);
        if (!container) return;
        container.innerHTML = templateFields.map(f => `
            <div class="form-check">
                <input class="form-check-input" type="checkbox" value="${f.col}" id="chk_${panelId}_${f.col}">
                <label class="form-check-label small" for="chk_${panelId}_${f.col}">${f.label}</label>
            </div>
        `).join('');
    });

    // Single selects / col-dropdowns in other tabs
    const optionsHtml = templateFields.map(f => `<option value="${f.col}">${f.label}</option>`).join('');
    const singles = document.querySelectorAll('.col-dropdown');
    singles.forEach(sel => {
        // Preserve the first placeholder option if it exists, else use generic
        const firstOpt = sel.querySelector('option[value=""]');
        const placeholder = firstOpt ? firstOpt.textContent : '-- Chọn --';
        sel.innerHTML = `<option value="">${placeholder}</option>` + optionsHtml;
    });
}

function populateDictDropdowns() {
    const optionsHtml = allDictionaries.map(d => `<option value="${d.name}">${d.name}${d.description && d.description !== d.name ? ' (' + d.description + ')' : ''}</option>`).join('');
    const singles = document.querySelectorAll('.dict-dropdown');
    singles.forEach(sel => {
        const firstOpt = sel.querySelector('option[value=""]');
        const placeholder = firstOpt ? firstOpt.textContent : '-- Chọn Từ Điển --';
        sel.innerHTML = `<option value="">${placeholder}</option>` + optionsHtml;
    });
}

function resetVisualUi() {
    // Reset checkboxes
    ['roColSelect', 'dateColSelect', 'yearColSelect'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.querySelectorAll('input[type=checkbox]').forEach(cb => cb.checked = false);
    });
    
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
    // Basic cols - read from checkboxes
    const getMultiVals = (id) => {
        const el = document.getElementById(id);
        if (!el) return [];
        return Array.from(el.querySelectorAll('input[type=checkbox]:checked')).map(cb => parseInt(cb.value));
    };
    currentConfigObj.readonly_cols = getMultiVals('roColSelect');
    currentConfigObj.date_cols = getMultiVals('dateColSelect');
    currentConfigObj.year_cols = getMultiVals('yearColSelect');
    
    // (Dict, Sync, Concat are already updated in real-time within currentConfigObj arrays when added/deleted)
    
    document.getElementById('configJsonInput').value = JSON.stringify(currentConfigObj, null, 2);
}

// ---------------- JSON -> UI ----------------
function renderVisualUiFromJSON() {
    const obj = currentConfigObj;
    
    // Basic
    // Basic - set checkboxes from saved values
    const setMultiVals = (id, arr) => {
        if (!arr) return;
        const el = document.getElementById(id);
        if (!el) return;
        el.querySelectorAll('input[type=checkbox]').forEach(cb => {
            if (arr.includes(parseInt(cb.value))) cb.checked = true;
        });
    };
    
    setMultiVals('roColSelect', obj.readonly_cols);
    setMultiVals('dateColSelect', obj.date_cols);
    setMultiVals('yearColSelect', obj.year_cols);
    
    // Dicts
    const dictBody = document.getElementById('dictRulesBody');
    dictBody.innerHTML = '';
    if (obj.dropdown_rules && obj.dropdown_rules.length > 0) {
        obj.dropdown_rules.forEach((r, idx) => {
            dictBody.innerHTML += `
                <tr>
                    <td>${getFieldName(r.col)}</td>
                    <td><span class="badge bg-success">${r.dictionary}</span></td>
                    <td>${r.extract_mode === 'left' ? 'Bên trái' : r.extract_mode === 'right' ? 'Bên phải' : 'Cả hai'}</td>
                    <td><button class="btn btn-sm btn-danger py-0" onclick="removeRule('dropdown_rules', ${idx})"><i class="fas fa-times"></i></button></td>
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
                    <span>${getFieldName(r.source)} <i class="fas fa-arrow-right text-muted mx-2"></i> ${getFieldName(r.target)}</span>
                    <button class="btn btn-sm btn-outline-danger py-0 px-2" onclick="removeRule('sync_cols', ${idx})"><i class="fas fa-times"></i></button>
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
                    <span>${getFieldName(r.source_1)} <b class="text-warning">+</b> ${getFieldName(r.source_2)} <i class="fas fa-arrow-right text-muted mx-2"></i> <b>${getFieldName(r.target)}</b></span>
                    <button class="btn btn-sm btn-outline-danger py-0 px-2" onclick="removeRule('concat_rules', ${idx})"><i class="fas fa-times"></i></button>
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
        alert('Đã lưu cấu hình biểu mẫu thành công!');
        configModalInstance.hide();
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
                    const btn = document.createElement('button');
                    btn.className = `list-group-item list-group-item-action d-flex justify-content-between align-items-center ${currentDictId === d.id ? 'active' : ''}`;
                    btn.innerHTML = `
                        <span><strong>${d.name}</strong></span>
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteDictionary(${d.id}, event)"><i class="fas fa-trash"></i></button>
                    `;
                    btn.onclick = () => selectDictionary(d.id, d.name);
                    listGroup.appendChild(btn);
                });
            }
        }
        populateDictDropdowns();
    }
}

function selectDictionary(id, name) {
    currentDictId = id;
    const nameEl = document.getElementById('currentDictionaryName');
    const formEl = document.getElementById('dictionaryItemForm');
    if (nameEl) nameEl.innerText = name;
    if (formEl) formEl.style.display = 'flex';
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
    const data = await apiCall(`/api/dictionaries/${currentDictId}/items`);
    if (data) {
        const tbody = document.getElementById('dictionaryItemsTableBody');
        if (!tbody) return;
        tbody.innerHTML = '';
        if (data.data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">Chưa có giá trị nào</td></tr>';
            return;
        }
        data.data.forEach(item => {
            tbody.innerHTML += `
                <tr>
                    <td>${item.code || ''}</td>
                    <td>${item.value}</td>
                    <td>
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteDictionaryItem(${item.id})"><i class="fas fa-trash"></i></button>
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

async function deleteDictionaryItem(id) {
    if (!confirm("Xóa giá trị này?")) return;
    const data = await apiCall(`/api/dictionaries/items/${id}`, { method: 'DELETE' });
    if (data) {
        fetchDictionaryItems();
    }
}
