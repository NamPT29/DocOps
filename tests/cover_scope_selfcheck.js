// Bìa hồ sơ dùng chung theo thư mục (lát F1): form_renderer.js + submission.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function withTimeout(promise, message, ms = 1500) {
    let timer;
    return Promise.race([
        promise,
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`Treo: ${message}`)), ms); }),
    ]).finally(() => clearTimeout(timer));
}

// ---------- DOM giả ----------
function fakeClassList(initial = []) {
    const set = new Set(initial);
    return {
        add: (...names) => names.forEach(name => set.add(name)),
        remove: (...names) => names.forEach(name => set.delete(name)),
        contains: name => set.has(name),
        toggle: name => (set.has(name) ? (set.delete(name), false) : (set.add(name), true)),
        replace: (from, to) => { if (set.has(from)) { set.delete(from); set.add(to); } },
    };
}
function fakeElement(tag) {
    const element = {
        tag, style: {}, children: [], classList: fakeClassList(), listeners: {},
        appendChild(child) { this.children.push(child); return child; },
        addEventListener(type, fn) { this.listeners[type] = fn; },
        setAttribute() {},
        querySelector() { this.icon = this.icon || { classList: fakeClassList() }; return this.icon; },
        querySelectorAll() { return []; },
    };
    Object.defineProperty(element, 'className', {
        set(value) { element.classList = fakeClassList(String(value).split(/\s+/).filter(Boolean)); },
        get() { return ''; },
    });
    return element;
}

const fields = ['col_0', 'col_1', 'col_2'].map(name => ({ name, id: name, value: '' }));
const dataForm = { querySelectorAll: () => fields };
const fetches = [];
let respond = () => ({ status: 'ok', found: false, data: {} });
const storage = new Map();
const alerts = [];
const confirms = [];
let confirmAnswer = true;

