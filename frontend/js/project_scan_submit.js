/* global authFetch, formatApiErrorDetail, formatVietnamDateTime, refreshProjectWorkflow, projectWorkflowProjectId, bootstrap */

// =============================================================================
// NỘP S (FR-SCN-01): submit a box's scan folder from the server and follow the
// package until it is read. Rendering uses textContent/createElement only.
// =============================================================================

const SCAN_SUBMIT_POLL_MS = 2000;
const SCAN_SUBMIT_OPEN_STATUSES = ['pending', 'rejected', 'in_progress'];
const SCAN_WARNING_LABELS = Object.freeze({
    missing_scan_user: 'Chưa có tên người scan',
    incomplete_files: 'Có file đang chép dở',
    error_files: 'Có file lỗi (cụt/mã hóa)',
    non_pdf_files: 'Có file không phải PDF',
});
const SCAN_PACKAGE_STATUS_LABELS = Object.freeze({
    processing: 'Đang xử lý',
    done: 'Xong',
    failed: 'Lỗi',
});

var scanSubmitState = {
    projectId: 0,
    caseId: 0,
    currentPath: '',
    selectedPath: null,
    poller: null,
    bound: false,
};

// --- pure helpers ---------------------------------------------------------------

/**
 * "Nộp S" is offered while Scan is open and Check scan has not started. A
 * waiting or returned box also needs its previous stage done (available).
 */
function scanSubmitCanSubmit(scanCell, qcCell) {
    if (!scanCell || !SCAN_SUBMIT_OPEN_STATUSES.includes(scanCell.status)) return false;
    if (scanCell.status !== 'in_progress' && scanCell.available === false) return false;
    const qcStatus = qcCell && qcCell.status ? qcCell.status : 'pending';
    return qcStatus === 'pending';
}

/** Error text for an API answer; a {code, message} detail shows its message. */
function scanSubmitErrorText(data, fallback = 'Không thực hiện được thao tác.') {
    const body = data || {};
    const detail = body.detail;
    if (detail && typeof detail === 'object' && !Array.isArray(detail) && typeof detail.message === 'string') {
        return detail.message;
    }
    return formatApiErrorDetail(detail || body.message || fallback);
}

function scanWarningLabels(flags) {
    if (!Array.isArray(flags)) return [];
    return flags.map(flag => SCAN_WARNING_LABELS[flag] || String(flag));
}

/** Warnings to show for a package, including failed files of a finished one. */
function scanPackageWarnings(pkg) {
    const warnings = scanWarningLabels(pkg && pkg.warning_flags);
    const failed = Number(pkg && pkg.failed_files) || 0;
    if (pkg && pkg.status === 'done' && failed > 0) {
        warnings.push(`${failed} file không đọc được, cần kiểm tra lại`);
    }
    return warnings;
}

function scanSubmitProgress(pkg) {
    const total = Number(pkg && pkg.total_files) || 0;
    const done = (Number(pkg && pkg.processed_files) || 0) + (Number(pkg && pkg.failed_files) || 0);
    const percent = total > 0 ? Math.min(100, Math.round((done * 100) / total)) : 0;
    return { done, total, percent, text: `${done}/${total} file (${percent}%)` };
}

/** API times are naive UTC; mark them as UTC before the shared formatter. */
function scanSubmitTime(value) {
    if (!value) return '';
    const text = String(value);
    const utc = /(Z|[+-]\d{2}:?\d{2})$/.test(text) ? text : `${text}Z`;
    if (typeof formatVietnamDateTime === 'function') return formatVietnamDateTime(utc);
    // index.html không nạp project_management.js: tự đổi sang giờ Việt Nam, cùng định dạng.
    const date = new Date(utc);
    if (isNaN(date.getTime())) return text;
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', hour12: false,
    }).formatToParts(date).map(part => [part.type, part.value]));
    return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
}

/**
 * Ask ``fetchPackage`` every ``intervalMs`` until the package is no longer
 * 'processing' or ``stop()`` is called. ``done`` resolves with the final
 * package, or ``null`` when stopped.
 */
