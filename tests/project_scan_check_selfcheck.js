// Check scan (lát CS1): màn hai cột, cột trái hồ sơ/file, cột phải trang PDF. Chạy hàm thật bằng vm.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('frontend/js/project_scan_submit.js', 'utf8');
const authSource = fs.readFileSync('frontend/auth.js', 'utf8');
const errorFormatter = authSource.match(/function formatApiErrorDetail[\s\S]*?\n\}/)[0];

// --- static checks ------------------------------------------------------------
assert.doesNotMatch(source, /innerHTML|insertAdjacentHTML|document\.write/, 'Render with textContent only.');
for (const page of ['frontend/admin.html', 'frontend/index.html']) {
    const html = fs.readFileSync(page, 'utf8');
    const tags = html.match(/<script src="js\/project_scan_submit\.js\?v=[\d.]+"><\/script>/g) || [];
    assert.equal(tags.length, 1, `${page} nạp project_scan_submit.js đúng một lần`);
    assert.match(tags[0], /\?v=1\.07"/, `${page} nâng ?v= của project_scan_submit.js`);
}

function withTimeout(promise, message, ms = 1500) {
    let timer;
    return Promise.race([
        promise,
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`Treo: ${message}`)), ms); }),
    ]).finally(() => clearTimeout(timer));
}

// --- a small DOM --------------------------------------------------------------
function element(tag) {
    const classes = new Set();
    const node = {
        tagName: String(tag).toUpperCase(),
        className: '',
        textContent: '',
        children: [],
        listeners: {},
        dataset: {},
        style: {},
        disabled: false,
        type: '',
        removed: false,
        parent: null,
        classList: {
            add: name => classes.add(name),
            toggle(name, force) { if (force) classes.add(name); else classes.delete(name); },
            contains: name => classes.has(name),
        },
        append(...items) { items.forEach(item => this.appendChild(item)); },
        appendChild(child) { child.parent = this; this.children.push(child); return child; },
        replaceChildren(...items) { this.children = []; items.forEach(item => this.appendChild(item)); },
        addEventListener(type, handler) { this.listeners[type] = handler; },
        remove() {
            this.removed = true;
            if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this);
        },
        value: '',
        getContext() {
            if (!this.ctx) {
                const calls = [];
                this.ctx = { calls };
                ['clearRect', 'beginPath', 'moveTo', 'lineTo', 'stroke'].forEach(name => {
                    this.ctx[name] = (...args) => calls.push([name, ...args]);
                });
            }
            return this.ctx;
        },
        getBoundingClientRect: () => ({ left: 100, top: 50, width: 200, height: 300 }),
    };
    return node;
}
const text = node => [node.textContent, ...node.children.map(text)].join(' ');
const find = (node, predicate, found = []) => {
    if (predicate(node)) found.push(node);
    node.children.forEach(child => find(child, predicate, found));
    return found;
};
const byText = (root, tag, wanted) => find(root, node => node.tagName === tag && text(node).includes(wanted));

// --- fake server and PDF.js -----------------------------------------------------
const requests = [];
const posts = [];
let routes = [];
function respond(status, body) {
    return { ok: status >= 200 && status < 300, status, json: async () => body, arrayBuffer: async () => new ArrayBuffer(4) };
}
function pdfResponse(pages, sha = 'sha-a') {
    const buffer = new ArrayBuffer(1);
    new Uint8Array(buffer)[0] = pages;
    return {
        ok: true,
        status: 200,
        headers: { get: name => (name === 'X-Scan-File-Sha256' ? sha : null) },
        json: async () => ({}),
        arrayBuffer: async () => buffer,
    };
}
const rendered = [];
let holdRender = null;
const fakePdfjs = {
    GlobalWorkerOptions: {},
    getDocument({ data }) {
        const numPages = data[0];
        return {
            promise: Promise.resolve({
                numPages,
                getPage: async number => ({
                    getViewport: ({ scale }) => ({ width: 600 * scale, height: 840 * scale }),
                    render: () => {
                        rendered.push(number);
                        const hold = holdRender;
                        holdRender = null;
                        return { promise: hold || Promise.resolve() };
                    },
                }),
            }),
        };
    },
};

