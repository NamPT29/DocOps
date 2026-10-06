const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('frontend/js/project_entry_qc.js', 'utf8');
const workflowSource = fs.readFileSync('frontend/js/project_workflow.js', 'utf8');
const managementSource = fs.readFileSync('frontend/js/project_management.js', 'utf8');
const html = fs.readFileSync('frontend/admin.html', 'utf8');

// --- static checks ---
assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML|document\.write/, 'Render with textContent only.');
assert.doesNotMatch(
    source,
    /function\s+formatVietnamDateTime\b|(?:var|let|const)\s+formatVietnamDateTime\b|\bformatVietnamDateTime\s*=(?!=)/,
    'Reuse the shared formatter; never redeclare it.',
);

const scripts = Array.from(html.matchAll(/<script src="([^"]+)"/g), match => match[1]);
const entryIndex = scripts.findIndex(src => /^js\/project_entry_qc\.js\?v=[\d.]+$/.test(src));
const workflowIndex = scripts.findIndex(src => /^js\/project_workflow\.js\?v=[\d.]+$/.test(src));
assert.ok(entryIndex > workflowIndex && workflowIndex >= 0, 'project_entry_qc.js loads after project_workflow.js');
assert.ok(scripts.some(src => /^js\/project_workflow\.js\?v=[\d.]+$/.test(src)), 'project_workflow.js version check');

assert.match(workflowSource, /typeof openEntryQc === 'function'/, 'Check nhập button is rendered for entry_qc column');

// --- a small DOM ---
function element(tag) {
    const classes = new Set();
    return {
        tagName: String(tag).toUpperCase(),
        className: '',
        textContent: '',
        children: [],
        listeners: {},
        dataset: {},
        disabled: false,
        value: '',
        classList: {
            add: name => classes.add(name),
            remove: name => classes.delete(name),
            toggle(name, force) { if (force) classes.add(name); else classes.delete(name); },
            contains: name => classes.has(name),
        },
        style: {},
        setAttribute(name, value) { this[name] = value; },
        append(...items) { this.children.push(...items); },
        appendChild(child) { this.children.push(child); return child; },
        replaceChildren() { this.children = []; },
        addEventListener(type, handler) { this.listeners[type] = handler; },
        remove() {},
    };
}

const text = node => {
    if (typeof node === 'string') return node;
    if (node.nodeType === 3) return node.textContent; // Text node mock
    return [node.textContent, ...node.children.map(text)].join(' ');
};

const find = (node, predicate, found = []) => {
    if (predicate(node)) found.push(node);
    if (node.children) node.children.forEach(child => find(child, predicate, found));
    return found;
};

const requests = [];
let routes = {};
function respond(status, body) {
    return { ok: status >= 200 && status < 300, status, json: async () => body };
}

const body = element('body');
let confirmResult = false;
let promptResult = null;
let alertMessages = [];

const formatter = managementSource.match(/function formatVietnamDateTime[\s\S]*?\n\}/)[0];
const authSource = fs.readFileSync('frontend/auth.js', 'utf8');
const errorFormatter = authSource.match(/function formatApiErrorDetail[\s\S]*?\n\}/)[0];

const sandbox = {
    console,
    Promise,
    Intl,
    Date,
    projectWorkflowProjectId: 1,
    document: {
        body,
        createElement: tag => element(tag),
        createTextNode: txt => ({ nodeType: 3, textContent: txt, children: [] })
    },
    window: {
        confirm: msg => confirmResult,
        prompt: msg => promptResult,
        alert: msg => alertMessages.push(msg)
    },
    async authFetch(url, options = {}) {
        const bodyStr = options.body ? JSON.parse(options.body) : null;
        requests.push({ url, method: options.method || 'GET', body: bodyStr });
        const route = routes[`${options.method || 'GET'} ${url}`] || routes[`GET ${url}`];
        if (route) return respond(200, route());
        return respond(404, { status: 'error', detail: 'Not found' });
    },
    WORKFLOW_STATUS_LABELS: { done: 'Xong', in_progress: 'Đang xử lý', pending: 'Chờ' },
    refreshProjectWorkflow: () => { requests.push({ url: 'refresh' }); },
};
sandbox.scanSubmitErrorText = (data, fallback) => data && data.detail && data.detail.message ? data.detail.message : fallback;
vm.runInNewContext(formatter + '\n' + errorFormatter + '\n' + source, sandbox);