function scanSubmitStartPolling(fetchPackage, onUpdate, timers, intervalMs = SCAN_SUBMIT_POLL_MS) {
    // Browsers throw "Illegal invocation" when setTimeout is called as a method
    // of another object, so the defaults are wrapped in plain functions.
    const clock = timers || {
        setTimeout: (callback, ms) => setTimeout(callback, ms),
        clearTimeout: handle => clearTimeout(handle),
    };
    let stopped = false;
    let handle = null;
    let finish;
    const done = new Promise(resolve => { finish = resolve; });

    async function tick() {
        handle = null;
        if (stopped) return;
        let pkg = null;
        try {
            pkg = await fetchPackage();
        } catch (error) {
            pkg = null;
        }
        if (stopped) return;
        if (pkg) onUpdate(pkg);
        if (pkg && pkg.status !== 'processing') {
            stopped = true;
            finish(pkg);
            return;
        }
        handle = clock.setTimeout(tick, intervalMs);
    }

    tick();
    return {
        done,
        stop() {
            if (stopped) return;
            stopped = true;
            if (handle !== null) clock.clearTimeout(handle);
            handle = null;
            finish(null);
        },
    };
}

// --- DOM ---------------------------------------------------------------------------

function scanSubmitElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
}

function scanSubmitApiBase() {
    return `/api/projects/${Number(scanSubmitState.projectId)}/cases/${Number(scanSubmitState.caseId)}/scan-packages`;
}

async function scanSubmitReadJson(response) {
    if (!response) return { ok: false, data: { detail: 'Phiên đăng nhập đã hết hạn.' } };
    const data = await response.json().catch(() => ({}));
    return { ok: response.ok && data.status === 'ok', data };
}

function setScanSubmitError(message) {
    const box = document.getElementById('scanSubmitError');
    if (!box) return;
    box.textContent = message || '';
    box.classList.toggle('d-none', !message);
}

async function scanSubmitListPackages() {
    const { ok, data } = await scanSubmitReadJson(await authFetch(scanSubmitApiBase(), { cache: 'no-store' }));
    return ok && Array.isArray(data.data) ? data.data : [];
}

function scanSubmitPackageLines(pkg) {
    const lines = [];
    lines.push(`S${pkg.version} – ${SCAN_PACKAGE_STATUS_LABELS[pkg.status] || pkg.status}`);
    lines.push(`Người scan: ${pkg.scanned_by_name || 'chưa có tên'}`);
    if (pkg.status === 'processing') {
        lines.push(`Tiến độ: ${scanSubmitProgress(pkg).text}`);
    } else {
        lines.push(`${Number(pkg.total_pages) || 0} trang, ${Number(pkg.total_a4_equivalent) || 0} trang A4 quy đổi`);
        const when = scanSubmitTime(pkg.finished_at || pkg.started_at);
        if (when) lines.push(`Lúc: ${when}`);
    }
    return lines;
}

function scanMatchLabels(pkg) {
    if (pkg.status !== 'done') return [];
    const els = [];
    const statusMap = {
        'matched': 'Khớp mục lục',
        'mismatch': 'Lệch mục lục',
        'no_catalog': 'Chưa có mục lục để so khớp'
    };
    const mainText = statusMap[pkg.match_status] || 'Chưa so khớp được';
    const mainEl = scanSubmitElement('div', 'fw-bold mt-2', mainText);
    if (pkg.match_status === 'matched') mainEl.classList.add('text-success');
    else if (pkg.match_status === 'mismatch' || !pkg.match_status) mainEl.classList.add('text-danger');
    els.push(mainEl);

    if (pkg.match_summary) {
        const summary = pkg.match_summary;
        const listMap = [
            { key: 'missing', label: 'Thiếu hồ sơ' },
            { key: 'extra', label: 'Thư mục thừa' },
            { key: 'invalid_folders', label: 'Tên thư mục lạ' },
            { key: 'duplicate_folders', label: 'Thư mục trùng' },
            { key: 'only_cover', label: 'Thư mục chỉ có bìa' },
            { key: 'removed_from_catalog', label: 'Hồ sơ không còn trong mục lục mới' },
            { key: 'misplaced_files', label: 'File sai cấp' }
        ];
        listMap.forEach(({ key, label }) => {
            const arr = summary[key];
            if (Array.isArray(arr) && arr.length > 0) {
                const show = arr.slice(0, 10);
                let text = `${label}: ${show.join(', ')}`;
                if (arr.length > 10) {
                    text += ` ... và ${arr.length - 10} mục nữa`;
                }
                els.push(scanSubmitElement('div', 'small text-muted', text));
            }
        });
        if (summary.truncated) {
            els.push(scanSubmitElement('div', 'small text-warning', 'Danh sách đã được cắt bớt'));
        }
    }
    return els;
}

