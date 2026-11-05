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
    assert.match(tags[0], /\?v=1\.06"/, `${page} nâng ?v= của project_scan_submit.js`);
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
        getContext: () => ({ canvas: true }),
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
let routes = [];
function respond(status, body) {
    return { ok: status >= 200 && status < 300, status, json: async () => body, arrayBuffer: async () => new ArrayBuffer(4) };
}
function pdfResponse(pages) {
    const buffer = new ArrayBuffer(1);
    new Uint8Array(buffer)[0] = pages;
    return { ok: true, status: 200, json: async () => ({}), arrayBuffer: async () => buffer };
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
const sandbox = {
    console,
    Promise,
    Uint8Array,
    Map,
    Set,
    projectWorkflowProjectId: 7,
    alert: message => alerts.push(message),
    document: {
        body,
        getElementById: () => null,
        createElement: tag => element(tag),
    },
    setTimeout,
    clearTimeout,
    async authFetch(url, options = {}) {
        requests.push(url);
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
function setRoutes(pkgStatus = 'done') {
    routes = [
        [base, () => respond(200, { status: 'ok', data: [{ id: 9, version: 2, status: pkgStatus, match_status: 'matched' }] })],
        [`${base}/9/check-view`, () => respond(200, { status: 'ok', data: view })],
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

    console.log('Project scan check self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
