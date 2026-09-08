function showLoginError(message) {
    const error = document.getElementById('loginError');
    if (!error) return;
    error.textContent = message;
    error.hidden = false;
}

function getOrCreateBrowserId() {
    const storageKey = 'scanToExcelBrowserId';
    let browserId = localStorage.getItem(storageKey);
    if (browserId) return browserId;
    browserId = window.crypto?.randomUUID?.()
        || `browser-${Array.from(window.crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('')}`;
    localStorage.setItem(storageKey, browserId);
    return browserId;
}

async function doLogin() {
    const user = document.getElementById('loginUsername').value.trim();
    const pass = document.getElementById('loginPassword').value.trim();
    if (!user || !pass) return;

    try {
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username: user,
                password: pass,
                browser_id: getOrCreateBrowserId(),
            }),
        });
        const data = await response.json();

        if (data.status === 'ok') {
            localStorage.setItem('token', data.token);
            localStorage.setItem('user', JSON.stringify(data.user));
            localStorage.setItem('sessionLastActivityAt', String(Date.now()));
            const idleMinutes = Number(data.session_idle_timeout_minutes);
            if (Number.isFinite(idleMinutes) && idleMinutes > 0) {
                localStorage.setItem('sessionIdleTimeoutMinutes', String(idleMinutes));
            }
            const closeGraceSeconds = Number(data.session_close_grace_seconds);
            if (Number.isFinite(closeGraceSeconds) && closeGraceSeconds > 0) {
                localStorage.setItem('sessionCloseGraceSeconds', String(closeGraceSeconds));
            }
            window.location.href = data.user.role === 'admin' ? '/admin.html' : '/index.html';
            return;
        }
        showLoginError(data.message || data.detail || 'Không thể đăng nhập');
    } catch (error) {
        showLoginError('Lỗi kết nối máy chủ');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const username = document.getElementById('loginUsername');
    const password = document.getElementById('loginPassword');
    const loginButton = document.getElementById('loginButton');
    const authNotice = sessionStorage.getItem('authNotice');
    if (authNotice) {
        sessionStorage.removeItem('authNotice');
        showLoginError(authNotice);
    }

    if (username) username.focus();
    if (loginButton) loginButton.addEventListener('click', doLogin);
    if (password) {
        password.addEventListener('keyup', event => {
            if (event.key === 'Enter') return doLogin();
            return undefined;
        });
    }
});
