// ==========================================
// ACCOUNT MANAGEMENT & PERSONNEL STATISTICS
// ==========================================

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
