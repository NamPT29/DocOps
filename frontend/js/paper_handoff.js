/* global authFetch, downloadExportResponse, formatApiErrorDetail, currentUser, bootstrap */

// =============================================================================
// SỔ GIAO NHẬN HỒ SƠ GIẤY (H1b, FR-ARR-02)
// Mỗi hộp một dòng, 5 mốc giao nhận. Chỉ mốc kế tiếp có nút Ghi; Xóa chỉ ở mốc cuối.
// Giờ hiện theo giờ Việt Nam (UTC+7) tính bằng getUTC*, không phụ thuộc múi giờ máy.
// Dữ liệu người dùng hiện bằng textContent.
// =============================================================================

const PAPER_HANDOFF_VN_OFFSET_MS = 7 * 60 * 60 * 1000;
var paperHandoffProject = null;
var paperHandoffData = null;
var paperHandoffEditing = null;

function paperHandoffPad(value) {
    return String(value).padStart(2, '0');
}

function paperHandoffVnDate(isoUtc) {
    const ms = Date.parse(isoUtc || '');
    return Number.isNaN(ms) ? null : new Date(ms + PAPER_HANDOFF_VN_OFFSET_MS);
}

// "2026-10-08T17:30:00Z" -> "09/10/2026 00:30"
function formatPaperHandoffTime(isoUtc) {
    const date = paperHandoffVnDate(isoUtc);
    if (!date) return '';
    return `${paperHandoffPad(date.getUTCDate())}/${paperHandoffPad(date.getUTCMonth() + 1)}/${date.getUTCFullYear()} `
        + `${paperHandoffPad(date.getUTCHours())}:${paperHandoffPad(date.getUTCMinutes())}`;
}

// Giá trị cho input datetime-local: "2026-10-08T01:30:00Z" -> "2026-10-08T08:30"
function paperHandoffToVnInput(isoUtc) {
    const date = paperHandoffVnDate(isoUtc);
    if (!date) return '';
    return `${date.getUTCFullYear()}-${paperHandoffPad(date.getUTCMonth() + 1)}-${paperHandoffPad(date.getUTCDate())}`
        + `T${paperHandoffPad(date.getUTCHours())}:${paperHandoffPad(date.getUTCMinutes())}`;
}

// Giá trị input (giờ Việt Nam) -> chuỗi gửi lên kèm múi giờ; rỗng/sai dạng -> null.
function paperHandoffFromVnInput(value) {
    const text = String(value || '').trim();
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(text)) return null;
    return `${text.slice(0, 16)}:00+07:00`;
}

function paperHandoffNextMilestone(milestones, events) {
    const next = milestones.find(milestone => !events[milestone.key]);
    return next ? next.key : null;
}

function paperHandoffLastMilestone(milestones, events) {
    const recorded = milestones.filter(milestone => events[milestone.key]);
    return recorded.length ? recorded[recorded.length - 1].key : null;
}

function paperHandoffIsAdmin() {
    return typeof currentUser !== 'undefined' && Boolean(currentUser) && currentUser.role === 'admin';
}

function paperHandoffElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
}

function paperHandoffButton(label, className, handler) {
    const button = paperHandoffElement('button', `btn btn-sm ${className}`, label);
    button.type = 'button';
    button.addEventListener('click', handler);
    return button;
}

function setPaperHandoffError(message) {
    const box = document.getElementById('paperHandoffError');
    if (!box) return;
    box.textContent = message || '';
    if (message) box.classList.remove('d-none');
    else box.classList.add('d-none');
}

async function paperHandoffErrorText(response) {
    const body = await response.json().catch(() => ({}));
    const detail = body && body.detail;
    if (detail && typeof detail === 'object' && !Array.isArray(detail) && detail.message) return detail.message;
    if (Array.isArray(detail)) return formatApiErrorDetail(detail);
    if (body && body.message) return body.message;
    if (detail) return formatApiErrorDetail(detail);
    return `Lỗi máy chủ (${response.status})`;
}

function renderPaperHandoffTable(data) {
    const table = document.getElementById('paperHandoffTable');
    if (!table) return;
    const milestones = (data && data.milestones) || [];
    const cases = (data && data.cases) || [];
    const isAdmin = paperHandoffIsAdmin();

    const head = paperHandoffElement('thead', 'table-light');
    const headRow = paperHandoffElement('tr');
    ['Hộp', 'Tên hộp', ...milestones.map(milestone => milestone.label)]
        .forEach(text => headRow.appendChild(paperHandoffElement('th', '', text)));
    head.appendChild(headRow);

    const body = paperHandoffElement('tbody');
    if (!cases.length) {
        const row = paperHandoffElement('tr');
        const cell = paperHandoffElement('td', 'text-center text-muted', 'Dự án chưa có hộp nào.');
        cell.colSpan = milestones.length + 2;
        row.appendChild(cell);
        body.appendChild(row);
    }
    cases.forEach(caseItem => {
        const events = caseItem.events || {};
        const next = paperHandoffNextMilestone(milestones, events);
        const last = paperHandoffLastMilestone(milestones, events);
        const row = paperHandoffElement('tr');
        const box = caseItem.box_number === null || caseItem.box_number === undefined ? '—' : caseItem.box_number;
        row.appendChild(paperHandoffElement('td', 'text-nowrap', box));
        row.appendChild(paperHandoffElement('td', '', caseItem.case_name || ''));
        milestones.forEach(milestone => {
            const cell = paperHandoffElement('td', 'small');
            cell.dataset.milestone = milestone.key;
            const event = events[milestone.key];
            if (event) {
                cell.appendChild(paperHandoffElement('div', 'fw-semibold', formatPaperHandoffTime(event.happened_at)));
                cell.appendChild(paperHandoffElement('div', '', event.received_by || ''));
                const actions = paperHandoffElement('div', 'd-flex gap-1 mt-1');
                actions.appendChild(paperHandoffButton('Sửa', 'btn-outline-primary py-0',
                    () => openPaperHandoffForm(caseItem, milestone, event)));
                if (isAdmin && milestone.key === last) {
                    actions.appendChild(paperHandoffButton('Xóa', 'btn-outline-danger py-0',
                        () => deletePaperHandoff(caseItem, milestone)));
                }
                cell.appendChild(actions);
            } else if (milestone.key === next) {
                cell.appendChild(paperHandoffButton('Ghi', 'btn-primary py-0',
                    () => openPaperHandoffForm(caseItem, milestone, null)));
            }
            row.appendChild(cell);
        });
        body.appendChild(row);
    });
    table.replaceChildren(head, body);
}

