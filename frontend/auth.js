let currentUser = null;
let currentToken = null;

function checkAuth() {
    const token = localStorage.getItem('token');
    const userStr = localStorage.getItem('user');
    
    if (token && userStr) {
        currentToken = token;
        currentUser = JSON.parse(userStr);
        
        // Show user info if element exists
        const userInfo = document.getElementById('userInfoDisplay');
        if (userInfo) userInfo.style.display = 'flex';
        
        const userNameText = document.getElementById('userNameText');
        if (userNameText) userNameText.innerText = currentUser.username;
        
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
    if (document.getElementById('templateSelectContainer')) {
        await populateTemplateDropdown();
    }
    
    if (typeof initApp === 'function') {
        initApp();
    }
}

async function doLogin() {
    const user = document.getElementById('loginUsername').value.trim();
    const pass = document.getElementById('loginPassword').value.trim();
    if (!user || !pass) return;
    
    try {
        const res = await fetch('/api/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username: user, password: pass})
        });
        const data = await res.json();
        
        if (data.status === 'ok') {
            localStorage.setItem('token', data.token);
            localStorage.setItem('user', JSON.stringify(data.user));
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
    window.location.href = '/login.html';
}

async function authFetch(url, options = {}) {
    if (!options.headers) options.headers = {};
    if (currentToken) {
        options.headers['Authorization'] = 'Bearer ' + currentToken;
    }
    const res = await fetch(url, options);
    if (res.status === 401) {
        doLogout();
        return null;
    }
    return res;
}

const apiCache = {};

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
            alert('Lỗi: ' + (data.message || data.detail || 'Lỗi không xác định'));
            return null;
        }
    } catch (err) {
        alert(errorMessage + ': ' + err.message);
        return null;
    }
}

// ---------------- ADMIN LOGIC ----------------

async function fetchAdminData() {
    if (currentUser.role !== 'admin') return;
    
    // Fetch users for table
    const data = await apiCall('/api/users');
    if (!data) return;
    
    const tbody = document.getElementById('adminUsersTableBody');
    if (tbody) {
        tbody.innerHTML = '';
        data.data.forEach(u => {
            let badge = u.role === 'admin' ? '<span class="badge bg-danger">Admin</span>' : '<span class="badge bg-primary">Nhân viên</span>';
            const safeId = Number(u.id);
            const safeUsername = escapeHTML(u.username);
            let deleteBtn = safeId === currentUser.id ? '' : `<button class="btn btn-sm btn-danger" onclick="deleteUser(${safeId})"><i class="fas fa-trash"></i> Xóa</button>`;
            tbody.innerHTML += `
                <tr>
                    <td>${safeId}</td>
                    <td>${safeUsername}</td>
                    <td>${badge}</td>
                    <td>${deleteBtn}</td>
                </tr>
            `;
        });
    }
}

async function deleteUser(userId) {
    if(!confirm("Bạn có chắc chắn muốn xóa tài khoản này? Toàn bộ tài liệu chưa xử lý của họ sẽ trở về trạng thái trống.")) return;
    
    const data = await apiCall(`/api/users/${userId}`, { method: 'DELETE' });
    if (data) {
        alert('Đã xóa thành công!');
        fetchAdminData();
        if (typeof fetchDocumentPool === 'function') fetchDocumentPool();
    }
}

async function fetchDashboardStats() {
    if (currentUser.role !== 'admin') return;
    
    const data = await apiCall('/api/submissions');
    if (data) {
        const el = document.getElementById('dashTotalDocs');
        if (el) {
            el.innerText = data.data.length;
        }
    }
    
    // Also load templates dropdown so export/filter works
    await populateTemplatesDropdown('filterTemplateId', true);
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
                    <button class="btn btn-sm btn-outline-primary me-1" onclick="openConfigModal(${safeId}, decodeURIComponent('${encodedName}'))">
                        <i class="fas fa-cog"></i> Cấu hình
                    </button>
                    <button class="btn btn-sm btn-outline-danger" onclick="deleteTemplate(${safeId}, decodeURIComponent('${encodedName}'))">
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
    if (!u || !p) return alert("Vui lòng nhập tên và mật khẩu");
    
    const data = await apiCall('/api/users', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username: u, password: p})
    });
    
    if (data) {
        alert("Tạo tài khoản thành công!");
        document.getElementById('newUsername').value = '';
        document.getElementById('newPassword').value = '';
        fetchAdminData();
    }
}



async function exportExcelByTemplate() {
    const tid = document.getElementById('filterTemplateId').value;
    if (!tid) return alert("Vui lòng chọn 1 biểu mẫu ở ô bên cạnh để xuất dữ liệu!");
    
    // We can do a fetch but since it's downloading a file, we can just redirect to the download URL
    // since the API is protected by tokens, it's better to fetch and create a blob URL
    try {
        const res = await authFetch(`/api/export?template_id=${tid}`);
        if (!res) return;
        if (!res.ok) {
            const data = await res.json();
            return alert("Lỗi: " + data.message);
        }
        
        // Get filename from header
        let filename = `BaoCao_${tid}.xlsx`;
        const disposition = res.headers.get('content-disposition');
        if (disposition && disposition.indexOf('filename=') !== -1) {
            const filenameRegex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
            const matches = filenameRegex.exec(disposition);
            if (matches != null && matches[1]) { 
                filename = matches[1].replace(/['"]/g, '');
            }
        }
        
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
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
