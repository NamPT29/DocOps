/* global currentToken:writable, currentUser:writable, activeReviewFolderPath:writable */

document.addEventListener('DOMContentLoaded', () => {
    const token = localStorage.getItem('token');
    const userStr = localStorage.getItem('user');
    if (!token || !userStr) {
        window.location.href = '/login.html';
        return;
    }
    const user = JSON.parse(userStr);
    if (user.role !== 'admin') {
        window.location.href = '/index.html';
        return;
    }

    currentToken = token;
    currentUser = user;
    document.getElementById('userNameText').innerText = user.username;

    // Auto open tab and folder from the page that opened the record editor.
    const urlParams = new URLSearchParams(window.location.search);
    if (window.location.hash === '#review') {
        const returnFolder = urlParams.get('return_folder');
        if (returnFolder) activeReviewFolderPath = returnFolder;
        const reviewTab = document.getElementById('review-tab');
        if (reviewTab) {
            const tab = new bootstrap.Tab(reviewTab);
            tab.show();
            fetchReviewSubmissions();
        }
    } else if (window.location.hash === '#data') {
        const dataTab = document.getElementById('data-tab');
        if (dataTab) {
            const tab = new bootstrap.Tab(dataTab);
            tab.show();
            fetchCompletedSubmissions();
        }
    } else {
        fetchDashboardStats();
    }
});