const body = element('body');
const alerts = [];
const confirms = [];
let confirmAnswer = true;
const sandbox = {
    console,
    Promise,
    Uint8Array,
    Map,
    Set,
    projectWorkflowProjectId: 7,
    alert: message => alerts.push(message),
    confirm: message => { confirms.push(message); return confirmAnswer; },
    JSON,
    document: {
        body,
        getElementById: () => null,
        createElement: tag => element(tag),
    },
    setTimeout,
    clearTimeout,
    async authFetch(url, options = {}) {
        requests.push(url);
        if (options.method === 'POST') posts.push({ url, body: JSON.parse(options.body) });
        const route = routes.find(([prefix]) => url === prefix);
        return route ? route[1](url, options) : respond(404, { detail: 'Không tìm thấy' });
    },
};
vm.createContext(sandbox);
vm.runInContext(`${errorFormatter}\n${source}`, sandbox);
sandbox.scanCheckState.pdfjs = Promise.resolve(fakePdfjs);

const base = '/api/projects/7/cases/4/scan-packages';
const view = {
    package: { id: 9, version: 2, status: 'done' },
    dossiers: [
        {
            folder: '01', sheets: 3, min_pages: 4, max_pages: 7, pages: 5, status: 'ok', has_cover: true,
            files: [
                { id: 10, name: 'BIA.pdf', relative_path: '01/BIA.pdf', page_count: 1, status: 'ok', is_pdf: true, is_cover: true },
                { id: 11, name: '1.pdf', relative_path: '01/1.pdf', page_count: 2, status: 'ok', is_pdf: true, is_cover: false },
                { id: 12, name: 'Thumbs.db', relative_path: '01/Thumbs.db', page_count: 0, status: 'not_pdf', is_pdf: false, is_cover: false },
            ],
        },
        {
            folder: '02', sheets: 2, min_pages: 3, max_pages: 5, pages: 1, status: 'missing', has_cover: false,
            files: [{ id: 20, name: '1.pdf', relative_path: '02/1.pdf', page_count: 1, status: 'ok', is_pdf: true, is_cover: false }],
        },
    ],
    misplaced_files: [{ id: 30, name: 'ghichu.pdf', relative_path: 'ghichu.pdf', page_count: 1, status: 'ok', is_pdf: true, is_cover: false }],
};
function setRoutes(pkgStatus = 'done', editable = false) {
    routes = [
        [base, () => respond(200, { status: 'ok', data: [{ id: 9, version: 2, status: pkgStatus, match_status: 'matched' }] })],
        [`${base}/9/check-view`, () => respond(200, {
            status: 'ok',
            data: { ...view, can_whiteout: editable, whiteout_hint: editable ? '' : 'Bấm Bắt đầu Check scan của hộp trước khi bôi trắng.' },
        })],
        [`${base}/9/files/10`, () => pdfResponse(1)],
        [`${base}/9/files/11`, () => pdfResponse(2)],
        [`${base}/9/files/20`, () => respond(404, { detail: 'File không còn trong thư mục scan trên máy chủ.' })],
        [`${base}/9/files/30`, () => pdfResponse(1)],
    ];
}

