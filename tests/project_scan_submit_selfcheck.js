// FR-SCN-01: "Nộp S" dialog. The functions are loaded with vm and executed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('frontend/js/project_scan_submit.js', 'utf8');
const workflowSource = fs.readFileSync('frontend/js/project_workflow.js', 'utf8');
const managementSource = fs.readFileSync('frontend/js/project_management.js', 'utf8');
const html = fs.readFileSync('frontend/admin.html', 'utf8');

// --- static checks ------------------------------------------------------------
assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML|document\.write/, 'Render with textContent only.');
assert.doesNotMatch(
    source,
    /function\s+formatVietnamDateTime\b|(?:var|let|const)\s+formatVietnamDateTime\b|\bformatVietnamDateTime\s*=(?!=)/,
    'Reuse the shared formatter; never redeclare it.',
);
const scripts = Array.from(html.matchAll(/<script src="([^"]+)"/g), match => match[1]);
const managementIndex = scripts.findIndex(src => src.startsWith('js/project_management.js'));
const scanIndex = scripts.indexOf('js/project_scan_submit.js?v=1.01');
assert.ok(scanIndex > managementIndex && managementIndex >= 0, 'project_scan_submit.js loads after project_management.js');
assert.ok(scripts.includes('js/project_workflow.js?v=1.06'), 'project_workflow.js version was bumped');
const ids = Array.from(html.matchAll(/\sid="([^"]+)"/g), match => match[1]);
const duplicates = ids.filter((id, index) => ids.indexOf(id) !== index);
assert.deepEqual(duplicates, [], 'Element ids in admin.html are unique.');
[
    'scanSubmitModal', 'scanSubmitModalTitle', 'scanSubmitUpButton', 'scanSubmitCurrentPath',
    'scanSubmitChooseButton', 'scanSubmitFolderList', 'scanSubmitSelectedPath', 'scanSubmitUserLevel',
    'scanSubmitSendButton', 'scanSubmitError', 'scanSubmitResult', 'scanSubmitHistory',
].forEach(id => assert.ok(ids.includes(id), `admin.html has #${id}`));
assert.match(html, /id="scanSubmitUserLevel" min="0" step="1" value="1"/);
const modalHtml = html.slice(html.indexOf('id="scanSubmitModal"'), html.indexOf('<!-- CHÍNH SÁCH DỰ ÁN'));
assert.doesNotMatch(modalHtml, /<input[^>]*type="text"/, 'No typed path: folders are picked from the list.');
assert.doesNotMatch(modalHtml, /\son[a-z]+\s*=/i, 'No inline handlers (CSP).');

// --- a small DOM --------------------------------------------------------------
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
            toggle(name, force) { if (force) classes.add(name); else classes.delete(name); },
            contains: name => classes.has(name),
        },
        append(...items) { this.children.push(...items); },
        appendChild(child) { this.children.push(child); return child; },
        replaceChildren() { this.children = []; },
        addEventListener(type, handler) { this.listeners[type] = handler; },
    };
}
const text = node => [node.textContent, ...node.children.map(text)].join(' ');
const find = (node, predicate, found = []) => {
    if (predicate(node)) found.push(node);
    node.children.forEach(child => find(child, predicate, found));
    return found;
};

const elements = {};
[
    'scanSubmitModal', 'scanSubmitModalTitle', 'scanSubmitUpButton', 'scanSubmitCurrentPath',
    'scanSubmitChooseButton', 'scanSubmitFolderList', 'scanSubmitSelectedPath', 'scanSubmitUserLevel',
    'scanSubmitSendButton', 'scanSubmitError', 'scanSubmitResult', 'scanSubmitHistory',
].forEach(id => { elements[id] = element('div'); });