async function runTest() {
    // (a) status done, chưa chốt -> có 'Chốt vòng 1'
    routes = {
        'GET /api/projects/1/workflow/cases/2/entry-qc': () => ({
            status: 'ok', data: { gate: { blocked: false }, entry_qc_status: 'done', live: null, rounds: [] }
        }),
        'POST /api/projects/1/workflow/cases/2/entry-qc/round1': () => ({ status: 'ok', data: {} })
    };
    await sandbox.openEntryQc(2, 'Box 1');
    let overlay = body.children[body.children.length - 1];
    let txt = text(overlay);
    assert.match(txt, /Xong/, 'Has status done');
    assert.match(txt, /Chốt vòng 1/, 'Has button Chốt vòng 1');
    assert.doesNotMatch(txt, /Duyệt kèm lý do/);
    
    // click chot, confirm = false -> no POST
    confirmResult = false;
    let btnChot = find(overlay, n => n.tagName === 'BUTTON' && n.textContent === 'Chốt vòng 1')[0];
    requests.length = 0;
    await btnChot.listeners.click();
    assert.equal(requests.length, 0, 'No API call if confirm false');
    
    
    let refreshCount = 0;
    sandbox.refreshProjectWorkflow = () => { refreshCount++; };

    // click chot, confirm = true -> POST
    confirmResult = true;
    await btnChot.listeners.click();
    assert.equal(requests[0].method, 'POST');
    assert.equal(requests[0].url, '/api/projects/1/workflow/cases/2/entry-qc/round1');
    assert.equal(refreshCount, 1);

    // (b) status in_progress, chưa chốt -> không có nút nào
    routes = {
        'GET /api/projects/1/workflow/cases/2/entry-qc': () => ({
            status: 'ok', data: { gate: { blocked: false }, entry_qc_status: 'in_progress', live: null, rounds: [] }
        })
    };
    body.replaceChildren();
    await sandbox.openEntryQc(2, 'Box 2');
    overlay = body.children[body.children.length - 1];
    txt = text(overlay);
    assert.doesNotMatch(txt, /Chốt vòng 1/);
    assert.doesNotMatch(txt, /Duyệt kèm lý do/);

    // (c) vòng 1 không đạt, chưa duyệt -> có 'Duyệt kèm lý do' + cảnh báo gate
    routes = {
        'GET /api/projects/1/workflow/cases/2/entry-qc': () => ({
            status: 'ok', data: { 
                gate: { blocked: true, message: 'Gate is blocked' }, 
                entry_qc_status: 'done', 
                live: null, 
                rounds: [{ round: 1, passed: false, rate_percent: 10, threshold_percent: 5 }] 
            }
        }),
        'POST /api/projects/1/workflow/cases/2/entry-qc/resolve': () => ({ status: 'ok', data: {} })
    };
    body.replaceChildren();
    await sandbox.openEntryQc(2, 'Box 3');
    overlay = body.children[body.children.length - 1];
    txt = text(overlay);
    assert.doesNotMatch(txt, /Chốt vòng 1/);
    assert.match(txt, /Duyệt kèm lý do/);
    assert.match(txt, /Gate is blocked/);
    
    // prompt empty or null -> no POST
    let btnDuyet = find(overlay, n => n.tagName === 'BUTTON' && n.textContent === 'Duyệt kèm lý do')[0];
    promptResult = '   ';
    requests.length = 0;
    await btnDuyet.listeners.click();
    assert.equal(requests.length, 0);
    
    // prompt > 500 chars -> no POST
    promptResult = 'a'.repeat(501);
    alertMessages = [];
    await btnDuyet.listeners.click();
    assert.equal(requests.length, 0);
    assert.ok(alertMessages.some(m => m.includes('tối đa 500')), 'Alert length');
    
    // valid prompt -> POST
    promptResult = '  valid reason  ';
    refreshCount = 0;
    await btnDuyet.listeners.click();
    assert.equal(requests[0].method, 'POST');
    assert.equal(requests[0].url, '/api/projects/1/workflow/cases/2/entry-qc/resolve');
    assert.equal(requests[0].body.reason, 'valid reason');
    assert.equal(refreshCount, 1);
    
    // 409 error
    routes['POST /api/projects/1/workflow/cases/2/entry-qc/resolve'] = () => ({ status: 'error', detail: { code: 'c', message: 'Lỗi 409' } });
    sandbox.authFetch = async (url, opts) => {
        if (opts && opts.method === 'POST') return respond(409, routes['POST /api/projects/1/workflow/cases/2/entry-qc/resolve']());
        return respond(200, routes['GET /api/projects/1/workflow/cases/2/entry-qc']());
    };
    promptResult = 'valid';
    refreshCount = 0;
    await btnDuyet.listeners.click();
    txt = text(overlay);
    assert.match(txt, /Lỗi 409/);
    assert.equal(refreshCount, 0);

    // (d) đã duyệt -> hiện lý do, không nút
    routes = {
        'GET /api/projects/1/workflow/cases/2/entry-qc': () => ({
            status: 'ok', data: { 
                gate: { blocked: false }, 
                entry_qc_status: 'done', 
                live: null, 
                rounds: [{ round: 1, passed: false, resolution: 'approved', resolution_reason: 'OK la' }] 
            }
        })
    };
    sandbox.authFetch = async (url) => respond(200, routes['GET /api/projects/1/workflow/cases/2/entry-qc']());
    body.replaceChildren();
    await sandbox.openEntryQc(2, 'Box 4');
    overlay = body.children[body.children.length - 1];
    txt = text(overlay);
    assert.doesNotMatch(txt, /Chốt vòng 1/);
    assert.doesNotMatch(txt, /Duyệt kèm lý do/);
    assert.match(txt, /Lý do: OK la/);
    
    // (e) vòng 1 đạt -> không có 'Duyệt kèm lý do'
    routes = {
        'GET /api/projects/1/workflow/cases/2/entry-qc': () => ({
            status: 'ok', data: { 
                gate: { blocked: false }, 
                entry_qc_status: 'done', 
                live: null, 
                rounds: [{ round: 1, passed: true }] 
            }
        })
    };
    body.replaceChildren();
    await sandbox.openEntryQc(2, 'Box 5');
    overlay = body.children[body.children.length - 1];
    txt = text(overlay);
    assert.doesNotMatch(txt, /Chốt vòng 1/);
    assert.doesNotMatch(txt, /Duyệt kèm lý do/);
    // edge case (f) rate 5, threshold 5, would_pass false
    routes = {
        'GET /api/projects/1/workflow/cases/2/entry-qc': () => ({
            status: 'ok', data: { 
                gate: { blocked: false }, 
                entry_qc_status: 'done', 
                live: { reports_total: 10, reports_assessed: 10, error_reports: 2, total_fields: 100, error_fields: 5, rate_percent: 5, threshold_percent: 5, would_pass: false }, 
                rounds: [] 
            }
        })
    };
    body.replaceChildren();
    await sandbox.openEntryQc(2, 'Box 6');
    overlay = body.children[body.children.length - 1];
    txt = text(overlay);
    assert.match(txt, /Dự kiến: Không đạt/);

    console.log("All tests passed");
}
runTest().catch(error => { console.error(error); process.exitCode = 1; });
