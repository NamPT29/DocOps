(() => {
    'use strict';

    const actions = Object.freeze({
        'load-notifications': () => loadNotifications(),
        'logout': () => doLogout(),
        'fetch-submissions': () => fetchSubmissions(),
        'fetch-review-submissions': () => fetchReviewSubmissions(),
        'fetch-my-queue': () => fetchMyQueue(),
        'open-queue-root': () => openQueueFolder(null),
        'select-template': () => onTemplateSelected(),
        'toggle-pdf-link': () => togglePdfLink(),
        'toggle-form-check': () => toggleFormCheck(),
        'submit-draft': () => submitData('draft'),
        'submit-pending-review': () => submitData('pending_review'),
        'reset-form': () => resetFormData(),
        'cancel-edit': () => cancelEdit(),
        'next-review': () => goToNextReviewSubmission(),
        'select-all-submissions': () => selectAllSubmissionsOnPage(),
        'clear-submission-selection': () => clearSubmissionSelection(),
        'bulk-submit-submissions': () => bulkSubmitSelectedSubmissions(),
        'bulk-delete-submissions': () => bulkDeleteSelectedSubmissions(),
        'mark-notifications-read': () => markAllNotificationsRead(),
        'fetch-dashboard': () => fetchDashboardStats(),
        'fetch-admin-data': () => fetchAdminData(),
        'fetch-document-stats': () => fetchDocumentStats(),
        'initialize-assignment': () => {
            fetchDocumentStats();
            fetchReviewerReassignmentData();
            loadServerSourceFolders();
        },
        'fetch-admin-templates': () => fetchAdminTemplates(),
        'fetch-completed-submissions': () => fetchCompletedSubmissions(),
        'create-user': () => createUser(),
        'parent-server-folder': () => goToParentServerFolder(),
        'server-folder-root': () => loadServerSourceFolders(''),
        'open-server-folder': () => openSelectedServerFolder(),
        'scan-server-folder': () => scanSelectedServerFolder(),
        'upload-and-assign': () => uploadAndAssign(),
        'toggle-reviewer-folders': () => toggleAllReviewerFolders(),
        'reassign-reviewer': () => reassignDocumentReviewer(),
        'fetch-reviewer-reassignment': () => fetchReviewerReassignmentData(),
        'upload-template': () => uploadTemplate(),
        'export-template-excel': () => exportExcelByTemplate(),
        'fetch-template-dictionaries': () => fetchTemplateDictionaries(),
        'create-dictionary': () => createDictionary(),
        'create-dictionary-item': () => createDictionaryItem(),
        'preview-dictionary-import': () => previewBulkDictionaryItems(),
        'import-dictionary-items': () => importBulkDictionaryItems(),
        'add-rule-dictionary': () => addRuleDict(),
        'add-rule-sync': () => addRuleSync(),
        'add-rule-concat': () => addRuleConcat(),
        'generate-default-config': () => generateDefaultConfig(),
        'format-config': () => formatConfigJson(),
        'save-template-config': () => saveTemplateConfig(),
        'change-password': () => submitChangePassword(),
        'login': () => doLogin(),
        'login-on-enter': event => {
            if (event.key === 'Enter') doLogin();
        },
    });

    const eventBindings = Object.freeze({
        click: 'tempClick',
        change: 'tempChange',
        dblclick: 'tempDblclick',
        keyup: 'tempKeyup',
    });

    function dispatchTempAction(event) {
        const datasetKey = eventBindings[event.type];
        const actionElement = event.target?.closest?.(`[data-${datasetKey.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`)}]`);
        const action = actionElement && actions[actionElement.dataset[datasetKey]];
        if (action) return action(event, actionElement);
        return undefined;
    }

    Object.keys(eventBindings).forEach(eventName => {
        document.addEventListener(eventName, dispatchTempAction);
    });
})();