function renderScanPackage(container, pkg) {
    container.replaceChildren();
    scanSubmitPackageLines(pkg).forEach((line, index) => {
        container.appendChild(scanSubmitElement('div', index === 0 ? 'fw-bold' : 'small', line));
    });
    if (pkg.status === 'failed' && pkg.error_message) {
        container.appendChild(scanSubmitElement('div', 'small text-danger', pkg.error_message));
    }
    scanPackageWarnings(pkg).forEach(label => {
        container.appendChild(scanSubmitElement('span', 'badge bg-warning text-dark me-1', label));
    });
    scanMatchLabels(pkg).forEach(el => container.appendChild(el));
}

function renderScanPackageHistory(packages) {
    const list = document.getElementById('scanSubmitHistory');
    if (!list) return;
    list.replaceChildren();
    if (!packages.length) {
        list.appendChild(scanSubmitElement('li', 'list-group-item text-muted small', 'Hộp chưa nộp gói scan nào.'));
        return;
    }
    packages.forEach(pkg => {
        const item = scanSubmitElement('li', 'list-group-item');
        renderScanPackage(item, pkg);
        list.appendChild(item);
    });
}

async function reloadScanPackageHistory() {
    renderScanPackageHistory(await scanSubmitListPackages());
}

function renderScanFolderList(data) {
    const list = document.getElementById('scanSubmitFolderList');
    const current = document.getElementById('scanSubmitCurrentPath');
    const up = document.getElementById('scanSubmitUpButton');
    scanSubmitState.currentPath = data.current_relative_path || '';
    if (current) current.textContent = scanSubmitState.currentPath || '(thư mục gốc)';
    if (up) up.disabled = data.parent_relative_path === null || data.parent_relative_path === undefined;
    if (up) up.dataset.path = data.parent_relative_path || '';
    if (!list) return;
    list.replaceChildren();
    const directories = Array.isArray(data.directories) ? data.directories : [];
    if (!directories.length) {
        list.appendChild(scanSubmitElement('div', 'list-group-item text-muted small', 'Không có thư mục con.'));
        return;
    }
    directories.forEach(directory => {
        const button = scanSubmitElement('button', 'list-group-item list-group-item-action', directory.name);
        button.type = 'button';
        button.addEventListener('click', () => loadScanSubmitFolder(directory.relative_path));
        list.appendChild(button);
    });
}

async function loadScanSubmitFolder(path) {
    setScanSubmitError('');
    const response = await authFetch(`/api/documents/server-folders?path=${encodeURIComponent(path || '')}`);
    const { ok, data } = await scanSubmitReadJson(response);
    if (!ok) {
        setScanSubmitError(scanSubmitErrorText(data, 'Không mở được thư mục.'));
        return;
    }
    renderScanFolderList(data);
}

function chooseScanSubmitFolder() {
    scanSubmitState.selectedPath = scanSubmitState.currentPath || null;
    renderScanSubmitSelection();
}

function renderScanSubmitSelection() {
    const selected = document.getElementById('scanSubmitSelectedPath');
    if (selected) {
        selected.textContent = scanSubmitState.selectedPath
            ? `Đã chọn: ${scanSubmitState.selectedPath}`
            : 'Hãy vào thư mục của hộp rồi bấm "Chọn thư mục này".';
    }
    const send = document.getElementById('scanSubmitSendButton');
    if (send) send.disabled = !scanSubmitState.selectedPath;
}

function stopScanSubmitPolling() {
    if (scanSubmitState.poller) scanSubmitState.poller.stop();
    scanSubmitState.poller = null;
}

async function followScanPackage(packageId) {
    const result = document.getElementById('scanSubmitResult');
    // Ensure any previous poller is stopped
    stopScanSubmitPolling();
    const poller = scanSubmitStartPolling(
        async () => (await scanSubmitListPackages()).find(pkg => Number(pkg.id) === packageId) || null,
        pkg => { if (result) renderScanPackage(result, pkg); },
    );
    scanSubmitState.poller = poller;
    const finished = await poller.done;
    if (scanSubmitState.poller === poller) scanSubmitState.poller = null;
    if (!finished) return;
    const send = document.getElementById('scanSubmitSendButton');
    if (send) send.disabled = false;
    await reloadScanPackageHistory();
    if (typeof refreshProjectWorkflow === 'function') await refreshProjectWorkflow();
}

