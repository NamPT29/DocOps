// Immediate Auth Check to prevent flickering
const token = localStorage.getItem('token');
const userStr = localStorage.getItem('user');
if (!token || !userStr) {
    window.location.href = '/login.html';
} else {
    const user = JSON.parse(userStr);
    const urlParams = new URLSearchParams(window.location.search);
    const hasCheckId = urlParams.has('check_id');
    if (user.role === 'admin' && !hasCheckId) {
        window.location.href = '/admin.html';
    }
}