(async () => {
    // a) Dòng tóm tắt số trang theo quy tắc Số tờ + 1 .. 2 x Số tờ + 1.
    assert.equal(sandbox.scanCheckDossierLine(view.dossiers[0]), '3 tờ · cần 4–7 trang · có 5 trang');
    assert.equal(
        sandbox.scanCheckDossierLine({ sheets: null, pages: 2, has_cover: false }),
        'có 2 trang · chưa có bìa',
    );

    // b) Mở màn: tải check-view của gói mới nhất, mỗi hồ sơ có nhãn trạng thái đúng màu.
    setRoutes();
    await withTimeout(sandbox.openScanMatch(4, 'Hộp 01'), 'openScanMatch phải trả về');
    assert.ok(requests.includes(`${base}/9/check-view`), 'gọi check-view của gói mới nhất');
    assert.equal(body.children.length, 1, 'một lớp phủ duy nhất');
    const overlay = body.children[0];
    assert.match(text(overlay), /Check scan: Hộp 01 – S2/);
    const okBadge = byText(overlay, 'SPAN', 'Đủ trang')[0];
    assert.ok(okBadge && okBadge.className.includes('bg-success'), 'hồ sơ đủ trang có nhãn xanh');
    const missingBadge = byText(overlay, 'SPAN', 'Thiếu trang')[0];
    assert.ok(missingBadge && missingBadge.className.includes('bg-danger'), 'hồ sơ thiếu trang có nhãn đỏ');
    assert.match(text(overlay), /2 tờ · cần 3–5 trang · có 1 trang · chưa có bìa/);
    assert.match(text(overlay), /File sai cấp thư mục/);
    const thumbs = byText(overlay, 'BUTTON', 'Thumbs.db')[0];
    assert.equal(thumbs.disabled, true, 'file không phải PDF không bấm được');
    assert.equal(thumbs.listeners.click, undefined);
    const fileButtons = find(overlay, node => node.tagName === 'BUTTON' && node.className.includes('list-group-item'));
    assert.deepEqual(
        fileButtons.map(node => node.children[0].textContent),
        ['BIA.pdf (bìa)', '1.pdf', 'Thumbs.db', '1.pdf', 'ghichu.pdf'],
        'bìa đứng đầu, đúng thứ tự máy chủ trả',
    );
    const pane = find(overlay, node => node.className.includes('flex-grow-1'))[0];

    // c) Bấm một file: vẽ đủ trang của file đó, đánh dấu đã xem.
    rendered.length = 0;
    await withTimeout(fileButtons[1].listeners.click(), 'vẽ file 1.pdf');
    assert.ok(requests.includes(`${base}/9/files/11`));
    assert.equal(find(pane, node => node.tagName === 'CANVAS').length, 2, 'file 2 trang vẽ 2 canvas');
    assert.deepEqual(rendered, [1, 2]);
    assert.match(text(pane), /1\.pdf – trang 2\/2/);
    assert.equal(fileButtons[1].children[1].children[1].textContent, '✓', 'file đã xem có dấu ✓');
    assert.equal(fileButtons[0].children[1].children[1].textContent, '', 'file chưa xem không có dấu');

    // d) Bấm tên hồ sơ: vuốt cả hồ sơ, bìa rồi tới các file, bỏ qua file không phải PDF.
    const dossierHead = byText(overlay, 'BUTTON', 'Hồ sơ 01')[0];
    await withTimeout(dossierHead.listeners.click(), 'vẽ cả hồ sơ 01');
    const labels = find(pane, node => node.tagName === 'DIV' && /trang \d+\/\d+/.test(node.textContent)).map(node => node.textContent);
    assert.deepEqual(labels, ['BIA.pdf – trang 1/1', '1.pdf – trang 1/2', '1.pdf – trang 2/2']);
    assert.equal(fileButtons[0].children[1].children[1].textContent, '✓');
    assert.ok(!requests.includes(`${base}/9/files/12`), 'không tải file không phải PDF');

    // e) File lỗi: báo lỗi máy chủ, không đánh dấu đã xem.
    await withTimeout(fileButtons[3].listeners.click(), 'mở file lỗi');
    assert.match(text(pane), /File không còn trong thư mục scan trên máy chủ\./);
    assert.equal(find(pane, node => node.tagName === 'CANVAS').length, 0);
    assert.equal(fileButtons[3].children[1].children[1].textContent, '');

    // f) Chọn file khác khi file trước chưa tải xong: bản vẽ cũ bị bỏ, chỉ còn trang của file mới.
    let release;
    const held = new Promise(resolve => { release = resolve; });
    routes.find(([prefix]) => prefix === `${base}/9/files/30`)[1] = async () => { await held; return pdfResponse(3); };
    const slow = fileButtons[4].listeners.click();
    await withTimeout(fileButtons[0].listeners.click(), 'vẽ bìa trong lúc file cũ còn treo');
    release();
    await withTimeout(slow, 'lần vẽ cũ phải tự dừng');
    assert.equal(find(pane, node => node.tagName === 'CANVAS').length, 1, 'chỉ còn trang của bìa');
    assert.doesNotMatch(text(pane), /ghichu\.pdf – trang/);
    assert.equal(fileButtons[4].children[1].children[1].textContent, '', 'file bị bỏ giữa chừng không có dấu ✓');

    // f2) Chuyển file khi file trước đang vẽ dở trang 1: không vẽ tiếp trang 2 vào khung mới.
    let releasePage;
    holdRender = new Promise(resolve => { releasePage = resolve; });
    const midway = fileButtons[1].listeners.click();
    for (let i = 0; i < 20 && holdRender; i += 1) await new Promise(resolve => setImmediate(resolve));
    assert.equal(holdRender, null, 'trang 1 của 1.pdf đang vẽ');
    await withTimeout(fileButtons[0].listeners.click(), 'vẽ bìa khi 1.pdf còn dở');
    releasePage();
    await withTimeout(midway, 'lần vẽ dở phải tự dừng');
    assert.deepEqual(
        find(pane, node => node.tagName === 'DIV' && /trang \d+\/\d+/.test(node.textContent)).map(node => node.textContent),
        ['BIA.pdf – trang 1/1'],
        'khung chỉ có trang của bìa',
    );

    // g) Đóng: gỡ lớp phủ; mở lại cùng gói giữ dấu đã xem.
    const closeButton = find(overlay, node => node.className.includes('btn-close'))[0];
    closeButton.listeners.click();
    assert.equal(body.children.length, 0, 'đóng gỡ lớp phủ');
    await withTimeout(sandbox.openScanMatch(4, 'Hộp 01'), 'mở lại');
    const again = find(body.children[0], node => node.tagName === 'BUTTON' && node.className.includes('list-group-item'));
    assert.equal(again[1].children[1].children[1].textContent, '✓', 'mở lại cùng gói còn dấu đã xem');
    sandbox.closeScanCheck();

    // h) Gói chưa xử lý xong: không gọi check-view.
    requests.length = 0;
    setRoutes('processing');
    await withTimeout(sandbox.openScanMatch(4, 'Hộp 01'), 'mở gói đang xử lý');
    assert.ok(!requests.includes(`${base}/9/check-view`));
    assert.match(text(body), /Gói scan chưa xử lý xong\./);
    sandbox.closeScanCheck();

    // i) check-view bị từ chối: hiện lỗi máy chủ.
    setRoutes();
    routes[1][1] = () => respond(403, { detail: 'Không có quyền thực hiện thao tác này' });
    await withTimeout(sandbox.openScanMatch(4, 'Hộp 01'), 'mở khi bị từ chối');
    assert.match(text(body), /Không có quyền thực hiện thao tác này/);
    sandbox.closeScanCheck();

    // j) Không được bôi: không có nút, cột trái nói lý do.
    setRoutes();
    await withTimeout(sandbox.openScanMatch(4, 'Hộp 01'), 'mở khi chưa bắt đầu Check scan');
    let shown = body.children[0];
    assert.match(text(shown), /Bôi trắng vết ghim: Bấm Bắt đầu Check scan của hộp trước khi bôi trắng\./);
    let buttons = find(shown, node => node.tagName === 'BUTTON' && node.className.includes('list-group-item'));
    await withTimeout(buttons[1].listeners.click(), 'vẽ 1.pdf khi không được bôi');
    assert.equal(byText(shown, 'BUTTON', 'Bôi trắng vết ghim').length, 0);
    sandbox.closeScanCheck();

    // k) Được bôi: mỗi trang một nút; vẽ, đổi cỡ bút, hoàn tác, lưu.
    setRoutes('done', true);
    await withTimeout(sandbox.openScanMatch(4, 'Hộp 01'), 'mở khi được bôi');
    shown = body.children[0];
    assert.doesNotMatch(text(shown), /Bôi trắng vết ghim:/);
    buttons = find(shown, node => node.tagName === 'BUTTON' && node.className.includes('list-group-item'));
    await withTimeout(buttons[1].listeners.click(), 'vẽ 1.pdf');
    const editPane = find(shown, node => node.className.includes('flex-grow-1'))[0];
    const starts = byText(editPane, 'BUTTON', 'Bôi trắng vết ghim');
    assert.equal(starts.length, 2, 'mỗi trang có nút Bôi trắng');
    assert.equal(sandbox.scanCheckState.sha.get(11), 'sha-a', 'nhớ SHA-256 máy chủ gửi kèm file');
    starts[1].listeners.click();
    const frames = find(editPane, node => node.className.includes('position-relative'));
    assert.equal(frames[1].children.length, 2, 'trang 2 có lớp phủ để vẽ');
    const overlayCanvas = frames[1].children[1];
    assert.equal(overlayCanvas.style.touchAction, 'none');
    assert.equal(frames[0].children.length, 1, 'trang 1 không bị phủ');
    alerts.length = 0;
    starts[0].listeners.click();
    assert.equal(alerts.length, 1, 'chỉ bôi một trang một lúc');
    assert.equal(frames[0].children.length, 1);

    overlayCanvas.listeners.pointerdown({ clientX: 120, clientY: 80, pointerId: 1 });
    overlayCanvas.listeners.pointermove({ clientX: 140, clientY: 80 });
    overlayCanvas.listeners.pointermove({ clientX: 140.1, clientY: 80 });
    overlayCanvas.listeners.pointerup({});
    overlayCanvas.listeners.pointermove({ clientX: 180, clientY: 80 });
    const editing = sandbox.scanCheckState.editing;
    assert.deepEqual(JSON.parse(JSON.stringify(editing.strokes)), [{ width: 0.03, points: [[0.1, 0.1], [0.2, 0.1]] }]);
    assert.ok(overlayCanvas.ctx.calls.some(call => call[0] === 'lineTo'), 'nét được vẽ lên lớp phủ');
    const tools = frames[1].parent.children[0];
    assert.ok(byText(tools, 'BUTTON', 'Lưu trang').length === 1, 'thanh công cụ nằm trên trang');
    const select = tools.children[0];
    select.value = '2';
    select.listeners.change();
    overlayCanvas.listeners.pointerdown({ clientX: 400, clientY: 900, pointerId: 1 });
    overlayCanvas.listeners.pointerup({});
    assert.deepEqual(JSON.parse(JSON.stringify(editing.strokes[1])), { width: 0.06, points: [[1, 1]] }, 'bút lớn, điểm bị kẹp trong trang');
    byText(tools, 'BUTTON', 'Hoàn tác nét')[0].listeners.click();
    assert.equal(editing.strokes.length, 1);

    routes.push([`${base}/9/files/11/whiteout`, () => respond(409, { detail: 'File đã thay đổi kể từ lúc mở.' })]);
    const saveButton = byText(tools, 'BUTTON', 'Lưu trang')[0];
    await withTimeout(saveButton.listeners.click(), 'lưu bị từ chối');
    assert.match(text(tools), /File đã thay đổi kể từ lúc mở\./);
    assert.equal(frames[1].children.length, 2, 'lỗi thì giữ lớp phủ và các nét');
    assert.equal(sandbox.scanCheckState.editing, editing);

    // Rời file khi còn nét chưa lưu: hỏi, chọn ở lại thì không đổi gì.
    confirmAnswer = false;
    await withTimeout(buttons[0].listeners.click(), 'đổi file nhưng ở lại');
    assert.equal(confirms.length, 1);
    assert.equal(sandbox.scanCheckState.editing, editing);
    assert.match(text(editPane), /1\.pdf – trang 2\/2/);
    confirmAnswer = true;

    posts.length = 0;
    routes[routes.length - 1][1] = () => respond(200, { status: 'ok', data: { sha256: 'sha-b', page: 2 } });
    routes.find(([prefix]) => prefix === `${base}/9/files/11`)[1] = () => pdfResponse(2, 'sha-b');
    rendered.length = 0;
    await withTimeout(saveButton.listeners.click(), 'lưu trang');
    assert.deepEqual(posts, [{
        url: `${base}/9/files/11/whiteout`,
        body: { page: 2, base_sha256: 'sha-a', strokes: [{ width: 0.03, points: [[0.1, 0.1], [0.2, 0.1]] }] },
    }]);
    assert.equal(sandbox.scanCheckState.sha.get(11), 'sha-b', 'lần lưu sau dùng SHA-256 mới');
    assert.deepEqual(rendered, [2], 'vẽ lại đúng trang vừa lưu');
    assert.equal(frames[1].children.length, 1, 'lưu xong gỡ lớp phủ');
    assert.equal(sandbox.scanCheckState.editing, null);
    assert.match(text(tools), /Đã lưu, file gốc đã được ghi đè\./);
    assert.equal(byText(tools, 'BUTTON', 'Bôi trắng vết ghim').length, 1);

    // Lưu khi chưa có nét: không gửi gì.
    byText(tools, 'BUTTON', 'Bôi trắng vết ghim')[0].listeners.click();
    posts.length = 0;
    await withTimeout(byText(tools, 'BUTTON', 'Lưu trang')[0].listeners.click(), 'lưu khi chưa có nét');
    assert.equal(posts.length, 0);
    assert.match(text(tools), /Chưa có nét bôi nào\./);
    // Chưa có nét thì đổi file không cần hỏi.
    confirms.length = 0;
    await withTimeout(buttons[0].listeners.click(), 'đổi file khi lớp phủ trống');
    assert.equal(confirms.length, 0);
    assert.equal(sandbox.scanCheckState.editing, null);
    sandbox.closeScanCheck();
    assert.equal(body.children.length, 0);

    console.log('Project scan check self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
