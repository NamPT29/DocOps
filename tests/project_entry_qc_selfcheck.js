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
assert.match(workflowSource, /entry_qc_round2_required/, 'Must check entry_qc_round2_required');
assert.match(workflowSource, /entry_qc_round2_pending/, 'Must check entry_qc_round2_pending');
assert.match(workflowSource, /entry_qc_round2_failed/, 'Must check entry_qc_round2_failed');

assert.doesNotMatch(source, /round2\.sampled/, 'Không dùng round2.sampled');
assert.doesNotMatch(source, /round2\.items/, 'Không dùng round2.items');
assert.doesNotMatch(source, /\.checked_at\b/, 'Không dùng item.checked_at');
assert.doesNotMatch(source, /sample\.rate_percent\b/, 'Không dùng sample.rate_percent');

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
        _value: '',
        get value() {
            if (this.tagName === 'SELECT') {
                const selectedOpt = this.children.find(c => c.tagName === 'OPTION' && c.selected);
                if (selectedOpt) return selectedOpt.value;
                if (this.children.length > 0 && this.children[0].tagName === 'OPTION') return this.children[0].value;
                return '';
            }
            return this._value;
        },
        set value(v) {
            this._value = v;
            if (this.tagName === 'SELECT') {
                this.children.forEach(c => {
                    if (c.tagName === 'OPTION') c.selected = (c.value === v);
                });
            }
        },
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
        insertBefore(newNode, referenceNode) {
            const idx = this.children.indexOf(referenceNode);
            if (idx >= 0) this.children.splice(idx, 0, newNode);
            else this.children.push(newNode);
            return newNode;
        },
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
    return { ok: status >= 200 && status < 300, status, json: async () => body, blob: async () => body };
}

const body = element('body');
let confirmResult = false;
let promptResult = null;
let alertMessages = [];
let createdUrls = [];
let revokedUrls = [];

const formatter = managementSource.match(/function formatVietnamDateTime[\s\S]*?\n\}/)[0];
const authSource = fs.readFileSync('frontend/auth.js', 'utf8');
const errorFormatter = authSource.match(/function formatApiErrorDetail[\s\S]*?\n\}/)[0];

