let currentUser = null;
let currentToken = null;
let adminUserData = [];

const DEFAULT_SESSION_IDLE_TIMEOUT_MINUTES = 30;
const SESSION_ACTIVITY_RECENT_MS = 90 * 1000;
const SESSION_MONITOR_INTERVAL_MS = 10 * 1000;
const SESSION_HEARTBEAT_INTERVAL_MS = 30 * 1000;
const SESSION_CLOSE_SIGNAL_KEY = 'scanToExcelSessionCloseSignal';
const APP_TAB_ID = window.sessionStorage?.getItem('scanToExcelAppTabId')
    || window.crypto?.randomUUID?.()
    || `tab-${Date.now()}-${Math.random().toString(36).slice(2)}`;
window.sessionStorage?.setItem('scanToExcelAppTabId', APP_TAB_ID);

let lastUserActivityAt = Number(localStorage.getItem('sessionLastActivityAt')) || Date.now();
let lastActivityPersistedAt = lastUserActivityAt;
let lastSessionHeartbeatAt = 0;
let sessionMonitorTimer = null;
let sessionHeartbeatInFlight = false;
let sessionTrackingStarted = false;
let explicitLogoutInProgress = false;

function sessionIdleTimeoutMs() {
    const configured = Number(localStorage.getItem('sessionIdleTimeoutMinutes'));
    const minutes = Number.isFinite(configured) && configured > 0
        ? configured
        : DEFAULT_SESSION_IDLE_TIMEOUT_MINUTES;
    return minutes * 60 * 1000;
}

function persistSessionPolicy(data) {
    const idleMinutes = Number(data?.session_idle_timeout_minutes);
    if (Number.isFinite(idleMinutes) && idleMinutes > 0) {
        localStorage.setItem('sessionIdleTimeoutMinutes', String(idleMinutes));
    }
    const closeGraceSeconds = Number(data?.session_close_grace_seconds);
    if (Number.isFinite(closeGraceSeconds) && closeGraceSeconds > 0) {
        localStorage.setItem('sessionCloseGraceSeconds', String(closeGraceSeconds));
    }
}

function recordUserActivity() {
    const now = Date.now();
    lastUserActivityAt = now;
    if (now - lastActivityPersistedAt >= 1000) {
        localStorage.setItem('sessionLastActivityAt', String(now));
        lastActivityPersistedAt = now;
    }
}

function clearLocalSession(message) {
    if (sessionMonitorTimer) window.clearInterval(sessionMonitorTimer);
    sessionMonitorTimer = null;
    currentToken = null;
    currentUser = null;
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    localStorage.removeItem('sessionLastActivityAt');
    localStorage.removeItem('sessionIdleTimeoutMinutes');
    localStorage.removeItem('sessionCloseGraceSeconds');
    if (message) sessionStorage.setItem('authNotice', message);
}

function expireLocalSession(message = 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.') {
    if (explicitLogoutInProgress) return;
    clearLocalSession(message);
    if (!window.location.pathname.includes('login.html')) {
        window.location.href = '/login.html';
    }
}

async function sendSessionHeartbeat(userActive) {
    if (!currentToken || sessionHeartbeatInFlight) return;
    sessionHeartbeatInFlight = true;
    try {
        const response = await fetch('/api/session/heartbeat', {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${currentToken}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ user_active: userActive === true }),
            cache: 'no-store',
        });
        if (response.status === 401) {
            expireLocalSession('Phiên đăng nhập đã bị thu hồi hoặc hết thời gian sử dụng.');
            return;
        }
        if (response.ok) lastSessionHeartbeatAt = Date.now();
    } catch (_error) {
        // A temporary network failure must not erase a local draft. The server
        // remains authoritative and the next request/heartbeat will re-check it.
    } finally {
        sessionHeartbeatInFlight = false;
    }
}

function requestSessionClose() {
    const token = currentToken || localStorage.getItem('token');
    if (!token || explicitLogoutInProgress) return;
    fetch('/api/session/closing', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        keepalive: true,
    }).catch(() => undefined);
    localStorage.setItem(
        SESSION_CLOSE_SIGNAL_KEY,
        `${APP_TAB_ID}:${Date.now()}`,
    );
}

