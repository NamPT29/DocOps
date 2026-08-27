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
        document.getElementById('loginError').innerText = 'Lỗi kết nối máy chủ';
        document.getElementById('loginError').style.display = 'block';
    }
}

// Luôn cho phép đăng nhập lại để người dùng có thể đổi tài khoản.
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('loginUsername').focus();
});
