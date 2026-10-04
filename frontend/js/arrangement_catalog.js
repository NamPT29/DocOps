/* global apiCall, projectManagementProjects */

// =============================================================================
// ARRANGEMENT CATALOGUE (FR-ARR-01, QC-16)
// Preview an Excel catalogue, then confirm the import. Server text (titles,
// file names, error messages) is rendered with textContent only.
// =============================================================================

var arrangementProjectId = 0;
var arrangementPlanToken = null;

function arrangementElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
}

function arrangementTable(headers, rows) {
    const wrapper = arrangementElement('div', 'table-responsive');
    const table = arrangementElement('table', 'table table-sm table-bordered align-middle mb-2');
    const head = arrangementElement('thead', 'table-light');
    const headRow = arrangementElement('tr');
    headers.forEach(text => headRow.appendChild(arrangementElement('th', '', text)));
    head.appendChild(headRow);
    const body = arrangementElement('tbody');
    // A row is either a plain list of cells or { className, values }.
    rows.forEach(cells => {
        const plain = Array.isArray(cells);
        const row = arrangementElement('tr', plain ? '' : cells.className || '');
        (plain ? cells : cells.values).forEach(value => row.appendChild(arrangementElement('td', '', value)));
        body.appendChild(row);
    });
    table.append(head, body);
    wrapper.appendChild(table);
    return wrapper;
}

function arrangementSelectedFile() {
    const input = document.getElementById('arrangementCatalogFile');
    return input && input.files && input.files[0] ? input.files[0] : null;
}

function setArrangementImportEnabled(enabled) {
    const button = document.getElementById('arrangementImportButton');
    if (button) button.disabled = !enabled;
}

function appendArrangementList(container, title, items) {
    if (!items || !items.length) return;
    container.appendChild(arrangementElement('div', 'fw-semibold small mt-2', title));
    const list = arrangementElement('ul', 'small mb-2');
    items.forEach(item => {
        list.appendChild(arrangementElement('li', '', `Hộp ${item.box} / Hồ sơ ${item.dossier} – ${item.title}`));
    });
    container.appendChild(list);
}

function renderArrangementPreview(preview) {
    const container = document.getElementById('arrangementPreview');
    if (!container) return;
    container.replaceChildren();
    if (!preview) return;
    container.appendChild(arrangementElement(
        'div',
        'fw-semibold mb-2',
        `${preview.file_name}: ${preview.row_count} hồ sơ trong ${preview.box_count} hộp`,
    ));
    (preview.file_errors || []).forEach(message => {
        container.appendChild(arrangementElement('div', 'alert alert-danger py-2 small mb-2', message));
    });
    if (preview.summary) {
        const badges = arrangementElement('div', 'd-flex flex-wrap gap-2 mb-2');
        [
            ['Thêm', preview.summary.added, 'bg-success'],
            ['Sửa', preview.summary.updated, 'bg-primary'],
            ['Không đổi', preview.summary.unchanged, 'bg-secondary'],
            ['Xóa', preview.summary.removed, 'bg-danger'],
            ['Giữ lại (đã scan)', preview.summary.kept, 'bg-warning text-dark'],
            ['Hộp mới', preview.summary.new_boxes, 'bg-info text-dark'],
        ].forEach(([label, count, tone]) => {
            badges.appendChild(arrangementElement('span', `badge ${tone}`, `${label}: ${Number(count) || 0}`));
        });
        container.appendChild(badges);
    }
    const errors = preview.errors || [];
    if (preview.error_count) {
        const shown = errors.length < preview.error_count ? ` (hiện ${errors.length} lỗi đầu)` : '';
        container.appendChild(arrangementElement(
            'div',
            'text-danger small mb-1',
            `${preview.error_count} lỗi${shown}. Sửa file rồi bấm Xem trước lại; chưa có gì được ghi.`,
        ));
        container.appendChild(arrangementTable(
            ['Dòng Excel', 'Cột', 'Lỗi'],
            errors.map(error => [error.row, error.column, error.message]),
        ));
    }
    appendArrangementList(container, 'Sẽ xóa (hộp chưa scan):', preview.removed);
    appendArrangementList(container, 'Giữ lại và gắn cờ (hộp đã scan):', preview.kept);
}

function renderArrangementBoxes(data) {
    const body = document.getElementById('arrangementBoxesBody');
    const totals = document.getElementById('arrangementCatalogTotals');
    const boxes = (data && data.boxes) || [];
    if (totals) totals.textContent = `(${boxes.length} hộp, ${Number(data?.dossier_total) || 0} hồ sơ)`;
    if (!body) return;
    body.replaceChildren();
    if (!boxes.length) {
        const row = arrangementElement('tr');
        const cell = arrangementElement('td', 'text-center text-muted', 'Chưa có mục lục.');
        cell.colSpan = 6;
        row.appendChild(cell);
        body.appendChild(row);
        return;
    }
    boxes.forEach(box => {
        const row = arrangementElement('tr');
        row.appendChild(arrangementElement('td', 'fw-bold', box.box_number));
        const folder = arrangementElement('td');
        if (box.awaiting_scan) {
            folder.appendChild(arrangementElement('span', 'badge bg-secondary', 'Chờ scan'));
        } else {
            folder.textContent = box.folder || '';
        }
        row.appendChild(folder);
        row.appendChild(arrangementElement('td', 'text-center', box.dossier_count));
        row.appendChild(arrangementElement(
            'td',
            '',
            box.bad_paper_proposed ? `Đề xuất (${box.bad_paper_dossiers} hồ sơ đánh x)` : '—',
        ));
        row.appendChild(arrangementElement(
            'td',
            box.missing_count ? 'text-danger small' : '',
            box.missing_count ? `${box.missing_count} hồ sơ không còn trong mục lục mới` : '',
        ));
        const actions = arrangementElement('td');
        const button = arrangementElement('button', 'btn btn-sm btn-outline-primary py-0', 'Xem hồ sơ');
        button.type = 'button';
        button.addEventListener('click', () => loadArrangementBox(box.box_number));
        actions.appendChild(button);
        row.appendChild(actions);
        body.appendChild(row);
    });
}

