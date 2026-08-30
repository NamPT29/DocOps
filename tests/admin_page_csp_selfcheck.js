const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const projectRoot = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(projectRoot, 'frontend', 'admin.html'), 'utf8');
const script = fs.readFileSync(path.join(projectRoot, 'frontend', 'admin-page.js'), 'utf8');

assert.doesNotMatch(html, /<script\b(?![^>]*\bsrc\s*=)[^>]*>/i, 'Admin page must not contain inline scripts.');
assert.doesNotMatch(html, /\bon[a-z]+\s*=/i, 'Admin page must not contain inline event handlers.');
assert.doesNotMatch(html, /<style\b/i, 'Admin page must not contain inline style elements.');
assert.doesNotMatch(html, /\bstyle\s*=/i, 'Admin page must not contain inline style attributes.');
assert.match(html, /href="admin-page\.css\?v=1"/i, 'Admin page must load its external stylesheet.');
assert.match(html, /src="admin-page\.js\?v=2"/i, 'Admin page must load its external behavior script.');

const actionNames = [...html.matchAll(/data-admin-action="([^"]+)"/g)].map(match => match[1]);
const changeNames = [...html.matchAll(/data-admin-change="([^"]+)"/g)].map(match => match[1]);
assert.equal(actionNames.length, 25, 'All current click handlers must be represented by declarative actions.');
assert.equal(changeNames.length, 7, 'All former change handlers must be represented by declarative actions.');

const calls = [];
const listeners = {};
const userNameText = { innerText: '' };
const projectsTab = {};
const actionFunctions = {
    doLogout: [],
    fetchDashboardStats: [],
    fetchAdminData: [],
    initializeProjectManagement: [],
    fetchAdminTemplates: [],
    createUser: [],
    handleProjectFolderSelection: [],
    cancelProjectFolderUpdate: [],
    updateProjectLevelOptions: [],
    syncProjectReportMode: [],
    createAndUploadProject: [],
    loadProjectList: [],
    uploadTemplate: [],
    saveProjectMembers: [],
    reloadProjectReports: [],
    fetchTemplateDictionaries: [],
    createDictionary: [],
    createDictionaryItem: [],
    previewBulkDictionaryItems: [],
    importBulkDictionaryItems: [],
    addRuleDict: [],
    addRuleSync: [],
    addRuleConcat: [],
    generateDefaultConfig: [],
    formatConfigJson: [],
    saveTemplateConfig: [],
    submitChangePassword: [],
    submitEditUser: [],
    restoreProjectManagementNavigation: [],
};

const sandbox = {
    console,
    currentToken: null,
    currentUser: null,
    document: {
        addEventListener(type, handler) { listeners[type] = handler; },
        getElementById(id) {
            if (id === 'userNameText') return userNameText;
            if (id === 'projects-tab') return projectsTab;
            return null;
        },
    },
    localStorage: {
        getItem(key) {
            if (key === 'token') return 'admin-token';
            if (key === 'user') return JSON.stringify({ id: 1, username: 'root-admin', role: 'admin' });
            return null;
        },
    },
    window: { location: { href: '', hash: '' } },
    bootstrap: {
        Tab: class {
            constructor(element) { this.element = element; }
            show() { calls.push({ name: 'bootstrap.Tab.show', args: [this.element] }); }
        },
    },
};

for (const name of Object.keys(actionFunctions)) {
    sandbox[name] = (...args) => {
        calls.push({ name, args });
        return Promise.resolve();
    };
}

vm.createContext(sandbox);
vm.runInContext(script, sandbox, { filename: 'frontend/admin-page.js' });

assert.equal(typeof listeners.click, 'function');
assert.equal(typeof listeners.change, 'function');
assert.equal(typeof listeners.DOMContentLoaded, 'function');

(async () => {
    await listeners.DOMContentLoaded();
    assert.equal(sandbox.currentToken, 'admin-token');
    assert.equal(sandbox.currentUser.username, 'root-admin');
    assert.equal(userNameText.innerText, 'root-admin');
    assert(calls.some(call => call.name === 'fetchDashboardStats'));

    calls.length = 0;
    for (const actionName of actionNames) {
        const trigger = { dataset: { adminAction: actionName } };
        listeners.click({ target: { closest: () => trigger } });
    }
    for (const changeName of changeNames) {
        listeners.change({ target: { dataset: { adminChange: changeName } } });
    }
    assert.equal(calls.length, actionNames.length + changeNames.length, 'Every declarative action must resolve to one handler.');
    assert(calls.some(call => call.name === 'saveProjectMembers' && call.args.length === 0));

    calls.length = 0;
    sandbox.window.location.hash = '#projects';
    await listeners.DOMContentLoaded();
    assert(calls.some(call => call.name === 'bootstrap.Tab.show' && call.args[0] === projectsTab));
    assert(calls.some(call => call.name === 'initializeProjectManagement'));
    assert(calls.some(call => call.name === 'restoreProjectManagementNavigation'));
    console.log('Admin page CSP self-check passed.');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