function startSessionLifecycle() {
    if (sessionTrackingStarted || !currentToken) return;
    sessionTrackingStarted = true;
    recordUserActivity();
    ['pointerdown', 'keydown', 'input', 'scroll', 'touchstart'].forEach(eventName => {
        document.addEventListener(eventName, recordUserActivity, {
            capture: true,
            passive: true,
        });
    });
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            recordUserActivity();
            sendSessionHeartbeat(true);
        }
    });
    window.addEventListener('storage', event => {
        if (event.key !== SESSION_CLOSE_SIGNAL_KEY || !event.newValue) return;
        // A surviving app tab cancels another tab's close request without
        // extending the idle timer. Delaying avoids racing ahead of keepalive.
        window.setTimeout(() => sendSessionHeartbeat(false), 750);
        window.setTimeout(() => sendSessionHeartbeat(false), 2000);
    });
    window.addEventListener('pagehide', event => {
        if (event.persisted || explicitLogoutInProgress) return;
        requestSessionClose();
    });
    sendSessionHeartbeat(true);
    sessionMonitorTimer = window.setInterval(() => {
        const sharedActivityAt = Number(localStorage.getItem('sessionLastActivityAt')) || lastUserActivityAt;
        const inactiveFor = Date.now() - Math.max(lastUserActivityAt, sharedActivityAt);
        if (inactiveFor >= sessionIdleTimeoutMs()) {
            expireLocalSession('Phiên đăng nhập đã tự thu hồi do không sử dụng trong thời gian cho phép.');
            return;
        }
        if (
            document.visibilityState === 'visible'
            && inactiveFor <= SESSION_ACTIVITY_RECENT_MS
            && Date.now() - lastSessionHeartbeatAt >= SESSION_HEARTBEAT_INTERVAL_MS
        ) {
            sendSessionHeartbeat(true);
        }
    }, SESSION_MONITOR_INTERVAL_MS);
}