async function sendScanSubmit() {
    if (!scanSubmitState.selectedPath) return;
    setScanSubmitError('');
    const levelInput = document.getElementById('scanSubmitUserLevel');
    const level = Math.max(0, Number.parseInt(levelInput && levelInput.value, 10) || 0);
    const send = document.getElementById('scanSubmitSendButton');
    if (send) send.disabled = true;
    const response = await authFetch(scanSubmitApiBase(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder_path: scanSubmitState.selectedPath, scan_user_name_level: level }),
    });
    const { ok, data } = await scanSubmitReadJson(response);
    if (!ok) {
        setScanSubmitError(scanSubmitErrorText(data, 'Không nộp được gói scan.'));
        if (send) send.disabled = false;
        return;
    }
    const packageId = Number(data.package_id);
    // Start following the package progress
    await followScanPackage(packageId);
}

function bindScanSubmitModal() {
    if (scanSubmitState.bound) return;
    scanSubmitState.bound = true;
    document.getElementById('scanSubmitUpButton')?.addEventListener('click', event => {
        loadScanSubmitFolder(event.currentTarget.dataset.path || '');
    });
    document.getElementById('scanSubmitChooseButton')?.addEventListener('click', chooseScanSubmitFolder);
    document.getElementById('scanSubmitSendButton')?.addEventListener('click', sendScanSubmit);
    document.getElementById('scanSubmitModal')?.addEventListener('hidden.bs.modal', onScanSubmitHidden);
}

function onScanSubmitHidden() {
    stopScanSubmitPolling();
    // Bootstrap removes body.modal-open on close even if the pipeline dialog
    // underneath is still open, which breaks its scrolling.
    if (document.querySelector('.modal.show')) document.body.classList.add('modal-open');
}

async function openScanSubmit(caseId, caseName) {
    bindScanSubmitModal();
    stopScanSubmitPolling();
    scanSubmitState.projectId = Number(projectWorkflowProjectId);
    scanSubmitState.caseId = Number(caseId);
    scanSubmitState.selectedPath = null;
    scanSubmitState.currentPath = '';
    const title = document.getElementById('scanSubmitModalTitle');
    if (title) title.textContent = caseName || '';
    const level = document.getElementById('scanSubmitUserLevel');
    if (level) level.value = '1';
    document.getElementById('scanSubmitResult')?.replaceChildren();
    renderScanSubmitSelection();
    setScanSubmitError('');
    // Load folder list and history concurrently
    await Promise.all([loadScanSubmitFolder(''), reloadScanPackageHistory()]);
    new bootstrap.Modal(document.getElementById('scanSubmitModal')).show();
    // After loading history, check for any processing package and follow it automatically
    const packages = await scanSubmitListPackages();
    const processingPkg = packages.find(p => p.status === 'processing');
    if (processingPkg) {
        const result = document.getElementById('scanSubmitResult');
        if (result) renderScanPackage(result, processingPkg);
        const send = document.getElementById('scanSubmitSendButton');
        if (send) send.disabled = true;
        followScanPackage(processingPkg.id);
    }
}
// =============================================================================
// CHECK SCAN: cột trái là hồ sơ/file, cột phải là các trang PDF để vuốt kiểm số
// chỉnh lý. Chỉ đọc; số trang so với mục lục: cần Số tờ + 1 đến 2 x Số tờ + 1.
// =============================================================================

const SCAN_CHECK_STATUS = Object.freeze({
    ok: { label: 'Đủ trang', css: 'bg-success' },
    missing: { label: 'Thiếu trang', css: 'bg-danger' },
    over: { label: 'Thừa trang', css: 'bg-warning text-dark' },
    unknown: { label: 'Chưa đếm được', css: 'bg-secondary' },
    no_catalog: { label: 'Không có trong mục lục', css: 'bg-secondary' },
});

const SCAN_WHITEOUT_BRUSHES = Object.freeze([
    { label: 'Bút nhỏ', width: 0.015 },
    { label: 'Bút vừa', width: 0.03 },
    { label: 'Bút lớn', width: 0.06 },
]);

var scanCheckState = {
    packageId: 0,
    viewed: new Set(),
    renderToken: 0,
    pdfjs: null,
    overlay: null,
    canWhiteout: false,
    whiteoutHint: '',
    sha: new Map(),
    editing: null,
};

/** Một dòng tóm tắt số trang của hồ sơ, ví dụ "3 tờ · cần 4–7 trang · có 5". */
function scanCheckDossierLine(dossier) {
    const parts = [];
    if (Number.isInteger(dossier.sheets) && dossier.sheets > 0) {
        parts.push(`${dossier.sheets} tờ`);
        parts.push(`cần ${dossier.min_pages}–${dossier.max_pages} trang`);
    }
    parts.push(`có ${Number(dossier.pages) || 0} trang`);
    if (!dossier.has_cover) parts.push('chưa có bìa');
    return parts.join(' · ');
}

