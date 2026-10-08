/* global authFetch, formatApiErrorDetail, bootstrap */

// =============================================================================
// BẢNG TIẾN ĐỘ DỰ ÁN (D2): đọc GET /api/projects/{id}/dashboard (D1).
// 3 ô số, bảng hạng mục, sản lượng 14 ngày (thanh ngang, không thư viện biểu đồ), bảng người 7 ngày.
// Dữ liệu hiện bằng textContent.
// =============================================================================

var projectDashboardProject = null;

function dashboardElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
}

function dashboardNumber(value) {
    return Number(value || 0).toLocaleString('vi-VN');
}

// "2026-10-29" -> "29/10/2026"; null -> "Chưa đủ số liệu"
function dashboardFinishDate(isoDate) {
    if (!isoDate) return 'Chưa đủ số liệu';
    const [year, month, day] = String(isoDate).split('-');
    return `${day}/${month}/${year}`;
}

// "2026-10-08" -> "08/10"
function dashboardShortDate(isoDate) {
    const [, month, day] = String(isoDate || '').split('-');
    return `${day}/${month}`;
}

// Độ rộng thanh: tỷ lệ với ngày lớn nhất (ngày lớn nhất 100%, ngày 0 là 0%).
function dashboardBarWidth(value, maxValue) {
    if (!maxValue || !value) return '0%';
    return `${Math.round((value / maxValue) * 100)}%`;
}

function dashboardTable(headers, rows) {
    const table = dashboardElement('table', 'table table-sm table-bordered align-middle mb-0');
    const head = dashboardElement('thead', 'table-light');
    const headRow = dashboardElement('tr');
    headers.forEach(text => headRow.appendChild(dashboardElement('th', '', text)));
    head.appendChild(headRow);
    const body = dashboardElement('tbody');
    rows.forEach(cells => {
        const row = dashboardElement('tr');
        cells.forEach(value => {
            if (value && typeof value === 'object' && typeof value.appendChild === 'function') row.appendChild(value);
            else row.appendChild(dashboardElement('td', '', value));
        });
        body.appendChild(row);
    });
    table.append(head, body);
    return table;
}

function dashboardTile(label, value, note) {
    const column = dashboardElement('div', 'col-md-4');
    const card = dashboardElement('div', 'border rounded p-3 h-100');
    card.appendChild(dashboardElement('div', 'small text-muted', label));
    card.appendChild(dashboardElement('div', 'fs-4 fw-bold', value));
    if (note) card.appendChild(dashboardElement('div', 'small text-muted', note));
    column.appendChild(card);
    return column;
}

function dashboardBarCell(day, maxValue) {
    const cell = dashboardElement('td', 'w-50');
    [['entered', 'bg-primary'], ['approved', 'bg-success']].forEach(([key, color]) => {
        const track = dashboardElement('div', 'progress mb-1');
        const bar = dashboardElement('div', `progress-bar ${color}`);
        bar.dataset.metric = key;
        bar.style.width = dashboardBarWidth(day[key], maxValue);
        track.appendChild(bar);
        cell.appendChild(track);
    });
    return cell;
}

function renderProjectDashboard(data) {
    const container = document.getElementById('projectDashboardBody');
    if (!container) return;
    const documents = data.documents || { total: 0, completed: 0, remaining: 0 };
    const forecast = data.forecast || {};
    const percent = documents.total ? ((documents.completed * 100) / documents.total).toFixed(1) : '0.0';

    const tiles = dashboardElement('div', 'row g-2 mb-3');
    tiles.dataset.section = 'tiles';
    tiles.append(
        dashboardTile('Văn bản hoàn thành', `${dashboardNumber(documents.completed)} / ${dashboardNumber(documents.total)}`, `${percent}%`),
        dashboardTile('Còn lại', dashboardNumber(documents.remaining), `Đã nhập: ${dashboardNumber(documents.entered)}`),
        dashboardTile('Dự kiến xong', dashboardFinishDate(forecast.estimated_finish_date),
            `Duyệt TB 7 ngày: ${dashboardNumber(forecast.avg_approved_per_day_7d)} văn bản/ngày`),
    );

    const stages = dashboardTable(
        ['Bước', 'Hộp xong / tổng', '%', 'Khối lượng xong', 'Đang làm', 'Trả lại'],
        (data.stages || []).map(stage => [
            stage.label,
            `${dashboardNumber(stage.boxes_done)} / ${dashboardNumber(stage.boxes_total)}`,
            `${stage.percent_done}%`,
            `${dashboardNumber(stage.volume_done)} ${stage.unit}`,
            dashboardNumber(stage.boxes_in_progress),
            dashboardNumber(stage.boxes_rejected),
        ]),
    );
    stages.dataset.section = 'stages';

    const daily = data.daily || [];
    const maxValue = Math.max(0, ...daily.map(day => Math.max(day.entered || 0, day.approved || 0)));
    const dailyTable = dashboardTable(
        ['Ngày', 'Nhập (thanh trên) / Duyệt (thanh dưới)', 'Nhập / Duyệt / Trang scan'],
        daily.map(day => [
            dashboardShortDate(day.date),
            dashboardBarCell(day, maxValue),
            `${dashboardNumber(day.entered)} / ${dashboardNumber(day.approved)} / ${dashboardNumber(day.scan_pages)}`,
        ]),
    );
    dailyTable.dataset.section = 'daily';

    const people = dashboardTable(
        ['Họ tên', 'Nhập', 'Duyệt', 'Trang scan'],
        (data.people || []).map(person => [
            person.name, dashboardNumber(person.entered), dashboardNumber(person.approved), dashboardNumber(person.scan_pages),
        ]),
    );
    people.dataset.section = 'people';

    container.replaceChildren(
        tiles,
        dashboardElement('h6', 'text-primary mt-2', 'Hạng mục'), stages,
        dashboardElement('h6', 'text-primary mt-3', 'Sản lượng 14 ngày gần nhất'), dailyTable,
        dashboardElement('h6', 'text-primary mt-3', 'Theo người (7 ngày gần nhất)'), people,
    );
}

function setProjectDashboardError(message) {
    const box = document.getElementById('projectDashboardError');
    if (!box) return;
    box.textContent = message || '';
    if (message) box.classList.remove('d-none');
    else box.classList.add('d-none');
}

async function loadProjectDashboard() {
    if (!projectDashboardProject) return false;
    setProjectDashboardError('');
    const response = await authFetch(`/api/projects/${projectDashboardProject.id}/dashboard`, { cache: 'no-store' });
    if (!response) return false;
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
        const detail = body && body.detail;
        const message = (detail && typeof detail === 'object' && !Array.isArray(detail) && detail.message)
            || body.message || formatApiErrorDetail(detail) || `Lỗi máy chủ (${response.status})`;
        setProjectDashboardError(message);
        return false;
    }
    renderProjectDashboard(body.data || {});
    return true;
}

async function openProjectDashboard(project) {
    if (!project || !Number(project.id)) return false;
    projectDashboardProject = { id: Number(project.id), name: project.name || '' };
    document.getElementById('projectDashboardTitle').textContent = projectDashboardProject.name;
    const container = document.getElementById('projectDashboardBody');
    if (container) container.replaceChildren(dashboardElement('div', 'text-muted', 'Đang tải...'));
    bootstrap.Modal.getOrCreateInstance(document.getElementById('projectDashboardModal')).show();
    return loadProjectDashboard();
}
