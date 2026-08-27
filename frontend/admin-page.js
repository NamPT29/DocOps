const ADMIN_PAGE_ACTIONS = Object.freeze({
    logout: () => doLogout(),
    'fetch-dashboard': () => fetchDashboardStats(),
    'fetch-admin-data': () => fetchAdminData(),
    'initialize-projects': () => initializeProjectManagement(),
    'fetch-templates': () => fetchAdminTemplates(),
    'create-user': () => createUser(),
    'handle-project-folder': () => handleProjectFolderSelection(),
    'cancel-project-folder-update': () => cancelProjectFolderUpdate(),
    'update-project-level-options': () => updateProjectLevelOptions(),
    'sync-project-report-mode': () => syncProjectReportMode(),
    'create-project': () => createAndUploadProject(),
    'load-project-list': () => loadProjectList(),
    'upload-template': () => uploadTemplate(),
    'save-project-members': () => saveProjectMembers(),
    'reload-project-reports': () => reloadProjectReports(),
    'fetch-template-dictionaries': () => fetchTemplateDictionaries(),
    'create-dictionary': () => createDictionary(),
    'create-dictionary-item': () => createDictionaryItem(),
    'preview-bulk-dictionary-items': () => previewBulkDictionaryItems(),
    'import-bulk-dictionary-items': () => importBulkDictionaryItems(),
    'add-rule-dict': () => addRuleDict(),
    'add-rule-sync': () => addRuleSync(),
    'add-rule-concat': () => addRuleConcat(),
    'generate-default-config': () => generateDefaultConfig(),
    'format-config-json': () => formatConfigJson(),
    'save-template-config': () => saveTemplateConfig(),
    'submit-change-password': () => submitChangePassword(),
    'submit-edit-user': () => submitEditUser(),
});

function runAdminPageAction(actionName) {
    const action = ADMIN_PAGE_ACTIONS[actionName];
    if (action) return action();
    return undefined;
}

function handleAdminPageClick(event) {
    const trigger = event.target.closest('[data-admin-action]');
    if (!trigger) return;
    runAdminPageAction(trigger.dataset.adminAction);
}

function handleAdminPageChange(event) {
    const actionName = event.target.dataset.adminChange;
    if (actionName) runAdminPageAction(actionName);
}

async function initializeAdminPage() {
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

    // Load account and personnel statistics while the admin page initializes.
    fetchAdminData();

    // Restore the project/folder that opened the record editor.
    if (window.location.hash === '#projects') {
        const projectsTab = document.getElementById('projects-tab');
        if (projectsTab) new bootstrap.Tab(projectsTab).show();
        await initializeProjectManagement();
        await restoreProjectManagementNavigation();
    } else {
        fetchDashboardStats();
    }
}

document.addEventListener('click', handleAdminPageClick);
document.addEventListener('change', handleAdminPageChange);
document.addEventListener('DOMContentLoaded', initializeAdminPage);
