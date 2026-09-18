// ==========================================
// ADMIN DASHBOARD & TEMPLATES
// ==========================================

function getVietnamToday() {
    const parts = new Intl.DateTimeFormat('en', {
        timeZone: 'Asia/Ho_Chi_Minh',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
    }).formatToParts(new Date());
    const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
}

function formatDashboardCalendarDate(date) {
    const year = date.getUTCFullYear();
    const month = String(date.getUTCMonth() + 1).padStart(2, '0');
    const day = String(date.getUTCDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function parseDashboardCalendarDate(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
    if (!match) return null;
    const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
    return formatDashboardCalendarDate(date) === value ? date : null;
}

function getDashboardPeriodRange(period, referenceDate) {
    const reference = parseDashboardCalendarDate(referenceDate)
        || parseDashboardCalendarDate(getVietnamToday());
    const start = new Date(reference.getTime());
    const endExclusive = new Date(reference.getTime());

    if (period === 'week') {
        const daysFromMonday = (start.getUTCDay() + 6) % 7;
        start.setUTCDate(start.getUTCDate() - daysFromMonday);
        endExclusive.setTime(start.getTime());
        endExclusive.setUTCDate(endExclusive.getUTCDate() + 7);
    } else if (period === 'month') {
        start.setUTCDate(1);
        endExclusive.setUTCFullYear(start.getUTCFullYear(), start.getUTCMonth() + 1, 1);
    } else {
        endExclusive.setUTCDate(endExclusive.getUTCDate() + 1);
    }

    const startDate = formatDashboardCalendarDate(start);
    const endDateValue = new Date(endExclusive.getTime());
    endDateValue.setUTCDate(endDateValue.getUTCDate() - 1);
    const endDate = formatDashboardCalendarDate(endDateValue);
    const startBoundary = new Date(`${startDate}T00:00:00+07:00`);
    const endBoundary = new Date(`${formatDashboardCalendarDate(endExclusive)}T00:00:00+07:00`);
    endBoundary.setMilliseconds(endBoundary.getMilliseconds() - 1);

    return {
        startDate,
        endDate,
        startUtc: startBoundary.toISOString().replace('Z', ''),
        endUtc: endBoundary.toISOString().replace('Z', ''),
    };
}

function getDashboardCustomRange(startDate, endDate) {
    const start = parseDashboardLocalDateTime(startDate);
    const end = parseDashboardLocalDateTime(endDate);
    if (!start || !end || start.boundary.getTime() > end.boundary.getTime()) return null;

    return {
        startDateTime: start.value,
        endDateTime: end.value,
        startUtc: start.boundary.toISOString().replace('Z', ''),
        endUtc: end.boundary.toISOString().replace('Z', ''),
    };
}

function parseDashboardLocalDateTime(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(String(value || ''));
    if (!match) return null;

    const [, year, month, day, hour, minute] = match;
    const calendarDate = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
    if (
        formatDashboardCalendarDate(calendarDate) !== `${year}-${month}-${day}`
        || Number(hour) > 23
        || Number(minute) > 59
    ) return null;

    const normalized = `${year}-${month}-${day}T${hour}:${minute}`;
    const boundary = new Date(`${normalized}:00+07:00`);
    if (Number.isNaN(boundary.getTime())) return null;
    return { value: normalized, boundary };
}

function getVietnamNowLocal() {
    const parts = new Intl.DateTimeFormat('en', {
        timeZone: 'Asia/Ho_Chi_Minh',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hourCycle: 'h23',
    }).formatToParts(new Date());
    const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}T${values.hour}:${values.minute}`;
}

function formatDashboardDateLabel(value) {
    const [year, month, day] = value.split('-');
    return `${day}/${month}/${year}`;
}

function formatDashboardDateTimeLabel(value) {
    const [date, time] = value.split('T');
    return `${time} ${formatDashboardDateLabel(date)}`;
}

async function fetchDashboardStats() {
    if (!currentUser || currentUser.role !== 'admin') return;

    const dashboardStatus = document.getElementById('dashboardStatus');
    if (dashboardStatus) dashboardStatus.textContent = 'Đang cập nhật dữ liệu...';

    const periodFilter = document.getElementById('dashboardPeriodFilter');
    const referenceInput = document.getElementById('dashboardReferenceDate');
    const referenceGroup = document.getElementById('dashboardReferenceDateGroup');
    const dateRangeFields = document.getElementById('dashboardDateRangeFields');
    const startInput = document.getElementById('dashboardStartDate');
    const endInput = document.getElementById('dashboardEndDate');
    const periodCount = document.getElementById('dashPeriodDocs');
    const periodTitle = document.getElementById('dashPeriodTitle');
    const periodRange = document.getElementById('dashPeriodRange');
    let range = null;
    let periodRequest = Promise.resolve(null);

    if (periodFilter && periodCount) {
        const today = getVietnamToday();
        const period = ['day', 'week', 'month', 'range'].includes(periodFilter.value)
            ? periodFilter.value
            : 'day';
        const isCustomRange = period === 'range';
        if (referenceGroup) referenceGroup.classList.toggle('d-none', isCustomRange);
        if (dateRangeFields) dateRangeFields.classList.toggle('d-none', !isCustomRange);

        if (referenceInput) {
            if (!referenceInput.value) referenceInput.value = today;
            referenceInput.max = today;
        }
        if (startInput && endInput) {
            const now = getVietnamNowLocal();
            if (!endInput.value) endInput.value = now;
            if (!startInput.value) {
                startInput.value = `${getDashboardPeriodRange('month', today).startDate}T00:00`;
            }
            startInput.max = endInput.value || now;
            endInput.min = startInput.value || '';
            endInput.max = now;
        }

        range = isCustomRange
            ? getDashboardCustomRange(startInput && startInput.value, endInput && endInput.value)
            : getDashboardPeriodRange(period, referenceInput && referenceInput.value);
        const labels = {
            day: 'Hồ sơ nhập trong ngày',
            week: 'Hồ sơ nhập trong tuần',
            month: 'Hồ sơ nhập trong tháng',
            range: 'Hồ sơ nhập từ ngày đến ngày',
        };
        if (periodTitle) periodTitle.textContent = labels[period];
        if (periodRange) {
            periodRange.textContent = range
                ? (isCustomRange
                    ? `${formatDashboardDateTimeLabel(range.startDateTime)} – ${formatDashboardDateTimeLabel(range.endDateTime)}`
                    : `${formatDashboardDateLabel(range.startDate)} – ${formatDashboardDateLabel(range.endDate)}`)
                : 'Khoảng ngày không hợp lệ';
        }
        if (range) {
            periodCount.innerText = '...';
            const params = new URLSearchParams({
                page: '1',
                page_size: '1',
                start_date: range.startUtc,
                end_date: range.endUtc,
            });
            periodRequest = apiCall(`/api/submissions?${params.toString()}`);
        } else {
            periodCount.innerText = '—';
        }
    }

    const [data, periodData] = await Promise.all([
        apiCall('/api/submissions'),
        periodRequest,
    ]);
    if (data) {
        const el = document.getElementById('dashTotalDocs');
        if (el) {
            el.innerText = data.pagination.total;
        }
    }
    if (periodCount && periodData) {
        periodCount.innerText = periodData.pagination.total;
    }

    // Render per-user detail table from stats API
    const statsData = await apiCall('/api/documents/stats');
    if (statsData && statsData.user_stats) {
        let totalPendingReview = 0;
        let totalCompleted = 0;
        const tbody = document.getElementById('dashUserDetailBody');
        if (tbody) {
            tbody.innerHTML = '';
            const users = statsData.user_stats.filter(u => u.submissions_total > 0 || u.pending > 0 || u.completed > 0);
            if (users.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3">Chưa có dữ liệu nhập liệu.</td></tr>';
            } else {
                users.forEach(u => {
                    totalPendingReview += u.submissions_pending_review || 0;
                    totalCompleted += u.submissions_completed || 0;
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td class="fw-semibold"><i class="fas fa-user text-primary me-1"></i> ${escapeHTML(u.username)}</td>
                        <td class="text-center">${u.pending}</td>
                        <td class="text-center">${u.completed}</td>
                        <td class="text-center">${u.submissions_draft || 0}</td>
                        <td class="text-center"><span class="badge bg-warning text-dark">${u.submissions_pending_review || 0}</span></td>
                        <td class="text-center"><span class="badge bg-success">${u.submissions_completed || 0}</span></td>
                        <td class="text-center fw-bold">${u.submissions_total || 0}</td>
                    `;
                    tbody.appendChild(tr);
                });
            }
        }
        const pendingEl = document.getElementById('dashPendingReview');
        const completedEl = document.getElementById('dashApproved');
        if (pendingEl) pendingEl.textContent = totalPendingReview;
        if (completedEl) completedEl.textContent = totalCompleted;
    }

    // Also load templates dropdown so export/filter works
    await populateTemplatesDropdown('filterTemplateId', true);
    if (dashboardStatus) {
        dashboardStatus.textContent = `Đã cập nhật lúc ${new Intl.DateTimeFormat('vi-VN', {
            timeZone: 'Asia/Ho_Chi_Minh',
            hour: '2-digit',
            minute: '2-digit',
        }).format(new Date())}`;
    }
}