function scanCheckFileUrl(fileId) {
    return `${scanSubmitApiBase()}/${Number(scanCheckState.packageId)}/files/${Number(fileId)}`;
}

async function scanCheckLoadPdfjs() {
    if (!scanCheckState.pdfjs) {
        scanCheckState.pdfjs = import('/vendor/pdfjs/pdf.js').then(pdfjs => {
            pdfjs.GlobalWorkerOptions.workerSrc = '/vendor/pdfjs/pdf.worker.js';
            return pdfjs;
        });
    }
    return scanCheckState.pdfjs;
}

/** Tải file PDF của gói, nhớ mã SHA-256 máy chủ gửi kèm (dùng khi lưu bôi trắng). */
async function scanCheckFetchPdf(file) {
    const response = await authFetch(scanCheckFileUrl(file.id), { cache: 'no-store' });
    if (!response || !response.ok) {
        const { data } = await scanSubmitReadJson(response);
        return { error: scanSubmitErrorText(data, 'Không mở được file.') };
    }
    const sha = response.headers && typeof response.headers.get === 'function'
        ? response.headers.get('X-Scan-File-Sha256') : '';
    scanCheckState.sha.set(file.id, sha || '');
    const bytes = new Uint8Array(await response.arrayBuffer());
    const pdfjs = await scanCheckLoadPdfjs();
    return { pdf: await pdfjs.getDocument({ data: bytes, isEvalSupported: false, useWasm: false }).promise };
}

async function scanCheckPaintPage(pdf, number, canvas) {
    const page = await pdf.getPage(number);
    const base = page.getViewport({ scale: 1 });
    const viewport = page.getViewport({ scale: Math.min(2, 900 / Math.max(base.width, 1)) });
    canvas.width = Math.floor(viewport.width);
    canvas.height = Math.floor(viewport.height);
    await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise;
}

async function scanCheckRenderFile(container, file, token) {
    const loaded = await scanCheckFetchPdf(file);
    if (token !== scanCheckState.renderToken) return false;
    if (loaded.error) {
        container.appendChild(scanSubmitElement('div', 'alert alert-danger py-1 small', `${file.name}: ${loaded.error}`));
        return false;
    }
    const pdf = loaded.pdf;
    for (let number = 1; number <= pdf.numPages; number += 1) {
        if (token !== scanCheckState.renderToken) return false;
        const canvas = document.createElement('canvas');
        canvas.className = 'border shadow-sm d-block';
        canvas.style.maxWidth = '100%';
        canvas.style.height = 'auto';
        const frame = scanSubmitElement('div', 'position-relative d-inline-block');
        frame.style.maxWidth = '100%';
        frame.appendChild(canvas);
        const figure = scanSubmitElement('div', 'mb-3 text-center');
        if (scanCheckState.canWhiteout) {
            const tools = scanSubmitElement('div', 'mb-1');
            scanCheckIdleTools(tools, { frame, canvas, tools, file, number });
            figure.appendChild(tools);
        }
        figure.append(frame, scanSubmitElement('div', 'small text-muted',
            `${file.name} – trang ${number}/${pdf.numPages}`));
        container.appendChild(figure);
        await scanCheckPaintPage(pdf, number, canvas);
    }
    return true;
}

// --- Bôi trắng vết ghim: vẽ nét trắng lên lớp phủ, Lưu trang thì máy chủ ghi đè file ---

function scanCheckIdleTools(tools, target, message) {
    tools.replaceChildren();
    const start = scanSubmitElement('button', 'btn btn-sm btn-outline-secondary', 'Bôi trắng vết ghim');
    start.type = 'button';
    start.addEventListener('click', () => scanCheckStartWhiteout(target));
    tools.appendChild(start);
    if (message) tools.appendChild(scanSubmitElement('span', 'small text-success ms-2', message));
}

/** Điểm con trỏ trên trang đang hiển thị, quy về 0..1 tính từ góc trên trái. */
function scanCheckPoint(event, rect) {
    const clamp = value => Math.min(1, Math.max(0, value));
    const u = clamp((event.clientX - rect.left) / Math.max(rect.width, 1));
    const v = clamp((event.clientY - rect.top) / Math.max(rect.height, 1));
    return [Math.round(u * 10000) / 10000, Math.round(v * 10000) / 10000];
}