const sandbox = {
    console,
    Promise,
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
        if (route) {
            const res = route();
            if (res && res._status) return respond(res._status, res._body);
            return respond(200, res);
        }
        return respond(404, { status: 'error', detail: 'Not found' });
    },
    WORKFLOW_STATUS_LABELS: { done: 'Xong', in_progress: 'Đang xử lý', pending: 'Chờ' },
    refreshProjectWorkflow: () => { refreshCount++; },
    URL: {
        createObjectURL: (blob) => {
            const url = 'blob:test-' + Math.random();
            createdUrls.push(url);
            return url;
        },
        revokeObjectURL: (url) => {
            revokedUrls.push(url);
        }
    }
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
    routes['POST /api/projects/1/workflow/cases/2/entry-qc/resolve'] = () => ({ _status: 409, _body: { status: 'error', detail: { code: 'c', message: 'Lỗi 409' } } });
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

    assert.match(txt, /Dự kiến: Không đạt/);
    
    // --- ROUND 2 TESTS ---
    // (r2a) chưa bật
    routes = {
        'GET /api/projects/1/workflow/cases/2/entry-qc': () => ({
            status: 'ok', data: { gate: { blocked: false }, entry_qc_status: 'done', live: null, rounds: [{ round: 1, passed: true }], round2: { enabled: false } }
        })
    };
    body.replaceChildren();
    await sandbox.openEntryQc(2, 'Box 7');
    overlay = body.children[body.children.length - 1];
    txt = text(overlay);
    assert.match(txt, /Dự án không bật Check vòng 2/);
    assert.doesNotMatch(txt, /Lấy mẫu vòng 2/);
    
    // (r2b) chưa xong vòng 1
    routes = {
        'GET /api/projects/1/workflow/cases/2/entry-qc': () => ({
            status: 'ok', data: { gate: { blocked: false }, entry_qc_status: 'done', live: null, rounds: [], round2: { enabled: true, sampling: null } }
        })
    };
    body.replaceChildren();
    await sandbox.openEntryQc(2, 'Box 8');
    overlay = body.children[body.children.length - 1];
    txt = text(overlay);
    assert.match(txt, /Cần xong vòng 1 trước khi lấy mẫu/);
    assert.doesNotMatch(txt, /Lấy mẫu vòng 2/);
    
    // (r2c) lấy mẫu được (đã xong vòng 1)
    routes = {
        'GET /api/projects/1/workflow/cases/2/entry-qc': () => ({
            status: 'ok', data: { gate: { blocked: false }, entry_qc_status: 'done', live: null, rounds: [{ round: 1, passed: true }], round2: { enabled: true, sampling: null } }
        }),
        'POST /api/projects/1/workflow/cases/2/entry-qc/round2/sample': () => ({ status: 'ok', data: {} })
    };
    body.replaceChildren();
    await sandbox.openEntryQc(2, 'Box 9');
    overlay = body.children[body.children.length - 1];
    txt = text(overlay);
    assert.match(txt, /Lấy mẫu vòng 2/);
    
    let btnSample = find(overlay, n => n.tagName === 'BUTTON' && n.textContent === 'Lấy mẫu vòng 2')[0];
    confirmResult = false;
    requests.length = 0;
    await btnSample.listeners.click();
    assert.equal(requests.length, 0);
    
    confirmResult = true;
    refreshCount = 0;
    await btnSample.listeners.click();
    assert.equal(requests[0].method, 'POST');
    assert.equal(requests[0].url, '/api/projects/1/workflow/cases/2/entry-qc/round2/sample');
    assert.equal(refreshCount, 1);
    
    // (r2d) đang check dở (không có Chốt vòng 2)
    routes = {
        'GET /api/projects/1/workflow/cases/2/entry-qc': () => ({
            status: 'ok', data: { 
                gate: { blocked: false }, entry_qc_status: 'done', live: null, rounds: [{ round: 1, passed: true }], 
                round2: { enabled: true, sampling: { sample_size: 2, population_count: 10, sample_rate_percent: 20, items: [
                    { report_name: 'Rep 1', checked: false },
                    { report_name: 'Rep 2', checked: true, checked_by_name: 'Admin', changed_field_count: 1, visible_field_count: 5 }
                ] } }
            }
        })
    };
    body.replaceChildren();
    await sandbox.openEntryQc(2, 'Box 10');
    overlay = body.children[body.children.length - 1];
    txt = text(overlay);
    assert.match(txt, /Mẫu: 2\/10 phiếu \(tỷ lệ 20%\)/);
    assert.match(txt, /Chưa check/);
    assert.match(txt, /Đã check/);
    assert.match(txt, /1\/5 trường sửa/);
    assert.doesNotMatch(txt, /Chốt vòng 2/);
    
    // (r2e) đủ check chưa chốt
    routes = {
        'GET /api/projects/1/workflow/cases/2/entry-qc': () => ({
            status: 'ok', data: { 
                gate: { blocked: false }, entry_qc_status: 'done', live: null, rounds: [{ round: 1, passed: true }], 
                round2: { enabled: true, sampling: { sample_size: 2, population_count: 10, sample_rate_percent: 20, items: [
                    { report_name: 'Rep 1', checked: true, checked_by_name: 'Admin', changed_field_count: 0, visible_field_count: 5 },
                    { report_name: 'Rep 2', checked: true, checked_by_name: 'Admin', changed_field_count: 1, visible_field_count: 5 }
                ] } }
            }
        }),
        'POST /api/projects/1/workflow/cases/2/entry-qc/round2': () => ({ status: 'ok', data: {} })
    };
    body.replaceChildren();
    await sandbox.openEntryQc(2, 'Box 11');
    overlay = body.children[body.children.length - 1];
    txt = text(overlay);
    assert.match(txt, /Chốt vòng 2/);
    
    let btnR2Chot = find(overlay, n => n.tagName === 'BUTTON' && n.textContent === 'Chốt vòng 2')[0];
    confirmResult = false;
    requests.length = 0;
    await btnR2Chot.listeners.click();
    assert.equal(requests.length, 0);
    
    confirmResult = true;
    refreshCount = 0;
    await btnR2Chot.listeners.click();
    assert.equal(requests[0].method, 'POST');
    assert.equal(requests[0].url, '/api/projects/1/workflow/cases/2/entry-qc/round2');
    assert.equal(refreshCount, 1);
    
    // (r2f) vòng 2 không đạt chưa duyệt
    routes = {
        'GET /api/projects/1/workflow/cases/2/entry-qc': () => ({
            status: 'ok', data: { 
                gate: { blocked: false }, entry_qc_status: 'done', live: null, rounds: [{ round: 1, passed: true }, { round: 2, passed: false, rate_percent: 15, threshold_percent: 5 }], 
                round2: { enabled: true, sampling: { sample_size: 2, population_count: 10, sample_rate_percent: 20, items: [] } }
            }
        }),
        'POST /api/projects/1/workflow/cases/2/entry-qc/round2/resolve': () => ({ status: 'ok', data: {} })
    };
    body.replaceChildren();
    await sandbox.openEntryQc(2, 'Box 12');
    overlay = body.children[body.children.length - 1];
    txt = text(overlay);
    assert.match(txt, /Vòng 2: 15% \/ ngưỡng 5% - Không đạt/);
    assert.match(txt, /Duyệt vòng 2 kèm lý do/);
    assert.doesNotMatch(txt, /Chốt vòng 2/);
    
    let btnR2Duyet = find(overlay, n => n.tagName === 'BUTTON' && n.textContent === 'Duyệt vòng 2 kèm lý do')[0];
    promptResult = '  duyet r2  ';
    requests.length = 0;
    refreshCount = 0;
    await btnR2Duyet.listeners.click();
    assert.equal(requests[0].method, 'POST');
    assert.equal(requests[0].url, '/api/projects/1/workflow/cases/2/entry-qc/round2/resolve');
    assert.equal(requests[0].body.reason, 'duyet r2');
    assert.equal(refreshCount, 1);
    
    // (r2g) vòng 2 đã duyệt
    routes = {
        'GET /api/projects/1/workflow/cases/2/entry-qc': () => ({
            status: 'ok', data: { 
                gate: { blocked: false }, entry_qc_status: 'done', live: null, rounds: [{ round: 1, passed: true }, { round: 2, passed: false, resolution: 'approved', resolution_reason: 'OK r2' }], 
                round2: { enabled: true, sampling: { sample_size: 2, population_count: 10, sample_rate_percent: 20, items: [] } }
            }
        })
    };
    body.replaceChildren();
    await sandbox.openEntryQc(2, 'Box 13');
    overlay = body.children[body.children.length - 1];
    txt = text(overlay);
    assert.match(txt, /Lý do: OK r2/);
    assert.doesNotMatch(txt, /Duyệt vòng 2 kèm lý do/);
    
    // (r2h) vòng 2 đạt
    routes = {
        'GET /api/projects/1/workflow/cases/2/entry-qc': () => ({
            status: 'ok', data: { 
                gate: { blocked: false }, entry_qc_status: 'done', live: null, rounds: [{ round: 1, passed: true }, { round: 2, passed: true, rate_percent: 2, threshold_percent: 5 }], 
                round2: { enabled: true, sampling: { sample_size: 2, population_count: 10, sample_rate_percent: 20, items: [] } }
            }
        })
    };
    body.replaceChildren();
    await sandbox.openEntryQc(2, 'Box 14');
    overlay = body.children[body.children.length - 1];
    txt = text(overlay);
    assert.match(txt, /Vòng 2: 2% \/ ngưỡng 5% - Đạt/);
    assert.doesNotMatch(txt, /Duyệt vòng 2 kèm lý do/);

    // (r2i) test openRound2Item
    let reloadCalled = false;
    const dummyReload = async () => { reloadCalled = true; };
    createdUrls.length = 0;
    revokedUrls.length = 0;
    
    routes = {
        'GET /api/projects/1/workflow/cases/2/entry-qc/round2/items/99': () => ({
            status: 'ok', data: {
                submission_id: 99,
                report_name: 'Phieu 99',
                checked: false,
                fields: [
                    {name: 'f1', label: 'Field 1', type: 'text', value: 'old1'},
                    {name: 'f2', label: 'Field 2', type: 'dropdown', options: ['A', 'B'], value: 'C'},
                    {name: 'f3', label: 'Field 3', type: 'dropdown', options: ['X', 'Y'], value: 'Y'},
                    {name: 'f4', label: 'Field 4', type: 'dropdown', options: ['1', '2'], value: null},
                    {name: 'f5', label: 'Field 5', type: 'dropdown', options: ['M', 'N'], value: ''}
                ],
                pdf_url: '/api/pdf/99'
            }
        }),
        'GET /api/pdf/99': () => { return { _status: 200, _body: 'pdf_blob_data', blob: async () => 'pdf_blob_data', ok: true }; },
        'PUT /api/projects/1/workflow/cases/2/entry-qc/round2/items/99': () => ({ status: 'ok', data: {} })
    };
    
    await sandbox.openRound2Item(1, 2, 99, dummyReload);
    let r2Overlay = body.children[body.children.length - 1];
    let r2Txt = text(r2Overlay);
    assert.match(r2Txt, /Check vòng 2: Phieu 99/);
    assert.match(r2Txt, /Field 1/);
    assert.match(r2Txt, /Lưu kết quả check/);
    assert.equal(createdUrls.length, 1);
    
    let iframe = find(r2Overlay, n => n.tagName === 'IFRAME')[0];
    assert.ok(iframe.src.startsWith('blob:test-'));
    
    let inputs = find(r2Overlay, n => n.tagName === 'INPUT');
    let selects = find(r2Overlay, n => n.tagName === 'SELECT');
    assert.equal(inputs.length, 1);
    assert.equal(selects.length, 4);
    assert.equal(inputs[0].value, 'old1');
    
    assert.equal(selects[0].value, 'C');
    assert.equal(selects[0].children[0].value, '');
    assert.equal(selects[0].children.length, 4);
    
    assert.equal(selects[1].value, 'Y');
    assert.equal(selects[1].children[0].value, '');
    assert.equal(selects[1].children.length, 3);
    
    assert.equal(selects[2].value, '');
    assert.equal(selects[2].children[0].value, '');
    assert.equal(selects[2].children.length, 3);
    
    assert.equal(selects[3].value, '');
    assert.equal(selects[3].children[0].value, '');
    assert.equal(selects[3].children.length, 3);
    
    let btnSaveR2 = find(r2Overlay, n => n.tagName === 'BUTTON' && n.textContent === 'Lưu kết quả check')[0];
    confirmResult = false;
    requests.length = 0;
    await btnSaveR2.listeners.click();
    assert.equal(requests.length, 0);
    
    confirmResult = true;
    refreshCount = 0;
    await btnSaveR2.listeners.click();
    assert.equal(requests.length, 1);
    assert.equal(requests[0].method, 'PUT');
    assert.deepEqual(requests[0].body, { data: { f1: 'old1', f2: 'C', f3: 'Y', f4: '', f5: '' } });
    
    requests.length = 0;
    inputs[0].value = 'new1';
    selects[1].value = 'X';
    await btnSaveR2.listeners.click();
    assert.equal(requests.length, 1);
    assert.deepEqual(requests[0].body, { data: { f1: 'new1', f2: 'C', f3: 'X', f4: '', f5: '' } });
    assert.equal(reloadCalled, true);
    assert.equal(refreshCount, 2);
    
    assert.equal(revokedUrls.length, 2);
    assert.equal(revokedUrls[0], iframe.src);
    
    routes = {
        'GET /api/projects/1/workflow/cases/2/entry-qc/round2/items/100': () => ({
            status: 'ok', data: {
                submission_id: 100,
                report_name: 'Phieu 100',
                checked: true,
                checked_by_name: 'Admin',
                changed_field_count: 1,
                visible_field_count: 2,
                fields: [
                    {name: 'f1', label: 'Field 1', type: 'text', value: 'old1'}
                ],
                pdf_url: '/api/pdf/100'
            }
        }),
        'GET /api/pdf/100': () => { return { _status: 200, _body: 'pdf_blob_data', blob: async () => 'pdf_blob_data', ok: true }; }
    };
    
    await sandbox.openRound2Item(1, 2, 100, dummyReload);
    r2Overlay = body.children[body.children.length - 1];
    r2Txt = text(r2Overlay);
    assert.match(r2Txt, /Check vòng 2: Phieu 100/);
    assert.match(r2Txt, /Đã check bởi Admin: 1\/2 trường sửa/);
    assert.doesNotMatch(r2Txt, /Lưu kết quả check/);
    inputs = find(r2Overlay, n => n.tagName === 'INPUT');
    assert.equal(inputs[0].disabled, true);
    
    let btnCloseR2 = find(r2Overlay, n => n.tagName === 'BUTTON' && n.textContent === 'Đóng')[0];
    await btnCloseR2.listeners.click();
    assert.equal(revokedUrls.length, 3);
    
    routes = {
        'GET /api/projects/1/workflow/cases/2/entry-qc/round2/items/101': () => ({
            _status: 409, _body: { status: 'error', detail: { code: 'self_review', message: 'Không được tự check' } }
        })
    };
    await sandbox.openRound2Item(1, 2, 101, dummyReload);
    r2Overlay = body.children[body.children.length - 1];
    r2Txt = text(r2Overlay);
    assert.match(r2Txt, /Không được tự check/);
    assert.doesNotMatch(r2Txt, /Lưu kết quả check/);
    assert.equal(find(r2Overlay, n => n.tagName === 'INPUT').length, 0);

    console.log("All tests passed");
}
runTest().catch(error => { console.error(error); process.exitCode = 1; });