async function loadPaperHandoffs() {
    if (!paperHandoffProject) return false;
    const response = await authFetch(`/api/projects/${paperHandoffProject.id}/paper-handoffs`, { cache: 'no-store' });
    if (!response) return false;
    if (!response.ok) {
        setPaperHandoffError(await paperHandoffErrorText(response));
        return false;
    }
    const body = await response.json();
    paperHandoffData = body.data || { milestones: [], cases: [] };
    renderPaperHandoffTable(paperHandoffData);
    return true;
}

function paperHandoffField(id) {
    return document.getElementById(id);
}

function hidePaperHandoffForm() {
    paperHandoffEditing = null;
    const form = paperHandoffField('paperHandoffForm');
    if (form) form.classList.add('d-none');
}

function openPaperHandoffForm(caseItem, milestone, event) {
    paperHandoffEditing = { caseId: Number(caseItem.case_id), milestone: milestone.key };
    setPaperHandoffError('');
    paperHandoffField('paperHandoffFormTitle').textContent = `${caseItem.case_name || ''} – ${milestone.label}`;
    paperHandoffField('paperHandoffTime').value = event
        ? paperHandoffToVnInput(event.happened_at)
        : paperHandoffToVnInput(new Date().toISOString());
    paperHandoffField('paperHandoffHandedBy').value = event ? event.handed_by || '' : '';
    paperHandoffField('paperHandoffReceivedBy').value = event ? event.received_by || '' : '';
    paperHandoffField('paperHandoffNote').value = event ? event.note || '' : '';
    paperHandoffField('paperHandoffForm').classList.remove('d-none');
}

async function savePaperHandoff() {
    if (!paperHandoffProject || !paperHandoffEditing) return false;
    const happenedAt = paperHandoffFromVnInput(paperHandoffField('paperHandoffTime').value);
    if (!happenedAt) {
        setPaperHandoffError('Nhập thời gian.');
        return false;
    }
    const note = paperHandoffField('paperHandoffNote').value;
    const payload = {
        happened_at: happenedAt,
        handed_by: paperHandoffField('paperHandoffHandedBy').value,
        received_by: paperHandoffField('paperHandoffReceivedBy').value,
        note: note && note.trim() ? note : null,
    };
    const { caseId, milestone } = paperHandoffEditing;
    const response = await authFetch(
        `/api/projects/${paperHandoffProject.id}/cases/${caseId}/paper-handoffs/${encodeURIComponent(milestone)}`,
        { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
    );
    if (!response) return false;
    if (!response.ok) {
        setPaperHandoffError(await paperHandoffErrorText(response));
        return false;
    }
    setPaperHandoffError('');
    hidePaperHandoffForm();
    await loadPaperHandoffs();
    return true;
}

async function deletePaperHandoff(caseItem, milestone) {
    if (!paperHandoffProject) return false;
    if (!confirm(`Xóa mốc «${milestone.label}» của ${caseItem.case_name || 'hộp'}?`)) return false;
    const response = await authFetch(
        `/api/projects/${paperHandoffProject.id}/cases/${Number(caseItem.case_id)}/paper-handoffs/${encodeURIComponent(milestone.key)}`,
        { method: 'DELETE' },
    );
    if (!response) return false;
    if (!response.ok) {
        setPaperHandoffError(await paperHandoffErrorText(response));
        return false;
    }
    setPaperHandoffError('');
    hidePaperHandoffForm();
    await loadPaperHandoffs();
    return true;
}

async function downloadPaperHandoffs() {
    if (!paperHandoffProject) return false;
    const response = await authFetch(`/api/projects/${paperHandoffProject.id}/paper-handoffs.xlsx`);
    if (!response) return false;
    if (!response.ok) {
        setPaperHandoffError(await paperHandoffErrorText(response));
        return false;
    }
    await downloadExportResponse(response, `So_giao_nhan_${paperHandoffProject.id}.xlsx`);
    return true;
}

async function openPaperHandoffModal(project) {
    if (!project || !Number(project.id)) return false;
    paperHandoffProject = { id: Number(project.id), name: project.name || '' };
    paperHandoffData = null;
    paperHandoffField('paperHandoffTitle').textContent = paperHandoffProject.name;
    setPaperHandoffError('');
    hidePaperHandoffForm();
    const table = paperHandoffField('paperHandoffTable');
    if (table) table.replaceChildren();
    bootstrap.Modal.getOrCreateInstance(paperHandoffField('paperHandoffModal')).show();
    return loadPaperHandoffs();
}