function getOrCreateBrowserId() {
    const storageKey = 'scanToExcelBrowserId';
    let browserId = localStorage.getItem(storageKey);
    if (browserId) return browserId;
    browserId = window.crypto?.randomUUID?.()
        || `browser-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    localStorage.setItem(storageKey, browserId);
    return browserId;
}

function userDisplayName(user) {
    return String(user?.full_name || '').trim() || user?.username || '';
}

function currentUserCanInput() {
    if (!currentUser) return false;
    return currentUser.role === 'admin' || currentUser.can_input === true;
}

function currentUserCanReview() {
    if (!currentUser) return false;
    return currentUser.role === 'admin' || currentUser.can_review === true;
}

function configureCapabilityUI() {
    const canInput = currentUserCanInput();
    const canReview = currentUserCanReview();
    const hasCheckId = new URLSearchParams(window.location.search).has('check_id');
    const inputTabItem = document.getElementById('inputTabItem');
    const dataTabItem = document.getElementById('dataTabItem');
    const reviewTabItem = document.getElementById('reviewTabItem');
    const employeeTabs = document.getElementById('employeeTabs');
    const noAssignmentNotice = document.getElementById('noAssignmentNotice');
    const formPane = document.getElementById('form-pane');
    const dataPane = document.getElementById('data-pane');
    const hasAssignment = canInput || canReview;

    if (inputTabItem) inputTabItem.classList.toggle('d-none', !canInput);
    if (dataTabItem) dataTabItem.classList.toggle('d-none', !canInput);
    if (reviewTabItem) reviewTabItem.classList.toggle('d-none', !canReview);
    if (employeeTabs) employeeTabs.classList.toggle('d-none', !hasAssignment && !hasCheckId);
    if (noAssignmentNotice) {
        noAssignmentNotice.classList.toggle('d-none', hasAssignment || hasCheckId);
    }
    if (canReview && !hasCheckId && window.location.hash === '#review') {
        const reviewTab = document.getElementById('employee-review-tab');
        if (reviewTab) reviewTab.click();
    } else if (!canInput && canReview && !hasCheckId) {
        if (formPane) formPane.classList.remove('show', 'active');
        if (dataPane) dataPane.classList.remove('show', 'active');
        const reviewTab = document.getElementById('employee-review-tab');
        if (reviewTab) reviewTab.click();
    } else if (!hasAssignment && !hasCheckId) {
        document.querySelectorAll('#appTabsContent > .tab-pane').forEach(pane => {
            pane.classList.remove('show', 'active');
        });
    }
}

async function refreshCurrentUserProfile() {
    const data = await apiCall('/api/me', { cache: 'no-store' }, 'Không thể tải quyền được phân');
    if (!data || !data.user) return false;
    currentUser = data.user;
    localStorage.setItem('user', JSON.stringify(currentUser));
    const userNameText = document.getElementById('userNameText');
    if (userNameText) userNameText.innerText = userDisplayName(currentUser);
    return true;
}

function checkAuth() {
    const token = localStorage.getItem('token');
    const userStr = localStorage.getItem('user');
    
    if (token && userStr) {
        currentToken = token;
        currentUser = JSON.parse(userStr);
        startSessionLifecycle();
        
        // Show user info if element exists
        const userInfo = document.getElementById('userInfoDisplay');
        if (userInfo) userInfo.style.display = 'flex';
        
        const userNameText = document.getElementById('userNameText');
        if (userNameText) userNameText.innerText = userDisplayName(currentUser);
        
        // Try fetching user tasks for KPI if element exists
        // (Moved to handlePostAuthInit)
    } else {
        // Redirect to login if not already on login
        if (!window.location.pathname.includes('login.html')) {
            window.location.href = '/login.html';
        }
    }
}

async function handlePostAuthInit() {
    if (!(await refreshCurrentUserProfile())) return;
    await loadNotifications();
    configureCapabilityUI();
    const hasCheckId = new URLSearchParams(window.location.search).has('check_id');
    if (
        document.getElementById('templateSelectContainer')
        && (currentUserCanInput() || hasCheckId)
    ) {
        await populateTemplateDropdown();
    }
    
    if (typeof initApp === 'function' && (currentUserCanInput() || hasCheckId)) {
        initApp();
    }

    if (!currentUserCanInput() && currentUserCanReview() && !hasCheckId) {
        await fetchReviewSubmissions();
    }
}

let notificationItems = [];

async function loadNotifications() {
    const data = await apiCall('/api/notifications', {}, 'Không thể tải thông báo');
    if (!data) return;
    notificationItems = data.data || [];
    const badge = document.getElementById('notificationBadge');
    if (badge) {
        badge.textContent = data.unread_count > 99 ? '99+' : String(data.unread_count || '');
        badge.classList.toggle('d-none', !data.unread_count);
    }
    const list = document.getElementById('notificationList');
    if (!list) return;
    if (!notificationItems.length) {
        list.innerHTML = '<div class="text-center text-muted py-4">Chưa có thông báo.</div>';
        return;
    }
    list.innerHTML = notificationItems.map(item => `
        <button type="button" class="list-group-item list-group-item-action ${item.read_at ? '' : 'fw-semibold bg-light'}" data-auth-action="mark-notification-read" data-notification-id="${Number(item.id)}">
            <div class="d-flex justify-content-between gap-2"><span>${escapeHTML(item.title)}</span><small class="text-muted text-nowrap">${formatNotificationDate(item.created_at)}</small></div>
            <div class="small text-muted mt-1 text-start">${escapeHTML(item.message).replace(/\n/g, '<br>')}</div>
        </button>
    `).join('');
}

function formatNotificationDate(value) {
    if (!value) return '';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('vi-VN');
}

async function markNotificationRead(notificationId) {
    const data = await apiCall(`/api/notifications/${Number(notificationId)}/read`, { method: 'POST' });
    if (data) await loadNotifications();
}

async function markAllNotificationsRead() {
    const data = await apiCall('/api/notifications/read-all', { method: 'POST' });
    if (data) await loadNotifications();
}

async function loadNotificationRecipients() {
    const data = await apiCall('/api/users');
    const container = document.getElementById('notificationRecipients');
    if (!data || !container) return;
    container.innerHTML = data.data.map(user => `
        <label class="list-group-item d-flex align-items-center gap-2">
            <input class="form-check-input notification-recipient" type="checkbox" value="${Number(user.id)}">
            <span>${escapeHTML(user.username)}${user.role === 'admin' ? ' <span class="badge bg-danger">Admin</span>' : ''}</span>
        </label>
    `).join('');
}

async function sendNotification() {
    const title = document.getElementById('notificationTitle')?.value.trim();
    const message = document.getElementById('notificationMessage')?.value.trim();
    const recipientUserIds = [...document.querySelectorAll('.notification-recipient:checked')].map(input => Number(input.value));
    if (!title || !message || !recipientUserIds.length) {
        alert('Vui lòng nhập tiêu đề, nội dung và chọn ít nhất một người nhận.');
        return;
    }
    const data = await apiCall('/api/notifications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, message, recipient_user_ids: recipientUserIds }),
    });
    if (!data) return;
    document.getElementById('notificationTitle').value = '';
    document.getElementById('notificationMessage').value = '';
    document.querySelectorAll('.notification-recipient').forEach(input => { input.checked = false; });
    alert(`Đã gửi thông báo đến ${data.recipient_count} người.`);
}

async function doLogin() {
    const user = document.getElementById('loginUsername').value.trim();
    const pass = document.getElementById('loginPassword').value.trim();
    if (!user || !pass) return;
    
    try {
        const res = await fetch('/api/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                username: user,
                password: pass,
                browser_id: getOrCreateBrowserId(),
            })
        });
        const data = await res.json();
        
        if (data.status === 'ok') {
            localStorage.setItem('token', data.token);
            localStorage.setItem('user', JSON.stringify(data.user));
            localStorage.setItem('sessionLastActivityAt', String(Date.now()));
            persistSessionPolicy(data);
            if (data.user.role === 'admin') {
                window.location.href = '/admin.html';
            } else {
                window.location.href = '/index.html';
            }
        } else {
            document.getElementById('loginError').innerText = data.message;
            document.getElementById('loginError').style.display = 'block';
        }
    } catch (e) {
        document.getElementById('loginError').innerText = "Lỗi kết nối máy chủ";
        document.getElementById('loginError').style.display = 'block';
    }
}

function doLogout() {
    explicitLogoutInProgress = true;
    if (sessionMonitorTimer) window.clearInterval(sessionMonitorTimer);
    const tokenToRevoke = currentToken || localStorage.getItem('token');
    if (tokenToRevoke) {
        fetch('/api/logout', {
            method: 'POST',
            headers: { Authorization: `Bearer ${tokenToRevoke}` },
            keepalive: true,
        }).catch(() => undefined);
    }
    try {
        const storedUser = currentUser || JSON.parse(localStorage.getItem('user') || 'null');
        if (storedUser) {
            const userKey = storedUser.id || storedUser.username;
            const prefix = `formDraft_${userKey}_`;
            for (let index = localStorage.length - 1; index >= 0; index--) {
                const key = localStorage.key(index);
                if (key && key.startsWith(prefix)) localStorage.removeItem(key);
            }
        }
        localStorage.removeItem('formDraft');
    } catch (error) {
        console.error('Không thể xóa bản nháp khi đăng xuất:', error);
    }
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    localStorage.removeItem('sessionLastActivityAt');
    localStorage.removeItem('sessionIdleTimeoutMinutes');
    localStorage.removeItem('sessionCloseGraceSeconds');
    window.location.href = '/login.html';
}

async function authFetch(url, options = {}) {
    if (!options.headers) options.headers = {};
    if (currentToken) {
        options.headers['Authorization'] = 'Bearer ' + currentToken;
    }
    const res = await fetch(url, options);
    if (res.status === 401) {
        expireLocalSession('Phiên đăng nhập đã bị thu hồi hoặc hết thời gian sử dụng.');
        return null;
    }
    return res;
}

const apiCache = {};

function formatApiErrorDetail(detail) {
    if (Array.isArray(detail)) {
        return detail.map(error => {
            if (typeof error === 'string') return error;
            if (!error || typeof error !== 'object') return String(error);

            const field = Array.isArray(error.loc)
                ? error.loc.filter(part => part !== 'body').join('.')
                : '';
            const message = error.msg || JSON.stringify(error);
            return field ? `${field}: ${message}` : message;
        }).join('\n');
    }
    if (detail && typeof detail === 'object') return detail.msg || JSON.stringify(detail);
    return detail || 'Lỗi không xác định';
}

async function apiCall(url, options = {}, errorMessage = "Lỗi kết nối máy chủ") {
    try {
        // Simple caching for specific static GET requests
        const method = options.method || 'GET';
        if (method === 'GET' && (url.includes('/api/templates') || url.includes('/api/users'))) {
            const cacheKey = url;
            const now = Date.now();
            if (apiCache[cacheKey] && now - apiCache[cacheKey].timestamp < 5000) {
                // Return cached data if younger than 5 seconds
                return apiCache[cacheKey].data;
            }
        }
        
        const res = await authFetch(url, options);
        if (!res) return null; // 401 was handled by authFetch
        
        const data = await res.json();
        if (data.status === 'ok') {
            if (method === 'GET' && (url.includes('/api/templates') || url.includes('/api/users'))) {
                apiCache[url] = { data: data, timestamp: Date.now() };
            }
            return data;
        } else {
            alert('Lỗi: ' + formatApiErrorDetail(data.message || data.detail));
            return null;
        }
    } catch (err) {
        alert(errorMessage + ': ' + err.message);
        return null;
    }
}

// ---------------- ADMIN LOGIC ----------------

function renderPersonnelStatistics(rows) {
    const tbody = document.getElementById('personnelStatsTableBody');
    if (!tbody) return;

    const personnel = Array.isArray(rows) ? rows : [];
    if (personnel.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-3">Chưa có dữ liệu nhân sự.</td></tr>';
        return;
    }

    tbody.innerHTML = personnel.map(user => {
        const fullName = escapeHTML(userDisplayName(user));
        const username = escapeHTML(user.username || '');
        const activeProjects = Number(user.active_project_count) || 0;
        const submittedReports = Number(user.submitted_report_count) || 0;
        const reviewedReports = Number(user.reviewed_report_count) || 0;
        const inputErrors = Number(user.input_error_report_count) || 0;
        const reviewerErrors = Number(user.reviewer_error_field_count) || 0;
        return `
            <tr>
                <td><span class="fw-semibold">${fullName}</span><div class="small text-muted">${username}</div></td>
                <td class="text-center fw-semibold">${activeProjects}</td>
                <td class="text-center">${submittedReports}</td>
                <td class="text-center">${reviewedReports}</td>
                <td class="text-center">${inputErrors ? `<span class="badge bg-danger">${inputErrors}</span>` : '0'}</td>
                <td class="text-center">${reviewerErrors ? `<span class="badge bg-warning text-dark">${reviewerErrors}</span>` : '0'}</td>
            </tr>
        `;
    }).join('');
}

async function fetchAdminData() {
    if (currentUser.role !== 'admin') return;
    
    const [data, personnelStats] = await Promise.all([
        apiCall('/api/users'),
        apiCall('/api/users/personnel-stats'),
    ]);
    if (personnelStats) renderPersonnelStatistics(personnelStats.data);
    if (!data) return;
    
    const tbody = document.getElementById('adminUsersTableBody');
    if (tbody) {
        adminUserData = data.data;
        tbody.innerHTML = '';
        data.data.forEach(u => {
            const safeId = Number(u.id);
            const safeUsername = escapeHTML(u.username);
            const safeFullName = escapeHTML(userDisplayName(u));
            const safePhoneNumber = escapeHTML(u.phone_number || '—');
            const badges = [];
            if (u.role === 'admin') badges.push('<span class="badge bg-danger">Admin</span>');
            if (u.can_input) badges.push('<span class="badge bg-primary">Nhập liệu</span>');
            if (u.can_review) badges.push('<span class="badge bg-warning text-dark">Kiểm tra</span>');
            if (badges.length === 0) badges.push('<span class="badge bg-secondary">Chưa phân công</span>');
            const activeSessions = Number(u.active_session_count) || 0;
            const sessionLimit = Number(u.max_concurrent_sessions) || 1;
            let deleteBtn = safeId === currentUser.id ? '' : `<button class="btn btn-sm btn-danger" data-auth-action="delete-user" data-user-id="${safeId}"><i class="fas fa-trash"></i> Xóa</button>`;
            let changePwdBtn = `<button class="btn btn-sm btn-warning ms-1" data-auth-action="change-user-password" data-user-id="${safeId}" data-username="${safeUsername}"><i class="fas fa-key"></i> Đổi MK</button>`;
            let editBtn = `<button class="btn btn-sm btn-outline-primary ms-1" data-auth-action="edit-user" data-user-id="${safeId}"><i class="fas fa-user-pen"></i> Sửa</button>`;
            let revokeSessionsBtn = activeSessions > 0
                ? `<button class="btn btn-sm btn-outline-danger ms-1" data-auth-action="revoke-user-sessions" data-user-id="${safeId}" data-username="${safeUsername}"><i class="fas fa-right-from-bracket"></i> Giải phóng phiên</button>`
                : '';
            tbody.innerHTML += `
                <tr>
                    <td>${safeId}</td>
                    <td>${safeUsername}</td>
                    <td>${safeFullName}</td>
                    <td>${safePhoneNumber}</td>
                    <td><div class="d-flex flex-wrap gap-1">${badges.join('')}</div></td>
                    <td class="text-center"><span class="badge ${activeSessions >= sessionLimit ? 'bg-warning text-dark' : 'bg-light text-dark border'}">${activeSessions}/${sessionLimit}</span></td>
                    <td>${deleteBtn}${changePwdBtn}${editBtn}${revokeSessionsBtn}</td>
                </tr>
            `;
        });
    }
}

function openChangePasswordModal(userId, username) {
    document.getElementById('changePasswordUserId').value = userId;
    document.getElementById('changePasswordUsername').value = username;
    document.getElementById('changePasswordNew').value = '';
    document.getElementById('changePasswordError').style.display = 'none';
    const modal = new bootstrap.Modal(document.getElementById('changePasswordModal'));
    modal.show();
}

async function submitChangePassword() {
    const userId = document.getElementById('changePasswordUserId').value;
    const newPassword = document.getElementById('changePasswordNew').value;
    const errorEl = document.getElementById('changePasswordError');
    errorEl.style.display = 'none';
    
    if (!newPassword || newPassword.length < 8) {
        errorEl.textContent = 'Mật khẩu phải có ít nhất 8 ký tự';
        errorEl.style.display = 'block';
        return;
    }
    
    const data = await apiCall(`/api/users/${userId}/password`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ new_password: newPassword })
    });
    
    if (data) {
        alert('Đổi mật khẩu thành công!');
        bootstrap.Modal.getInstance(document.getElementById('changePasswordModal')).hide();
    }
}

function invalidateUsersCache() {
    delete apiCache['/api/users'];
}

async function deleteUser(userId) {
    if(!confirm("Bạn có chắc chắn muốn xóa tài khoản này? Toàn bộ tài liệu chưa xử lý của họ sẽ trở về trạng thái trống.")) return;
    
    const data = await apiCall(`/api/users/${userId}`, { method: 'DELETE' });
    if (data) {
        invalidateUsersCache();
        alert('Đã xóa thành công!');
        fetchAdminData();
        if (typeof fetchDocumentPool === 'function') fetchDocumentPool();
    }
}

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

async function createUser() {
    const u = document.getElementById('newUsername').value.trim();
    const p = document.getElementById('newPassword').value.trim();
    const fullName = document.getElementById('newFullName').value.trim();
    const phoneNumber = document.getElementById('newPhoneNumber').value.trim();
    const maxConcurrentSessions = Number(document.getElementById('newMaxConcurrentSessions').value) || 1;
    if (!u || !p) return alert("Vui lòng nhập tên và mật khẩu");
    if (p.length < 8) return alert("Mật khẩu phải có ít nhất 8 ký tự");
    const data = await apiCall('/api/users', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            username: u,
            password: p,
            full_name: fullName,
            phone_number: phoneNumber,
            max_concurrent_sessions: maxConcurrentSessions,
        })
    });
    
    if (data) {
        invalidateUsersCache();
        alert("Tạo tài khoản thành công!");
        document.getElementById('newUsername').value = '';
        document.getElementById('newPassword').value = '';
        document.getElementById('newFullName').value = '';
        document.getElementById('newPhoneNumber').value = '';
        document.getElementById('newMaxConcurrentSessions').value = '1';
        fetchAdminData();
    }
}



async function downloadExportResponse(res, fallbackFilename) {
    let filename = fallbackFilename;
    const disposition = res.headers.get('content-disposition');
    if (disposition && disposition.indexOf('filename=') !== -1) {
        const filenameRegex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
        const matches = filenameRegex.exec(disposition);
        if (matches != null && matches[1]) filename = matches[1].replace(/['"]/g, '');
    }
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.style.display = 'none';
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.URL.revokeObjectURL(url);
}

function openEditUserModal(userId) {
    const user = adminUserData.find(item => Number(item.id) === Number(userId));
    if (!user) return;
    document.getElementById('editUserId').value = user.id;
    document.getElementById('editUsername').value = user.username;
    document.getElementById('editFullName').value = userDisplayName(user);
    document.getElementById('editPhoneNumber').value = user.phone_number || '';
    document.getElementById('editMaxConcurrentSessions').value = Number(user.max_concurrent_sessions) || 1;
    new bootstrap.Modal(document.getElementById('editUserModal')).show();
}

async function submitEditUser() {
    const userId = document.getElementById('editUserId').value;
    const fullName = document.getElementById('editFullName').value.trim();
    const phoneNumber = document.getElementById('editPhoneNumber').value.trim();
    const maxConcurrentSessions = Number(document.getElementById('editMaxConcurrentSessions').value) || 1;
    const data = await apiCall(`/api/users/${userId}`, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            full_name: fullName,
            phone_number: phoneNumber,
            max_concurrent_sessions: maxConcurrentSessions,
        }),
    });
    if (!data) return;
    invalidateUsersCache();
    bootstrap.Modal.getInstance(document.getElementById('editUserModal')).hide();
    await fetchAdminData();
    alert('Đã cập nhật thông tin tài khoản!');
}

async function revokeUserSessions(userId, username) {
    if (!confirm(`Giải phóng các phiên đăng nhập của ${username}? Các trình duyệt đó sẽ phải đăng nhập lại.`)) return;
    const data = await apiCall(`/api/users/${userId}/sessions`, { method: 'DELETE' });
    if (!data) return;
    invalidateUsersCache();
    await fetchAdminData();
    alert(`Đã giải phóng ${Number(data.revoked_sessions) || 0} phiên đăng nhập.`);
}

function setExportAllStatus(message, isError = false) {
    const status = document.getElementById('exportAllStatus');
    if (!status) return;
    status.textContent = message || '';
    status.className = `small ${isError ? 'text-danger' : 'text-muted'}`;
}

async function exportAllReportsAsJob(params, templateId) {
    const button = document.getElementById('exportAllBtn');
    if (button) button.disabled = true;
    setExportAllStatus('Đang khởi tạo tác vụ xuất...');
    try {
        const createResponse = await authFetch(`/api/export-jobs?${params.toString()}`, {
            method: 'POST',
        });
        if (!createResponse) return;
        const createData = await createResponse.json().catch(() => ({}));
        if (!createResponse.ok) {
            throw new Error(formatApiErrorDetail(createData.detail || createData.message));
        }
        const jobId = createData.job && createData.job.job_id;
        if (!jobId) throw new Error('Máy chủ không trả về mã tác vụ xuất');

        const deadline = Date.now() + 60 * 60 * 1000;
        while (Date.now() < deadline) {
            await new Promise(resolve => setTimeout(resolve, 2000));
            const statusResponse = await authFetch(`/api/export-jobs/${jobId}`, { cache: 'no-store' });
            if (!statusResponse) return;
            const statusData = await statusResponse.json().catch(() => ({}));
            if (!statusResponse.ok) {
                throw new Error(formatApiErrorDetail(statusData.detail || statusData.message));
            }
            const job = statusData.job || {};
            setExportAllStatus(job.message || 'Đang tạo file Excel...');
            if (job.state === 'error') throw new Error(job.message || 'Tác vụ xuất thất bại');
            if (job.state !== 'completed') continue;

            const downloadResponse = await authFetch(`/api/export-jobs/${jobId}/download`);
            if (!downloadResponse) return;
            if (!downloadResponse.ok) {
                const errorData = await downloadResponse.json().catch(() => ({}));
                throw new Error(formatApiErrorDetail(errorData.detail || errorData.message));
            }
            await downloadExportResponse(
                downloadResponse,
                job.filename || `BaoCao_TatCa_${templateId}.xlsx`,
            );
            setExportAllStatus(`Đã tải ${Number(job.rows_total || 0).toLocaleString('vi-VN')} báo cáo.`);
            return;
        }
        throw new Error('Tác vụ xuất quá 60 phút chưa hoàn tất');
    } catch (error) {
        setExportAllStatus(error.message, true);
        alert(`Lỗi xuất báo cáo: ${error.message}`);
    } finally {
        if (button) button.disabled = false;
    }
}

async function exportExcelByTemplate(includePendingReview = false) {
    const tid = document.getElementById('filterTemplateId').value;
    if (!tid) return alert("Vui lòng chọn 1 biểu mẫu để xuất toàn bộ hồ sơ!");
    const params = new URLSearchParams({ template_id: tid });
    const startDate = document.getElementById('filterStartDate');
    const endDate = document.getElementById('filterEndDate');
    if (includePendingReview) {
        params.set('include_pending_review', 'true');
        return exportAllReportsAsJob(params, tid);
    } else {
        if (startDate && startDate.value) params.set('start_date', startDate.value);
        if (endDate && endDate.value) params.set('end_date', endDate.value);
    }
    
    // We can do a fetch but since it's downloading a file, we can just redirect to the download URL
    // since the API is protected by tokens, it's better to fetch and create a blob URL
    try {
        const res = await authFetch(`/api/export?${params.toString()}`);
        if (!res) return;
        if (!res.ok) {
            const data = await res.json();
            return alert("Lỗi: " + formatApiErrorDetail(data.detail || data.message));
        }
        
        await downloadExportResponse(res, `BaoCao_${tid}.xlsx`);
    } catch (e) {
        alert("Lỗi xuất báo cáo: " + e.message);
    }
}

// ---------------- USER LOGIC ----------------
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

// Init
document.addEventListener("DOMContentLoaded", () => {
    checkAuth();
    if (currentToken) {
        handlePostAuthInit();
    }
});

const AUTH_GENERATED_ACTIONS = Object.freeze({
    'mark-notification-read': trigger => markNotificationRead(Number(trigger.dataset.notificationId)),
    'delete-user': trigger => deleteUser(Number(trigger.dataset.userId)),
    'change-user-password': trigger => openChangePasswordModal(Number(trigger.dataset.userId), trigger.dataset.username),
    'edit-user': trigger => openEditUserModal(Number(trigger.dataset.userId)),
    'revoke-user-sessions': trigger => revokeUserSessions(Number(trigger.dataset.userId), trigger.dataset.username),
    'configure-template': trigger => openConfigModal(Number(trigger.dataset.templateId), decodeURIComponent(trigger.dataset.templateName)),
    'delete-template': trigger => deleteTemplate(Number(trigger.dataset.templateId), decodeURIComponent(trigger.dataset.templateName)),
});

document.addEventListener('click', event => {
    const trigger = event.target?.closest?.('[data-auth-action]');
    const action = trigger && AUTH_GENERATED_ACTIONS[trigger.dataset.authAction];
    if (action) action(trigger);
});