function scanCheckDrawStrokes(overlay, strokes) {
    const context = overlay.getContext('2d');
    if (!context) return;
    context.clearRect(0, 0, overlay.width, overlay.height);
    context.strokeStyle = '#ffffff';
    context.lineCap = 'round';
    context.lineJoin = 'round';
    strokes.forEach(stroke => {
        context.lineWidth = stroke.width * overlay.width;
        context.beginPath();
        const [first, ...rest] = stroke.points;
        context.moveTo(first[0] * overlay.width, first[1] * overlay.height);
        (rest.length ? rest : [first]).forEach(([u, v]) => context.lineTo(u * overlay.width, v * overlay.height));
        context.stroke();
    });
}

function scanCheckStartWhiteout(target) {
    if (scanCheckState.editing) {
        alert('Hãy Lưu trang hoặc Hủy trang đang bôi trước.');
        return null;
    }
    const { frame, canvas, tools, file, number } = target;
    const overlay = document.createElement('canvas');
    overlay.width = canvas.width;
    overlay.height = canvas.height;
    overlay.className = 'position-absolute top-0 start-0 w-100 h-100';
    overlay.style.touchAction = 'none';
    overlay.style.cursor = 'crosshair';
    frame.appendChild(overlay);

    const strokes = [];
    let current = null;
    let brush = SCAN_WHITEOUT_BRUSHES[1].width;
    let busy = false;

    const status = scanSubmitElement('span', 'small ms-2');
    const size = document.createElement('select');
    size.className = 'form-select form-select-sm d-inline-block w-auto me-1';
    SCAN_WHITEOUT_BRUSHES.forEach((item, index) => {
        const option = scanSubmitElement('option', '', item.label);
        option.value = String(index);
        size.appendChild(option);
    });
    size.value = '1';
    size.addEventListener('change', () => { brush = (SCAN_WHITEOUT_BRUSHES[Number(size.value)] || SCAN_WHITEOUT_BRUSHES[1]).width; });
    const undo = scanSubmitElement('button', 'btn btn-sm btn-outline-secondary me-1', 'Hoàn tác nét');
    const cancel = scanSubmitElement('button', 'btn btn-sm btn-outline-secondary me-1', 'Hủy');
    const save = scanSubmitElement('button', 'btn btn-sm btn-primary', 'Lưu trang');
    [undo, cancel, save].forEach(button => { button.type = 'button'; });
    tools.replaceChildren(size, undo, cancel, save, status);

    const finish = message => {
        overlay.remove();
        scanCheckState.editing = null;
        scanCheckIdleTools(tools, target, message);
    };
    const editing = {
        number,
        strokes,
        dirty: () => strokes.length > 0,
        cancel: () => finish(''),
    };
    scanCheckState.editing = editing;

    overlay.addEventListener('pointerdown', event => {
        if (busy) return;
        if (typeof overlay.setPointerCapture === 'function') overlay.setPointerCapture(event.pointerId);
        current = { width: brush, points: [scanCheckPoint(event, overlay.getBoundingClientRect())] };
        strokes.push(current);
        scanCheckDrawStrokes(overlay, strokes);
    });
    overlay.addEventListener('pointermove', event => {
        if (!current) return;
        const point = scanCheckPoint(event, overlay.getBoundingClientRect());
        const last = current.points[current.points.length - 1];
        if (Math.abs(point[0] - last[0]) + Math.abs(point[1] - last[1]) < 0.002) return;
        if (current.points.length >= 2000) return;
        current.points.push(point);
        scanCheckDrawStrokes(overlay, strokes);
    });
    const stop = () => { current = null; };
    overlay.addEventListener('pointerup', stop);
    overlay.addEventListener('pointercancel', stop);
    undo.addEventListener('click', () => {
        strokes.pop();
        scanCheckDrawStrokes(overlay, strokes);
    });
    cancel.addEventListener('click', () => editing.cancel());
    save.addEventListener('click', async () => {
        if (busy) return;
        if (!strokes.length) {
            status.className = 'small ms-2 text-danger';
            status.textContent = 'Chưa có nét bôi nào.';
            return;
        }
        busy = true;
        save.disabled = true;
        status.className = 'small ms-2 text-muted';
        status.textContent = 'Đang lưu...';
        const { ok, data } = await scanSubmitReadJson(await authFetch(`${scanCheckFileUrl(file.id)}/whiteout`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ page: number, base_sha256: scanCheckState.sha.get(file.id) || '', strokes }),
        }));
        busy = false;
        save.disabled = false;
        if (!ok) {
            status.className = 'small ms-2 text-danger';
            status.textContent = scanSubmitErrorText(data, 'Không lưu được trang.');
            return;
        }
        scanCheckState.sha.set(file.id, data.data.sha256);
        const loaded = await scanCheckFetchPdf(file);
        if (loaded.pdf) await scanCheckPaintPage(loaded.pdf, number, canvas);
        finish(loaded.pdf ? 'Đã lưu, file gốc đã được ghi đè.' : `Đã lưu nhưng chưa tải lại được trang: ${loaded.error}`);
    });
    return editing;
}