const timers = [];
const requests = [];
let refreshCount = 0;
let routes = {};
function respond(status, body) {
    return { ok: status >= 200 && status < 300, status, json: async () => body };
}
const formatter = managementSource.match(/function formatVietnamDateTime[\s\S]*?\n\}/)[0];
const authSource = fs.readFileSync('frontend/auth.js', 'utf8');
const errorFormatter = authSource.match(/function formatApiErrorDetail[\s\S]*?\n\}/)[0];
const body = element('body');
let openModal = null;
const sandbox = {
    console,
    Promise,
    Intl,
    Date,
    projectWorkflowProjectId: 7,
    document: {
        body,
        getElementById: id => elements[id] || null,
        createElement: tag => element(tag),
        querySelector: selector => (selector === '.modal.show' ? openModal : null),
    },
    bootstrap: { Modal: class { show() { requests.push({ url: 'modal:show' }); } } },
    setTimeout(callback) { timers.push(callback); return timers.length; },
    clearTimeout(handle) { timers[handle - 1] = null; },
    async authFetch(url, options = {}) {
        requests.push({ url, method: options.method || 'GET', body: options.body });
        const route = Object.keys(routes).find(prefix => url.startsWith(prefix));
        const handler = route && routes[route].handler;
        return handler ? handler(url, options) : respond(404, { detail: 'not found' });
    },
    async refreshProjectWorkflow() { refreshCount += 1; },
};
vm.createContext(sandbox);
vm.runInContext(`${formatter}\n${errorFormatter}\n${source}`, sandbox);

async function flush() {
    // Let every pending await chain (fetch -> json -> render) settle.
    for (let i = 0; i < 5; i += 1) await new Promise(resolve => setImmediate(resolve));
}
async function runTimers() {
    while (timers.some(Boolean)) {
        const index = timers.findIndex(Boolean);
        const callback = timers[index];
        timers[index] = null;
        await callback();
        await flush();
    }
}