function renderArrangementImports(imports) {
    const list = document.getElementById('arrangementImportHistory');
    if (!list) return;
    list.replaceChildren();
    if (!imports.length) {
        list.appendChild(arrangementElement('li', 'text-muted', 'Chưa import lần nào.'));
        return;
    }
    imports.forEach(entry => {
        const when = entry.created_at ? new Date(entry.created_at).toLocaleString('vi-VN') : '';
        list.appendChild(arrangementElement(
            'li',
            'mb-1',
            `${when} – ${entry.imported_by || 'không rõ'}: ${entry.file_name} (thêm ${entry.added}, `
            + `sửa ${entry.updated}, xóa ${entry.removed}, giữ lại ${entry.kept})`,
        ));
    });
}

async function loadArrangementBox(boxNumber) {
    const detail = document.getElementById('arrangementBoxDetail');
    const response = await apiCall(
        `/api/projects/${arrangementProjectId}/arrangement/catalog/boxes/${Number(boxNumber)}`,
        { cache: 'no-store' },
    );
    if (!response || !detail) return;
    detail.replaceChildren();
    detail.appendChild(arrangementElement('h6', 'mt-2', `Hộp ${Number(boxNumber)}`));
    detail.appendChild(arrangementTable(
        ['Hồ sơ số', 'Tiêu đề', 'Thời gian', 'THBQ', 'Số tờ', 'Giấy xấu', 'Ghi chú'],
        (response.data || []).map(item => ({
            className: item.missing_from_last_import ? 'table-warning' : '',
            values: [
                item.dossier,
                item.missing_from_last_import ? `${item.title} (không còn trong mục lục mới)` : item.title,
                `${item.start_date} – ${item.end_date}`,
                item.maintenance_code,
                item.sheet_count,
                item.bad_paper ? 'x' : '',
                item.note || '',
            ],
        })),
    ));
}

async function loadArrangementCatalog() {
    const response = await apiCall(
        `/api/projects/${arrangementProjectId}/arrangement/catalog`,
        { cache: 'no-store' },
    );
    if (!response) return false;
    renderArrangementBoxes(response.data);
    renderArrangementImports(response.data.imports || []);
    return true;
}

async function openArrangementCatalog(projectId) {
    const project = projectManagementProjects.find(item => Number(item.id) === Number(projectId));
    if (!project) return alert('Không tìm thấy dự án trong danh sách hiện tại.');
    arrangementProjectId = Number(project.id);
    arrangementPlanToken = null;
    setArrangementImportEnabled(false);
    document.getElementById('arrangementCatalogTitle').textContent = project.name;
    const input = document.getElementById('arrangementCatalogFile');
    if (input) input.value = '';
    renderArrangementPreview(null);
    const detail = document.getElementById('arrangementBoxDetail');
    if (detail) detail.replaceChildren();
    if (!(await loadArrangementCatalog())) return;
    new bootstrap.Modal(document.getElementById('arrangementCatalogModal')).show();
}

async function previewArrangementCatalog() {
    if (!arrangementProjectId) return;
    const file = arrangementSelectedFile();
    if (!file) return alert('Vui lòng chọn file mục lục .xlsx.');
    arrangementPlanToken = null;
    setArrangementImportEnabled(false);
    const form = new FormData();
    form.append('file', file);
    const response = await apiCall(
        `/api/projects/${arrangementProjectId}/arrangement/catalog/preview`,
        { method: 'POST', body: form },
    );
    if (!response) return;
    renderArrangementPreview(response.data);
    arrangementPlanToken = response.data.can_import ? response.data.plan_token : null;
    setArrangementImportEnabled(Boolean(arrangementPlanToken));
}

async function importArrangementCatalog() {
    const file = arrangementSelectedFile();
    if (!arrangementProjectId || !file || !arrangementPlanToken) return;
    const token = arrangementPlanToken;
    // A token is used once; after any answer the admin previews again.
    arrangementPlanToken = null;
    setArrangementImportEnabled(false);
    const form = new FormData();
    form.append('file', file);
    form.append('plan_token', token);
    const response = await apiCall(
        `/api/projects/${arrangementProjectId}/arrangement/catalog/import`,
        { method: 'POST', body: form },
    );
    if (!response) return;
    const summary = response.data.summary;
    renderArrangementPreview(null);
    document.getElementById('arrangementCatalogFile').value = '';
    await loadArrangementCatalog();
    alert(
        `Đã ghi mục lục: thêm ${summary.added}, sửa ${summary.updated}, `
        + `xóa ${summary.removed}, giữ lại ${summary.kept}, hộp mới ${summary.new_boxes}.`,
    );
}