async function populateTemplatesDropdown(elementId, keepDefault = false) {
    const data = await apiCall('/api/templates');
    if (!data) return;
    
    const select = document.getElementById(elementId);
    if (!select) return;
    
    let originalContent = '';
    if (keepDefault) {
        originalContent = select.innerHTML;
    }
    
    select.innerHTML = originalContent;
    data.data.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t.id;
        opt.innerText = t.name;
        select.appendChild(opt);
    });
}

async function fetchAdminTemplates() {
    const data = await apiCall('/api/templates');
    if (!data) return;
    
    const tbody = document.getElementById('templatesTableBody');
    tbody.innerHTML = '';
    if (data.data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="text-center">Chưa có biểu mẫu nào.</td></tr>';
        return;
    }
    data.data.forEach(t => {
        const safeId = Number(t.id);
        const safeName = escapeHTML(t.name);
        const safeFilename = escapeHTML(t.filename);
        const encodedName = encodeURIComponent(t.name).replace(/'/g, '%27');
        tbody.innerHTML += `
            <tr>
                <td>${safeId}</td>
                <td><b>${safeName}</b></td>
                <td>${safeFilename}</td>
                <td>
                    <button class="btn btn-sm btn-outline-primary me-1" data-auth-action="configure-template" data-template-id="${safeId}" data-template-name="${encodedName}">
                        <i class="fas fa-cog"></i> Cấu hình
                    </button>
                    <button class="btn btn-sm btn-outline-danger" data-auth-action="delete-template" data-template-id="${safeId}" data-template-name="${encodedName}">
                        <i class="fas fa-trash"></i> Xóa
                    </button>
                </td>
            </tr>
        `;
    });
}

async function deleteTemplate(id, name) {
    if (!confirm(`Xóa biểu mẫu "${name}" ?\nLưu ý: Hồ sơ đã nhập liệu liên quan sẽ không bị xóa.`)) return;
    const data = await apiCall(`/api/templates/${id}`, { method: 'DELETE' });
    if (data) {
        fetchAdminTemplates();
    }
}

async function uploadTemplate() {
    const fileInput = document.getElementById('newTemplateFile');
    if (!fileInput.files || fileInput.files.length === 0) {
        return alert("Vui lòng chọn 1 file Excel mẫu (.xlsx hoặc .xlsm)");
    }
    
    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    
    const data = await apiCall('/api/templates', {
        method: 'POST',
        body: formData
    });
    
    if (data) {
        alert("Tải mẫu lên thành công!");
        fileInput.value = "";
        fetchAdminTemplates();
    }
}

async function populateTemplateDropdown() {
    const data = await apiCall('/api/templates');
    if (!data) return;
    
    if (data.data.length > 0) {
        const select = document.getElementById('templateSelect');
        const container = document.getElementById('templateSelectContainer');
        if (select && container) {
            select.replaceChildren();
            const placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = '-- Chọn Biểu mẫu --';
            select.appendChild(placeholder);
            data.data.forEach(t => {
                const option = document.createElement('option');
                option.value = Number(t.id);
                option.textContent = t.name;
                select.appendChild(option);
            });
            container.style.display = 'block';
            
            // if we have activeTemplateId (like when editing), select it
            if (window.activeTemplateId) {
                select.value = window.activeTemplateId;
            }
        }
    }
}
