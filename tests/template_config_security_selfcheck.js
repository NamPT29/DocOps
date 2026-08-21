const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

function escapeHTML(value) {
    return String(value || '').replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[char]);
}

async function checkAuthTemplateRendering() {
    const maliciousName = "x');alert(1);//<img src=x onerror=alert(2)>";
    const tbody = { innerHTML: '' };
    const select = {
        children: [],
        replaceChildren() { this.children = []; },
        appendChild(child) { this.children.push(child); },
    };
    const container = { style: {} };
    const sandbox = {
        console,
        escapeHTML,
        alert(message) { throw new Error(message); },
        fetch: async () => ({
            status: 200,
            json: async () => ({
                status: 'ok',
                data: [{ id: 3, name: maliciousName, filename: maliciousName }],
            }),
        }),
        localStorage: { getItem() { return null; } },
        window: { location: { pathname: '/login.html', href: '' } },
        document: {
            addEventListener() {},
            getElementById(id) {
                if (id === 'templatesTableBody') return tbody;
                if (id === 'templateSelect') return select;
                if (id === 'templateSelectContainer') return container;
                return null;
            },
            createElement() { return { value: '', textContent: '' }; },
        },
    };
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync('frontend/auth.js', 'utf8'), sandbox);

    await vm.runInContext('fetchAdminTemplates()', sandbox);
    assert(tbody.innerHTML.includes('%27'));
    assert(!tbody.innerHTML.includes("decodeURIComponent('x');alert"));
    assert(tbody.innerHTML.includes('&lt;img'));

    await vm.runInContext('populateTemplateDropdown()', sandbox);
    assert.equal(select.children[1].textContent, maliciousName);
}

async function checkTemplateConfigRendering() {
    const controls = ['roColSelect', 'dateColSelect', 'yearColSelect', 'hiddenColSelect', 'placeholderColSelect'];
    const elements = Object.fromEntries(controls.map(id => [id, {
        innerHTML: '',
        querySelectorAll() { return []; },
    }]));
    elements.dictRulesBody = { innerHTML: '' };
    elements.syncRulesList = { innerHTML: '' };
    elements.concatRulesList = { innerHTML: '' };
    elements.dictionaryItemsTableBody = { innerHTML: '' };
    const colSelect = {
        innerHTML: '',
        querySelector() { return { textContent: '<img src=x>' }; },
    };
    const dictSelect = {
        innerHTML: '',
        querySelector() { return { textContent: '<svg onload=x>' }; },
    };
    const sandbox = {
        console,
        escapeHTML,
        document: {
            getElementById(id) { return elements[id] || null; },
            querySelectorAll(selector) {
                if (selector === '.col-dropdown') return [colSelect];
                if (selector === '.dict-dropdown') return [dictSelect];
                return [];
            },
        },
        apiCall: async () => ({
            data: [{ id: 8, code: '<img src=x>', value: '<script>x()</script>' }],
        }),
    };
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync('frontend/js/template_config.js', 'utf8'), sandbox);
    vm.runInContext(`
        templateFields = [{ col: 1, label: '<img src=x onerror=x>' }];
        allDictionaries = [{ name: '<script>x()</script>', description: '<svg onload=x>' }];
        currentConfigObj = {
            dropdown_rules: [{ col: 1, dictionary: '<img src=x>', extract_mode: 'left' }],
            sync_cols: [{ source: 1, target: 1 }],
            concat_rules: [{ source_1: 1, source_2: 1, target: 1 }],
        };
        populateColDropdowns();
        populateDictDropdowns();
        renderVisualUiFromJSON();
    `, sandbox);

    assert(!elements.roColSelect.innerHTML.includes('<img src=x'));
    assert(!elements.hiddenColSelect.innerHTML.includes('<img src=x'));
    assert(!elements.placeholderColSelect.innerHTML.includes('<img src=x'));
    assert(!colSelect.innerHTML.includes('<img src=x'));
    assert(!dictSelect.innerHTML.includes('<script>'));
    assert(!elements.dictRulesBody.innerHTML.includes('<img src=x>'));

    await vm.runInContext('currentDictId = 1; fetchDictionaryItems()', sandbox);
    assert(!elements.dictionaryItemsTableBody.innerHTML.includes('<script>'));
    assert(elements.dictionaryItemsTableBody.innerHTML.includes('&lt;script&gt;'));
}

Promise.all([checkAuthTemplateRendering(), checkTemplateConfigRendering()])
    .then(() => console.log('Template/config security self-check: OK'))
    .catch(error => {
        console.error(error);
        process.exitCode = 1;
    });
