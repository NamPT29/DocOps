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
async function openScanMatch(caseId, caseName) {
    scanSubmitState.projectId = Number(projectWorkflowProjectId);
    scanSubmitState.caseId = Number(caseId);
    const packages = await scanSubmitListPackages();
    const pkg = packages[0];
    if (!pkg) {
        alert('Chưa có gói scan nào.');
        return;
    }

    const overlay = scanSubmitElement('div', 'modal fade show');
    overlay.style.display = 'block';
    overlay.style.backgroundColor = 'rgba(0,0,0,0.5)';
    
    const dialog = scanSubmitElement('div', 'modal-dialog modal-dialog-scrollable');
    const content = scanSubmitElement('div', 'modal-content');
    
    const header = scanSubmitElement('div', 'modal-header bg-info text-white');
    const title = scanSubmitElement('h5', 'modal-title', `So khớp: ${caseName}`);
    const closeBtn = scanSubmitElement('button', 'btn-close btn-close-white');
    closeBtn.addEventListener('click', () => overlay.remove());
    header.append(title, closeBtn);
    
    const body = scanSubmitElement('div', 'modal-body');
    renderScanPackage(body, pkg);
    
    const footer = scanSubmitElement('div', 'modal-footer');
    const closeBtn2 = scanSubmitElement('button', 'btn btn-secondary', 'Đóng');
    closeBtn2.addEventListener('click', () => overlay.remove());
    footer.appendChild(closeBtn2);
    
    content.append(header, body, footer);
    dialog.appendChild(content);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
}
