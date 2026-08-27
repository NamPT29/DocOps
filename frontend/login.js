function showLoginError(message) {
    const error = document.getElementById('loginError');
    if (!error) return;
    error.textContent = message;
    error.hidden = false;
}

async function doLogin() {
    const user = document.getElementById('loginUsername').value.trim();
    const pass = document.getElementById('loginPassword').value.trim();
    if (!user || !pass) return;

    try {
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: user, password: pass }),
        });
        const data = await response.json();

        if (data.status === 'ok') {
            localStorage.setItem('token', data.token);
            localStorage.setItem('user', JSON.stringify(data.user));
            window.location.href = data.user.role === 'admin' ? '/admin.html' : '/index.html';
            return;
        }
        showLoginError(data.message);
    } catch (error) {
        showLoginError('Lỗi kết nối máy chủ');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const username = document.getElementById('loginUsername');
    const password = document.getElementById('loginPassword');
    const loginButton = document.getElementById('loginButton');

    if (username) username.focus();
    if (loginButton) loginButton.addEventListener('click', doLogin);
    if (password) {
        password.addEventListener('keyup', event => {
            if (event.key === 'Enter') return doLogin();
            return undefined;
        });
    }
});