/** Có nét chưa lưu thì hỏi trước khi bỏ; trả về false nếu người dùng muốn ở lại. */
function scanCheckLeaveEditing() {
    const editing = scanCheckState.editing;
    if (!editing) return true;
    if (editing.dirty() && !confirm('Trang đang bôi có nét chưa lưu. Bỏ các nét này?')) return false;
    editing.cancel();
    return true;
}

/** Hiện các trang của danh sách file ở cột phải; lần chọn mới hủy lần vẽ cũ. */
async function scanCheckShowFiles(pane, title, files, markers) {
    if (!scanCheckLeaveEditing()) return;
    scanCheckState.renderToken += 1;
    const token = scanCheckState.renderToken;
    pane.replaceChildren(scanSubmitElement('h6', 'mb-3', title));
    const pdfs = files.filter(file => file.is_pdf);
    if (!pdfs.length) {
        pane.appendChild(scanSubmitElement('div', 'text-muted small', 'Không có file PDF để xem.'));
        return;
    }
    for (const file of pdfs) {
        if (token !== scanCheckState.renderToken) return;
        if (pdfs.length > 1) pane.appendChild(scanSubmitElement('div', 'fw-bold small border-bottom mb-2', file.name));
        try {
            if (await scanCheckRenderFile(pane, file, token)) {
                scanCheckState.viewed.add(file.id);
                const marker = markers.get(file.id);
                if (marker) marker.textContent = '✓';
            }
        } catch (error) {
            pane.appendChild(scanSubmitElement('div', 'alert alert-danger py-1 small',
                `${file.name}: không đọc được PDF (${error && error.message ? error.message : error}).`));
        }
    }
}

function scanCheckFileButton(file, onPick, markers) {
    const button = scanSubmitElement('button', 'list-group-item list-group-item-action py-1 small d-flex justify-content-between');
    button.type = 'button';
    const pages = file.is_pdf ? `${file.page_count > 0 ? file.page_count : '?'} tr` : 'không phải PDF';
    const marker = scanSubmitElement('span', 'text-success ms-2', scanCheckState.viewed.has(file.id) ? '✓' : '');
    const right = scanSubmitElement('span', 'text-nowrap');
    right.append(scanSubmitElement('span', 'text-muted', pages), marker);
    button.append(
        scanSubmitElement('span', file.is_cover ? 'fw-bold' : '', file.is_cover ? `${file.name} (bìa)` : file.name),
        right,
    );
    markers.set(file.id, marker);
    if (file.is_pdf) button.addEventListener('click', () => onPick(file));
    else button.disabled = true;
    return button;
}

/** Cột trái: mỗi hồ sơ một khối có nhãn trạng thái số trang và danh sách file. */
function renderScanCheckList(list, pane, view) {
    list.replaceChildren();
    const markers = new Map();
    const show = (title, files) => scanCheckShowFiles(pane, title, files, markers);
    if (!view.dossiers.length && !view.misplaced_files.length) {
        list.appendChild(scanSubmitElement('div', 'text-muted small', 'Gói scan không có file nào.'));
    }
    view.dossiers.forEach(dossier => {
        const block = scanSubmitElement('div', 'mb-3');
        block.dataset.status = dossier.status;
        const head = scanSubmitElement('button', 'btn btn-light btn-sm w-100 text-start');
        head.type = 'button';
        const status = SCAN_CHECK_STATUS[dossier.status] || SCAN_CHECK_STATUS.unknown;
        head.append(
            scanSubmitElement('span', 'fw-bold me-2', `Hồ sơ ${dossier.folder}`),
            scanSubmitElement('span', `badge ${status.css}`, status.label),
            scanSubmitElement('div', 'small text-muted', scanCheckDossierLine(dossier)),
        );
        head.addEventListener('click', () => show(`Hồ sơ ${dossier.folder} – cả hồ sơ`, dossier.files));
        const files = scanSubmitElement('div', 'list-group list-group-flush');
        dossier.files.forEach(file => files.appendChild(
            scanCheckFileButton(file, picked => show(`Hồ sơ ${dossier.folder} – ${picked.name}`, [picked]), markers),
        ));
        block.append(head, files);
        list.appendChild(block);
    });
    if (view.misplaced_files.length) {
        const block = scanSubmitElement('div', 'mb-3');
        block.appendChild(scanSubmitElement('div', 'fw-bold small text-danger', 'File sai cấp thư mục'));
        const files = scanSubmitElement('div', 'list-group list-group-flush');
        view.misplaced_files.forEach(file => files.appendChild(
            scanCheckFileButton(file, picked => show(picked.relative_path, [picked]), markers),
        ));
        block.appendChild(files);
        list.appendChild(block);
    }
    return markers;
}

