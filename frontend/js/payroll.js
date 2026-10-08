/* global authFetch, downloadExportResponse, formatApiErrorDetail, bootstrap */

// =============================================================================
// CHI TRẢ THEO SẢN LƯỢNG (P1b): đơn giá loại 1 theo dự án, bảng tạm tính theo kỳ (giờ Việt Nam).
// Dữ liệu hiện bằng textContent; tiền định dạng vi-VN (1.234.567).
// =============================================================================

const PAYROLL_RATE_CODES = ['NL-1', 'CN-1', 'SC-A4-1'];
const PAYROLL_VN_OFFSET_MS = 7 * 60 * 60 * 1000;
var payrollProject = null;

function payrollElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
}

function payrollMoney(value) {
    if (value === null || value === undefined || value === '') return '';
    return Number(value).toLocaleString('vi-VN');
}

// Ngày theo giờ Việt Nam dạng YYYY-MM-DD (đúng dạng API nhận), không phụ thuộc múi giờ máy.
function payrollVnDate(ms) {
    const date = new Date(ms + PAYROLL_VN_OFFSET_MS);
    const pad = value => String(value).padStart(2, '0');
    return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

function setPayrollError(message) {
    const box = document.getElementById('payrollError');
    if (!box) return;
    box.textContent = message || '';
    if (message) box.classList.remove('d-none');
    else box.classList.add('d-none');
}

async function payrollErrorText(response) {
    const body = await response.json().catch(() => ({}));
    const detail = body && body.detail;
    if (detail && typeof detail === 'object' && !Array.isArray(detail) && detail.message) return detail.message;
    if (body && body.message) return body.message;
    return formatApiErrorDetail(detail) || `Lỗi máy chủ (${response.status})`;
}

function payrollTable(id, headers, rows) {
    const table = document.getElementById(id);
    if (!table) return;
    const head = payrollElement('thead', 'table-light');
    const headRow = payrollElement('tr');
    headers.forEach(text => headRow.appendChild(payrollElement('th', '', text)));
    head.appendChild(headRow);
    const body = payrollElement('tbody');
    rows.forEach(cells => {
        const row = payrollElement('tr');
        cells.forEach(value => row.appendChild(payrollElement('td', '', value)));
        body.appendChild(row);
    });
    table.replaceChildren(head, body);
}

function renderPayrollRates(data) {
    (data.rates || []).forEach(rate => {
        const input = document.getElementById(`payrollRate-${rate.code}`);
        if (input) input.value = rate.unit_price === null || rate.unit_price === undefined ? '' : String(rate.unit_price);
    });
    const note = document.getElementById('payrollFactorNote');
    if (note) note.textContent = `Loại 2 (giấy xấu) = đơn giá loại 1 × ${String(data.bad_paper_factor).replace('.', ',')} (Chính sách dự án).`;
}

async function loadPayrollRates() {
    const response = await authFetch(`/api/projects/${payrollProject.id}/work-rates`, { cache: 'no-store' });
    if (!response) return false;
    if (!response.ok) {
        setPayrollError(await payrollErrorText(response));
        return false;
    }
    renderPayrollRates((await response.json()).data || {});
    return true;
}

async function savePayrollRates() {
    if (!payrollProject) return false;
    const rates = {};
    for (const code of PAYROLL_RATE_CODES) {
        const raw = String(document.getElementById(`payrollRate-${code}`).value || '').trim();
        if (!raw) {
            rates[code] = null;
            continue;
        }
        const value = Number(raw);
        if (!Number.isFinite(value)) {
            setPayrollError(`Đơn giá ${code} phải là số.`);
            return false;
        }
        rates[code] = value;
    }
    const response = await authFetch(`/api/projects/${payrollProject.id}/work-rates`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rates }),
    });
    if (!response) return false;
    if (!response.ok) {
        setPayrollError(await payrollErrorText(response));
        return false;
    }
    setPayrollError('');
    renderPayrollRates((await response.json()).data || {});
    return true;
}

function payrollPeriodQuery() {
    const from = String(document.getElementById('payrollFrom').value || '');
    const to = String(document.getElementById('payrollTo').value || '');
    if (!/^\d{4}-\d{2}-\d{2}$/.test(from) || !/^\d{4}-\d{2}-\d{2}$/.test(to)) {
        setPayrollError('Chọn từ ngày và đến ngày.');
        return null;
    }
    return `from=${from}&to=${to}`;
}

function renderPayrollPreview(data) {
    const warnings = document.getElementById('payrollWarnings');
    if (warnings) {
        warnings.replaceChildren(...(data.warnings || []).map(text => payrollElement('div', '', text)));
        if ((data.warnings || []).length) warnings.classList.remove('d-none');
        else warnings.classList.add('d-none');
    }
    payrollTable('payrollPeopleTable', ['Người', 'Thành tiền (VNĐ)', 'Ghi chú'], [
        ...(data.people || []).map(person => [person.name, payrollMoney(person.amount), person.complete ? '' : 'Thiếu đơn giá một số dòng']),
        ['Tổng', payrollMoney(data.total), ''],
    ]);
    payrollTable('payrollLinesTable', ['Người', 'Mã', 'Công việc', 'Đơn vị', 'Sản lượng', 'Đơn giá', 'Hệ số', 'Thành tiền'],
        (data.lines || []).map(line => [
            line.name, line.work_code, line.work, line.unit, payrollMoney(line.quantity), payrollMoney(line.unit_price),
            String(line.factor).replace('.', ','), payrollMoney(line.amount),
        ]));
}

async function previewPayroll() {
    if (!payrollProject) return false;
    const query = payrollPeriodQuery();
    if (!query) return false;
    const response = await authFetch(`/api/projects/${payrollProject.id}/payroll-preview?${query}`, { cache: 'no-store' });
    if (!response) return false;
    if (!response.ok) {
        setPayrollError(await payrollErrorText(response));
        return false;
    }
    setPayrollError('');
    renderPayrollPreview((await response.json()).data || {});
    return true;
}

async function downloadPayroll() {
    if (!payrollProject) return false;
    const query = payrollPeriodQuery();
    if (!query) return false;
    const response = await authFetch(`/api/projects/${payrollProject.id}/payroll-preview?${query}&format=xlsx`);
    if (!response) return false;
    if (!response.ok) {
        setPayrollError(await payrollErrorText(response));
        return false;
    }
    await downloadExportResponse(response, `Tam_tinh_chi_tra_${payrollProject.id}.xlsx`);
    return true;
}

async function openPayroll(project, nowMs = Date.now()) {
    if (!project || !Number(project.id)) return false;
    payrollProject = { id: Number(project.id), name: project.name || '' };
    document.getElementById('payrollTitle').textContent = payrollProject.name;
    setPayrollError('');
    const today = payrollVnDate(nowMs);
    document.getElementById('payrollFrom').value = `${today.slice(0, 8)}01`;
    document.getElementById('payrollTo').value = today;
    ['payrollPeopleTable', 'payrollLinesTable'].forEach(id => document.getElementById(id).replaceChildren());
    const warnings = document.getElementById('payrollWarnings');
    if (warnings) warnings.classList.add('d-none');
    bootstrap.Modal.getOrCreateInstance(document.getElementById('payrollModal')).show();
    return loadPayrollRates();
}
