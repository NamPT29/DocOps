(() => {
    'use strict';

    // Immediate auth check prevents protected-page flicker before app startup.
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
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindIndexPageActions, { once: true });
    } else {
        bindIndexPageActions();
    }
})();