function closeScanCheck() {
    if (!scanCheckLeaveEditing()) return;
    scanCheckState.renderToken += 1;
    if (scanCheckState.overlay) scanCheckState.overlay.remove();
    scanCheckState.overlay = null;
}

async function openScanMatch(caseId, caseName) {
    scanSubmitState.projectId = Number(projectWorkflowProjectId);
    scanSubmitState.caseId = Number(caseId);
    const packages = await scanSubmitListPackages();
    const pkg = packages[0];
    if (!pkg) {
        alert('Chưa có gói scan nào.');
        return;
    }
    closeScanCheck();
    if (scanCheckState.overlay) return;
    if (scanCheckState.packageId !== pkg.id) {
        scanCheckState.viewed = new Set();
        scanCheckState.sha = new Map();
    }
    scanCheckState.canWhiteout = false;
    scanCheckState.whiteoutHint = '';
    scanCheckState.packageId = pkg.id;

    const overlay = scanSubmitElement('div', 'modal fade show');
    overlay.style.display = 'block';
    overlay.style.backgroundColor = 'rgba(0,0,0,0.5)';
    const dialog = scanSubmitElement('div', 'modal-dialog modal-fullscreen');
    const content = scanSubmitElement('div', 'modal-content');

    const header = scanSubmitElement('div', 'modal-header bg-info text-white py-2');
    const title = scanSubmitElement('h5', 'modal-title', `Check scan: ${caseName} – S${pkg.version}`);
    const closeBtn = scanSubmitElement('button', 'btn-close btn-close-white');
    closeBtn.type = 'button';
    closeBtn.addEventListener('click', closeScanCheck);
    header.append(title, closeBtn);

    const body = scanSubmitElement('div', 'modal-body p-0 d-flex');
    const left = scanSubmitElement('div', 'border-end p-2 overflow-auto');
    left.style.width = '360px';
    left.style.flex = '0 0 360px';
    const summary = scanSubmitElement('div', 'mb-2 small');
    renderScanPackage(summary, pkg);
    const list = scanSubmitElement('div');
    left.append(summary, list);
    const pane = scanSubmitElement('div', 'flex-grow-1 p-3 overflow-auto bg-light');
    pane.appendChild(scanSubmitElement('div', 'text-muted',
        'Bấm tên hồ sơ để vuốt cả hồ sơ, hoặc bấm một file để xem riêng file đó.'));
    body.append(left, pane);

    content.append(header, body);
    dialog.appendChild(content);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    scanCheckState.overlay = overlay;

    if (pkg.status !== 'done') {
        list.appendChild(scanSubmitElement('div', 'text-muted small', 'Gói scan chưa xử lý xong.'));
        return;
    }
    const { ok, data } = await scanSubmitReadJson(
        await authFetch(`${scanSubmitApiBase()}/${Number(pkg.id)}/check-view`, { cache: 'no-store' }),
    );
    if (!ok) {
        list.appendChild(scanSubmitElement('div', 'alert alert-danger small',
            scanSubmitErrorText(data, 'Không tải được danh sách file.')));
        return;
    }
    scanCheckState.canWhiteout = Boolean(data.data.can_whiteout);
    scanCheckState.whiteoutHint = data.data.whiteout_hint || '';
    if (!scanCheckState.canWhiteout && scanCheckState.whiteoutHint) {
        summary.appendChild(scanSubmitElement('div', 'small text-muted mt-1', `Bôi trắng vết ghim: ${scanCheckState.whiteoutHint}`));
    }
    renderScanCheckList(list, pane, data.data);
}
