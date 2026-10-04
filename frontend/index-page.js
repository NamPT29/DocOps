(() => {
    'use strict';

    // Immediate auth check prevents protected-page flicker before app startup.
    const token = localStorage.getItem('token');
    const userStr = localStorage.getItem('user');
    const urlParams = new URLSearchParams(window.location.search);
    const hasCheckId = urlParams.has('check_id');
    // BA 3.3: admins may enter data; the admin page opens this page with ?mode=input.
    const isAdminInputMode = urlParams.get('mode') === 'input';
    let isAdmin = false;
    if (!token || !userStr) {
        window.location.href = '/login.html';
    } else {
        isAdmin = JSON.parse(userStr).role === 'admin';
        if (isAdmin && !hasCheckId && !isAdminInputMode) {
            window.location.href = '/admin.html';
        }
    }

    function showAdminReturnLink() {
        if (!isAdmin || hasCheckId) return;
        const backButton = document.getElementById('backToAdminBtn');
        if (!backButton) return;
        backButton.href = '/admin.html#projects';
        backButton.classList.remove('d-none');
    }

    const clickActions = Object.freeze({
        loadNotifications: () => loadNotifications(),
        doLogout: () => doLogout(),
        fetchSubmissions: () => fetchSubmissions(),
        fetchReviewSubmissions: () => fetchReviewSubmissions(),
        refreshEmployeeProjectQueue: () => refreshEmployeeProjectQueue(),
        openQueueFolder: () => openQueueFolder(null),
        togglePdfLink: () => togglePdfLink(),
        submitDataDraft: () => submitData('draft'),
        submitDataPendingReview: () => submitData('pending_review'),
        resetFormData: () => resetFormData(),
        cancelEdit: () => cancelEdit(),
        goToNextReviewSubmission: () => goToNextReviewSubmission(),
        selectAllSubmissionsOnPage: () => selectAllSubmissionsOnPage(),
        clearSubmissionSelection: () => clearSubmissionSelection(),
        bulkSubmitSelectedSubmissions: () => bulkSubmitSelectedSubmissions(),
        bulkDeleteSelectedSubmissions: () => bulkDeleteSelectedSubmissions(),
        markAllNotificationsRead: () => markAllNotificationsRead(),
    });

    const changeActions = Object.freeze({
        onEmployeeProjectSelected: () => onEmployeeProjectSelected(),
        onTemplateSelected: () => onTemplateSelected(),
        confirmReviewSubmission: actionElement => confirmReviewSubmission(actionElement),
        fetchSubmissions: () => fetchSubmissions(),
        fetchReviewSubmissions: () => fetchReviewSubmissions(),
    });

    function dispatchAction(actionHandlers, event) {
        const actionElement = event.target?.closest?.('[data-action]');
        const handler = actionElement && actionHandlers[actionElement.dataset.action];
        if (handler) handler(actionElement);
    }

    function bindIndexPageActions() {
        document.addEventListener('click', event => dispatchAction(clickActions, event));
        document.addEventListener('change', event => dispatchAction(changeActions, event));
        showAdminReturnLink();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindIndexPageActions, { once: true });
    } else {
        bindIndexPageActions();
    }
})();