(async () => {
    // scanSubmitCanSubmit: open Scan, Check scan still pending (or not enabled);
    // a waiting or returned box also needs its previous stage done.
    const can = (scan, qc, available) => sandbox.scanSubmitCanSubmit(
        scan === undefined ? undefined : { status: scan, ...(available === undefined ? {} : { available }) },
        qc === undefined ? undefined : { status: qc },
    );
    for (const scan of ['pending', 'rejected', 'in_progress']) {
        for (const available of [undefined, true]) {
            assert.equal(can(scan, undefined, available), true, `${scan} without scan_qc`);
            assert.equal(can(scan, 'pending', available), true, `${scan} with scan_qc pending`);
            assert.equal(can(scan, 'in_progress', available), false, `${scan} with scan_qc in progress`);
            assert.equal(can(scan, 'done', available), false);
            assert.equal(can(scan, 'rejected', available), false);
        }
    }
    assert.equal(can('pending', 'pending', false), false, 'pending but previous stage not done');
    assert.equal(can('rejected', undefined, false), false, 'rejected but previous stage reopened');
    assert.equal(can('in_progress', 'pending', false), true, 'in_progress always accepts another package');
    assert.equal(can('in_progress', 'in_progress', false), false);
    assert.equal(can('done', undefined), false);
    assert.equal(can('done', 'pending', true), false);
    assert.equal(sandbox.scanSubmitCanSubmit(undefined, undefined), false, 'Scan not enabled');
    assert.equal(sandbox.scanSubmitCanSubmit({ status: 'pending' }, {}), true, 'scan_qc without status = pending');

    // Error text: {code, message} shows the message, everything else the shared formatter.
    assert.equal(sandbox.scanSubmitErrorText({ detail: 'Hộp không tồn tại.' }), 'Hộp không tồn tại.');
    assert.equal(
        sandbox.scanSubmitErrorText({ detail: { code: 'stage_blocked', message: 'Bước trước chưa hoàn tất' } }),
        'Bước trước chưa hoàn tất',
    );
    assert.equal(
        sandbox.scanSubmitErrorText({ detail: [{ loc: ['body', 'folder_path'], msg: 'Field required' }] }),
        'folder_path: Field required',
    );
    assert.equal(sandbox.scanSubmitErrorText({ message: 'Lỗi máy chủ' }), 'Lỗi máy chủ');
    assert.equal(sandbox.scanSubmitErrorText({}, 'Không nộp được gói scan.'), 'Không nộp được gói scan.');
    assert.equal(sandbox.scanSubmitErrorText(null), 'Không thực hiện được thao tác.');
    assert.equal(sandbox.scanSubmitErrorText({ detail: { code: 'x' } }), '{"code":"x"}', 'object without message');

    // Without injected timers the poller must call setTimeout as a plain
    // function: browsers throw "Illegal invocation" for any other receiver.
    const browserQueue = [];
    const browser = { console, Promise };
    function browserSetTimeout(callback) {
        'use strict';
        if (this !== undefined && this !== browser && this !== browserGlobal) {
            throw new TypeError('Illegal invocation');
        }
        browserQueue.push(callback);
        return browserQueue.length;
    }
    function browserClearTimeout(handle) {
        'use strict';
        if (this !== undefined && this !== browser && this !== browserGlobal) {
            throw new TypeError('Illegal invocation');
        }
        browserQueue[handle - 1] = null;
    }
    browser.setTimeout = browserSetTimeout;
    browser.clearTimeout = browserClearTimeout;
    vm.createContext(browser);
    const browserGlobal = vm.runInContext('globalThis', browser);
    vm.runInContext(source, browser);
    const answers = ['processing', 'processing', 'done'];
    let browserFetches = 0;
    const unhandled = [];
    const onUnhandled = reason => unhandled.push(reason);
    process.on('unhandledRejection', onUnhandled);
    const browserPoller = browser.scanSubmitStartPolling(async () => {
        browserFetches += 1;
        return { status: answers.shift() };
    }, () => {});
    await flush();
    while (browserQueue.some(Boolean)) {
        const index = browserQueue.findIndex(Boolean);
        const callback = browserQueue[index];
        browserQueue[index] = null;
        await callback();
        await flush();
    }
    process.off('unhandledRejection', onUnhandled);
    assert.deepEqual(unhandled.map(String), [], 'no Illegal invocation while polling');
    assert.equal(browserFetches, 3, 'polling keeps running until the package is done');
    assert.equal((await browserPoller.done).status, 'done');

    // Warning labels.
    assert.deepEqual(
        Array.from(sandbox.scanWarningLabels(['missing_scan_user', 'incomplete_files', 'error_files', 'non_pdf_files', 'la_co_moi'])),
        ['Chưa có tên người scan', 'Có file đang chép dở', 'Có file lỗi (cụt/mã hóa)', 'Có file không phải PDF', 'la_co_moi'],
    );
    assert.deepEqual(Array.from(sandbox.scanWarningLabels([])), []);
    assert.deepEqual(Array.from(sandbox.scanWarningLabels(null)), []);
    const doneWithFailures = Array.from(sandbox.scanPackageWarnings({ status: 'done', failed_files: 2, warning_flags: ['error_files'] }));
    assert.equal(doneWithFailures[0], 'Có file lỗi (cụt/mã hóa)');
    assert.match(doneWithFailures[1], /2 file không đọc được/);
    assert.deepEqual(Array.from(sandbox.scanPackageWarnings({ status: 'done', failed_files: 0, warning_flags: [] })), []);

    // Progress.
    assert.equal(sandbox.scanSubmitProgress({ total_files: 4, processed_files: 2, failed_files: 1 }).text, '3/4 file (75%)');
    assert.equal(sandbox.scanSubmitProgress({ total_files: 0, processed_files: 0, failed_files: 0 }).percent, 0);
    assert.equal(sandbox.scanSubmitProgress({}).text, '0/0 file (0%)');

    // Naive UTC from the API is shown in Vietnam time by the shared formatter.
    assert.equal(sandbox.scanSubmitTime('2026-10-05T03:00:00'), '2026-10-05 10:00');
    assert.equal(sandbox.scanSubmitTime('2026-10-05T03:00:00+00:00'), '2026-10-05 10:00');
    assert.equal(sandbox.scanSubmitTime(null), '');

    // Polling: stops on done, on failed, and when cancelled; survives a fetch error.
    const fakeTimers = { setTimeout: sandbox.setTimeout, clearTimeout: sandbox.clearTimeout };
    for (const final of ['done', 'failed']) {
        const answers = [new Error('mạng chập chờn'), { status: 'processing' }, { status: final }];
        const updates = [];
        const poller = sandbox.scanSubmitStartPolling(async () => {
            const next = answers.shift();
            if (next instanceof Error) throw next;
            return next;
        }, pkg => updates.push(pkg.status), fakeTimers, 2000);
        await flush();
        await runTimers();
        assert.equal((await poller.done).status, final);
        assert.deepEqual(updates, ['processing', final]);
        assert.equal(timers.filter(Boolean).length, 0, `no timer left after ${final}`);
    }
    let calls = 0;
    const cancelled = sandbox.scanSubmitStartPolling(async () => { calls += 1; return { status: 'processing' }; }, () => {}, fakeTimers, 2000);
    await flush();
    cancelled.stop();
    assert.equal(await cancelled.done, null);
    await runTimers();
    assert.equal(calls, 1, 'no request after stop()');

    // Opening the dialog lists the server folders and the box history.
    const base = '/api/projects/7/cases/3/scan-packages';
    const packages = [];
    routes = {
        '/api/documents/server-folders': {
            handler: url => respond(200, {
                status: 'ok',
                current_relative_path: decodeURIComponent(url.split('path=')[1] || ''),
                parent_relative_path: url.endsWith('path=') ? null : '',
                directories: url.endsWith('path=') ? [{ name: 'Hộp 01', relative_path: 'Hộp 01' }] : [],
            }),
        },
        [base]: { handler: () => respond(200, { status: 'ok', data: packages.slice() }) },
    };
    await sandbox.openScanSubmit(3, 'Hộp 01');
    assert.equal(elements.scanSubmitModalTitle.textContent, 'Hộp 01');
    assert.equal(elements.scanSubmitUserLevel.value, '1');
    assert.equal(elements.scanSubmitSendButton.disabled, true, 'nothing chosen yet');
    assert.equal(elements.scanSubmitUpButton.disabled, true, 'already at the root');
    assert.match(text(elements.scanSubmitHistory), /chưa nộp gói scan nào/);

    // Enter "Hộp 01" and choose it.
    const folderButton = find(elements.scanSubmitFolderList, node => node.tagName === 'BUTTON')[0];
    await folderButton.listeners.click();
    assert.equal(elements.scanSubmitCurrentPath.textContent, 'Hộp 01');
    elements.scanSubmitChooseButton.listeners.click();
    assert.match(elements.scanSubmitSelectedPath.textContent, /Đã chọn: Hộp 01/);
    assert.equal(elements.scanSubmitSendButton.disabled, false);

    // A refused submission shows the server's detail verbatim.
    routes = { ...routes, [base]: { handler: (url, options) => (options.method === 'POST'
        ? respond(409, { detail: 'Bước Kiểm tra scan đã bắt đầu, không thể nộp thêm gói.' })
        : respond(200, { status: 'ok', data: packages.slice() })) } };
    elements.scanSubmitUserLevel.value = '2';
    await elements.scanSubmitSendButton.listeners.click();
    assert.equal(elements.scanSubmitError.textContent, 'Bước Kiểm tra scan đã bắt đầu, không thể nộp thêm gói.');
    assert.equal(elements.scanSubmitError.classList.contains('d-none'), false);
    const refused = requests.filter(r => r.method === 'POST').pop();
    assert.deepEqual(JSON.parse(refused.body), { folder_path: 'Hộp 01', scan_user_name_level: 2 });

    // A good submission is followed until done, then the pipeline refreshes.
    const states = [
        { id: 41, version: 1, status: 'processing', scanned_by_name: null, total_files: 4, processed_files: 1, failed_files: 0, warning_flags: ['missing_scan_user'] },
        { id: 41, version: 1, status: 'done', scanned_by_name: null, total_files: 4, processed_files: 3, failed_files: 1, total_pages: 12, total_a4_equivalent: 14, warning_flags: ['missing_scan_user', 'error_files'], finished_at: '2026-10-05T03:00:00' },
    ];
    routes = { [base]: { handler: (url, options) => {
        if (options.method === 'POST') return respond(200, { status: 'ok', package_id: 41 });
        return respond(200, { status: 'ok', data: [states[0]] });
    } } };
    const sending = elements.scanSubmitSendButton.listeners.click();
    await flush();
    assert.match(text(elements.scanSubmitResult), /S1 – Đang xử lý/);
    assert.match(text(elements.scanSubmitResult), /Tiến độ: 1\/4 file \(25%\)/);
    states.shift();
    await runTimers();
    await sending;
    const result = text(elements.scanSubmitResult);
    assert.match(result, /S1 – Xong/);
    assert.match(result, /Người scan: chưa có tên/);
    assert.match(result, /12 trang, 14 trang A4 quy đổi/);
    assert.match(result, /Lúc: 2026-10-05 10:00/);
    assert.match(result, /Chưa có tên người scan/);
    assert.match(result, /1 file không đọc được/);
    assert.equal(refreshCount, 1, 'refreshProjectWorkflow() after the package finished');
    assert.match(text(elements.scanSubmitHistory), /S1 – Xong/);

    // A failed package shows its error in red.
    const failedBox = element('div');
    sandbox.renderScanPackage(failedBox, { version: 2, status: 'failed', error_message: 'Thư viện pypdf chưa được cài đặt.', warning_flags: [] });
    const red = find(failedBox, node => node.className.includes('text-danger'))[0];
    assert.equal(red.textContent, 'Thư viện pypdf chưa được cài đặt.');

    // Closing the dialog stops polling.
    routes = { [base]: { handler: (url, options) => (options.method === 'POST'
        ? respond(200, { status: 'ok', package_id: 42 })
        : respond(200, { status: 'ok', data: [{ id: 42, version: 2, status: 'processing', total_files: 1, processed_files: 0, failed_files: 0 }] })) } };
    const pending = elements.scanSubmitSendButton.listeners.click();
    await flush();
    elements.scanSubmitModal.listeners['hidden.bs.modal']();
    await pending;
    const before = requests.length;
    await runTimers();
    assert.equal(requests.length, before, 'no polling after the dialog closed');
    assert.equal(body.classList.contains('modal-open'), false, 'no other dialog: body untouched');

    // Closing it over the still-open pipeline dialog keeps body.modal-open.
    openModal = element('div');
    elements.scanSubmitModal.listeners['hidden.bs.modal']();
    assert.equal(body.classList.contains('modal-open'), true);
    openModal = null;

    // The pipeline table offers "Nộp S" only where it is allowed.
    const tableElements = { workflowCasesHead: element('thead'), workflowCasesBody: element('tbody') };
    const page = {
        console,
        document: { getElementById: id => tableElements[id] || null, createElement: tag => element(tag) },
        scanSubmitCanSubmit: sandbox.scanSubmitCanSubmit,
        openScanSubmit(caseId, name) { page.opened = [caseId, name]; },
    };
    vm.createContext(page);
    vm.runInContext(`${workflowSource}\nthis.__render = renderWorkflowCases; this.__setConfig = c => { projectWorkflowConfig = c; };`, page);
    page.__setConfig({ stages: [{ key: 'scan', label: 'Scan', kind: 'work' }, { key: 'scan_qc', label: 'Check scan', kind: 'qc' }] });
    page.__render({
        enabled_stages: ['scan', 'scan_qc'],
        items: [
            { case_id: 1, display_name: 'Hộp 1', case_key: 'a', stages: { scan: { status: 'pending', available: true }, scan_qc: { status: 'pending' } } },
            { case_id: 2, display_name: 'Hộp 2', case_key: 'b', stages: { scan: { status: 'in_progress', available: true }, scan_qc: { status: 'in_progress' } } },
            { case_id: 3, display_name: 'Hộp 3', case_key: 'c', stages: { scan: { status: 'done', available: true }, scan_qc: { status: 'pending' } } },
        ],
    });
    const rows = tableElements.workflowCasesBody.children;
    const hasSubmit = row => find(row, node => node.tagName === 'BUTTON' && node.textContent === 'Nộp S').length > 0;
    assert.deepEqual(rows.map(hasSubmit), [true, false, false]);
    find(rows[0], node => node.textContent === 'Nộp S')[0].listeners.click();
    assert.deepEqual(page.opened, [1, 'Hộp 1']);

    console.log('Project scan submit self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