const sandbox = {
    console, setTimeout, clearTimeout, URLSearchParams,
    currentUser: { id: 2, username: 'a' },
    currentEditingId: null,
    window: { activeProjectId: 7, activeTemplateId: 11, activeTemplateConfig: { cover_cols: [1, 2], cover_folder_level: 1 } },
    localStorage: {
        getItem: key => (storage.has(key) ? storage.get(key) : null),
        setItem: (key, value) => storage.set(key, String(value)),
        removeItem: key => storage.delete(key),
    },
    document: {
        getElementById: id => (id === 'dataForm' ? dataForm : fields.find(field => field.id === id) || null),
        querySelectorAll: selector => (selector.includes('#dataForm') ? fields : []),
        createElement: fakeElement,
    },
    async authFetch(url, options = {}) {
        fetches.push({ url, options });
        const body = await respond(url, options);
        if (body instanceof Error) throw body;
        return { ok: true, async json() { return body; } };
    },
    alert: message => alerts.push(message),
    confirm: message => { confirms.push(message); return confirmAnswer; },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/form_renderer.js', 'utf8'), sandbox);

const values = () => fields.map(field => field.value);
const type = (...items) => items.forEach((value, index) => { fields[index].value = value; });
const file = (uuid, folder) => ({ uuid, folder_group: folder, project_id: 7, template_id: 11 });
const flush = () => withTimeout(new Promise(resolve => setTimeout(resolve, 0)), 'chờ nạp bìa');
function open(pdf) {
    sandbox.setActivePdfDraftFile(pdf);
    return sandbox.applyDraftForActivePdf();
}

(async () => {
    // 1) Thư mục dùng chung bìa: cùng quy tắc với cover_scope_folder ở máy chủ
    assert.equal(sandbox.getCoverScope(file('x', 'project/2/hop1/hs1')), 'project/2/hop1/hs1');
    assert.equal(sandbox.getCoverScope(file('x', '\\project\\2\\cv\\')), 'project/2/cv');
    assert.equal(sandbox.getCoverScope(file('x', 'project/2/hop1/hs1'), { cover_folder_level: 2 }), 'project/2/hop1');
    assert.equal(sandbox.getCoverScope(file('x', 'a/b'), { cover_folder_level: 5 }), 'a/b');
    assert.equal(sandbox.getCoverScope(file('x', '__ROOT__')), null);
    assert.equal(sandbox.getCoverScope({ uuid: 'x' }), null);

    // 2) File đầu của thư mục mới: hỏi máy chủ bìa của thư mục, thư mục chưa có hồ sơ thì ghi nhận "trống"
    open(file('a1', 'project/2/A'));
    await flush();
    assert.equal(fetches.length, 1, 'mở file đầu tiên phải hỏi bìa của thư mục');
    assert.match(fetches[0].url, /^\/api\/cover-data\?/);
    assert.equal(new URLSearchParams(fetches[0].url.split('?')[1]).get('folder_path'), 'project/2/A');
    assert.equal(new URLSearchParams(fetches[0].url.split('?')[1]).get('template_id'), '11');
    assert.equal(sandbox.window.initialCoverScope, 'project/2/A');
    assert.equal(sandbox.window.initialCoverFolderEmpty, true);

    // 3) Cùng thư mục: bìa giữ nguyên, phần văn bản xóa, không hỏi lại máy chủ
    type('Bìa A', '31/08/2006', 'văn bản 1');
    open(file('a2', 'project/2/A'));
    assert.deepEqual(values(), ['Bìa A', '31/08/2006', ''], 'cùng hồ sơ: giữ bìa, xóa văn bản');
    await flush();
    assert.equal(fetches.length, 1, 'cùng thư mục không hỏi lại');

    // 4) Sang thư mục khác: xóa bìa cũ ngay, nạp bìa đã lưu của thư mục mới
    respond = () => ({ status: 'ok', found: true, data: { col_0: 'Bìa B', col_1: '01/01/2007' } });
    type('Bìa A', '31/08/2006', 'văn bản 2');
    open(file('b1', 'project/2/B'));
    assert.deepEqual(values(), ['', '', ''], 'sang hồ sơ khác: không mang bìa của hồ sơ trước');
    await flush();
    assert.equal(fetches.length, 2);
    assert.deepEqual(values(), ['Bìa B', '01/01/2007', ''], 'bìa đã lưu của thư mục mới được điền');
    assert.deepEqual({ ...sandbox.window.initialCoverData }, { col_0: 'Bìa B', col_1: '01/01/2007' });
    assert.equal(sandbox.window.initialCoverFolderEmpty, false);

    // 5) Người dùng chuyển thư mục khi câu trả lời cũ chưa về: không được điền bìa của thư mục cũ
    let releaseC;
    respond = url => (url.includes('project%2F2%2FC')
        ? new Promise(resolve => { releaseC = () => resolve({ status: 'ok', found: true, data: { col_0: 'Bìa C' } }); })
        : { status: 'ok', found: false, data: {} });
    open(file('c1', 'project/2/C'));
    await flush();
    open(file('d1', 'project/2/D'));
    await flush();
    releaseC();
    await flush();
    assert.equal(fields[0].value, '', 'câu trả lời muộn của thư mục C không được ghi vào form của thư mục D');
    assert.equal(sandbox.window.initialCoverScope, 'project/2/D');

    // 6) Ô người dùng đã gõ không bị ghi đè; lỗi mạng không báo lỗi, không làm hỏng form
    let releaseE;
    respond = () => new Promise(resolve => { releaseE = () => resolve({ status: 'ok', found: true, data: { col_0: 'Bìa E', col_1: '02/02/2008' } }); });
    open(file('e1', 'project/2/E'));
    await flush();
    type('Người dùng tự gõ', '', '');
    releaseE();
    await flush();
    assert.deepEqual(values(), ['Người dùng tự gõ', '02/02/2008', ''], 'chỉ điền ô bìa còn trống');
    respond = () => new Error('mất mạng');
    open(file('f1', 'project/2/F'));
    await flush();
    assert.deepEqual(values(), ['', '', '']);
    assert.equal(alerts.length, 0, 'nạp bìa lỗi không được bật hộp báo lỗi');

    // 7) Không biết thư mục (hàng đợi cũ không có folder_group): giữ cách cũ, bìa mang sang
    type('Bìa cũ', '', 'x');
    open({ uuid: 'legacy', project_id: 7, template_id: 11 });
    assert.deepEqual(values(), ['Bìa cũ', '', '']);

    // 9) Chọn dự án / tải lại trang: form dựng lại có bìa của nháp hs01; sang hs02 phải ra bìa hs02
    respond = url => (url.includes('project%2F2%2FX')
        ? { status: 'ok', found: true, data: { col_0: 'Bìa X', col_1: '' } }
        : { status: 'ok', found: true, data: { col_0: 'Bìa Y', col_1: '05/05/2005' } });
    sandbox.window.coverFormScope = undefined;
    sandbox.setActivePdfDraftFile(file('x1', 'project/2/X'));
    sandbox.window.lastAppliedPdfDraftIdentity = sandbox.window.activePdfDraftIdentity;
    type('Bìa X (từ nháp)', '', '');
    let before = fetches.length;
    assert.equal(sandbox.initCoverStateForActiveFile(), true);
    await flush();
    assert.equal(fetches.length, before + 1, 'dựng form xong phải hỏi bìa của thư mục file đang mở');
    assert.equal(sandbox.window.coverFormScope, 'project/2/X');
    assert.deepEqual({ ...sandbox.window.initialCoverData }, { col_0: 'Bìa X', col_1: '' });
    assert.equal(fields[0].value, 'Bìa X (từ nháp)', 'không ghi đè bìa người dùng đang gõ dở');
    open(file('y1', 'project/2/Y'));
    await flush();
    assert.deepEqual(values(), ['Bìa Y', '05/05/2005', ''], 'sang hồ sơ khác sau khi tải lại: bìa của hồ sơ đó');

    assert(String(sandbox.renderForm).includes('initCoverStateForActiveFile()'),
        'renderForm (chọn dự án, tải lại trang) phải khởi tạo bìa cho file đang mở');

    // 10) Không biết bìa đang có trên form thuộc thư mục nào: không mang sang thư mục đã biết
    sandbox.window.coverFormScope = undefined;
    type('Bìa không rõ nguồn', '', '');
    open(file('z1', 'project/2/Z'));
    assert.equal(fields[0].value === 'Bìa không rõ nguồn', false, 'chưa biết thư mục trước thì không giữ bìa');

    // 11) Đang Xem/Sửa hồ sơ đã lưu: không tự điền bìa vào hồ sơ đó
    vm.runInContext('currentEditingId = 9', sandbox);
    type('', '', 'đang sửa');
    sandbox.setActivePdfDraftFile(file('w1', 'project/2/W'));
    before = fetches.length;
    sandbox.initCoverStateForActiveFile();
    await flush();
    assert.equal(fetches.length, before, 'đang Xem/Sửa thì không hỏi bìa');
    assert.deepEqual(values(), ['', '', 'đang sửa']);
    vm.runInContext('currentEditingId = null', sandbox);
    respond = () => ({ status: 'ok', found: false, data: {} });

    // 8) Biểu mẫu nhỏ mở hết các nhóm; biểu mẫu lớn chỉ mở nhóm đầu
    const group = (count) => ({ category: 'Nhóm', fields: Array.from({ length: count }, (_, i) => ({ col_index: i })) });
    const isOpen = (index, schema) => {
        const section = sandbox._buildCategorySection({ category: 'Nhóm', fields: [] }, index, schema, {}, {});
        return !section.children[1].classList.contains('d-none');
    };
    const small = [group(4), group(7)];
    const large = [group(20), group(11)];
    assert.equal(isOpen(1, small), true, 'biểu mẫu 11 trường: nhóm Văn bản phải mở sẵn');
    assert.equal(isOpen(0, large), true);
    assert.equal(isOpen(1, large), false, 'biểu mẫu trên 30 trường: giữ cách gập nhóm như cũ');
    assert.equal(isOpen(1, [group(15), group(15)]), true, 'đúng 30 trường vẫn là biểu mẫu nhỏ');

    // ---------- submission.js: khi nào hỏi đồng bộ bìa ----------
    vm.runInContext(fs.readFileSync('frontend/js/pdf_link_state.js', 'utf8'), sandbox);
    vm.runInContext(fs.readFileSync('frontend/js/submission.js', 'utf8'), sandbox);
    Object.assign(sandbox, {
        formatApiErrorDetail: String, fetchSubmissions() {}, saveQueueState() {}, renderFileQueue() {},
        updatePdfLinkUI() {}, resizeDynamicFormInputs() {}, removeCurrentFormDraft() {},
    });
    sandbox.window.pdfLinkState.setLinked(true);
    const extraElements = new Map();
    sandbox.document.getElementById = id => (id === 'dataForm' ? dataForm
        : fields.find(field => field.id === id)
        || extraElements.get(id) || extraElements.set(id, fakeElement('div')).get(id));
    const posted = [];
    respond = (url, options) => {
        if (url === '/api/submit') { posted.push(JSON.parse(options.body)); return { status: 'ok' }; }
        return { status: 'ok', found: false, data: {} };
    };
    async function saveNew(pdf, ...typed) {
        sandbox.uploadedFilesQueue = [pdf];
        sandbox.iframeCurrentIndex = 0;
        confirms.length = 0;
        type(...typed);
        await withTimeout(vm.runInContext("submitData('draft')", sandbox), 'lưu hồ sơ');
        return { asked: confirms.length, sync: posted[posted.length - 1].sync_cover };
    }

    // Thư mục chưa có hồ sơ nào: lưu văn bản đầu không hỏi
    open(file('g1', 'project/2/G'));
    await flush();
    let result = await saveNew(file('g1', 'project/2/G'), 'Bìa G', '03/03/2009', 'vb1');
    assert.deepEqual(result, { asked: 0, sync: false }, 'thư mục chưa có hồ sơ: không có gì để đồng bộ');
    // Văn bản tiếp theo cùng thư mục, bìa không đổi: không hỏi
    open(file('g2', 'project/2/G'));
    result = await saveNew(file('g2', 'project/2/G'), 'Bìa G', '03/03/2009', 'vb2');
    assert.deepEqual(result, { asked: 0, sync: false }, 'bìa không đổi thì không hỏi ở mỗi văn bản');
    // Sửa bìa: hỏi, đồng ý thì gửi sync_cover
    open(file('g3', 'project/2/G'));
    result = await saveNew(file('g3', 'project/2/G'), 'Bìa G (sửa)', '03/03/2009', 'vb3');
    assert.deepEqual(result, { asked: 1, sync: true }, 'bìa đổi so với bìa đã lưu: phải hỏi đồng bộ');
    confirmAnswer = false;
    open(file('g4', 'project/2/G'));
    result = await saveNew(file('g4', 'project/2/G'), 'Bìa G (sửa lần 2)', '03/03/2009', 'vb4');
    assert.deepEqual(result, { asked: 1, sync: false }, 'chọn Cancel thì chỉ lưu văn bản này');
    confirmAnswer = true;
    // Thư mục đã có hồ sơ, gõ bìa khác bìa đã lưu: hỏi
    respond = (url, options) => {
        if (url === '/api/submit') { posted.push(JSON.parse(options.body)); return { status: 'ok' }; }
        return { status: 'ok', found: true, data: { col_0: 'Bìa H', col_1: '' } };
    };
    open(file('h1', 'project/2/H'));
    await flush();
    result = await saveNew(file('h1', 'project/2/H'), 'Bìa H khác', '', 'vb');
    assert.deepEqual(result, { asked: 1, sync: true }, 'bìa khác bìa đã lưu của thư mục: hỏi');
    // Sau Xem/Sửa (cancelEdit) không tin bìa cũ nữa: file kế tiếp nạp lại
    vm.runInContext('cancelEdit()', sandbox);
    assert.equal(sandbox.window.coverFormScope, undefined);
    assert.equal(sandbox.window.initialCoverScope, undefined);
    const fetchesBeforeNext = fetches.length;
    open(file('h2', 'project/2/H'));
    await flush();
    assert.equal(fetches.length, fetchesBeforeNext + 1, 'sau khi thoát Xem/Sửa, file kế tiếp hỏi lại bìa của thư mục');

    // Phiên bản script đã nâng trong cả hai trang
    for (const page of ['frontend/index.html', 'frontend/admin.html']) {
        const html = fs.readFileSync(page, 'utf8');
        assert(html.includes('js/form_renderer.js?v=101.02'), `${page}: form_renderer.js phải là v101.01`);
        assert(html.includes('js/submission.js?v=100.07'), `${page}: submission.js phải là v100.07`);
    }
    console.log('Cover scope self-check: OK');
})().catch(error => {
    console.error(error);
    process.exit(1);
});
