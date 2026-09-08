// Region configuration only. Recognition and folder queues are not enabled here.
let ocrSample = null;
let ocrEditor = null;
let ocrEpoch = 0;

function refreshOcrButtons() {
    document.querySelectorAll('.ocr-region-button').forEach(button => {
        const col = Number(button.dataset.col);
        button.disabled = false;
        const configured = (currentConfigObj.ocr_regions || []).some(r => Number(r.col) === col);
        button.textContent = 'Chọn vùng';
        button.title = configured ? 'Đã có vùng OCR — bấm để chỉnh sửa' : 'Chọn vùng trên PDF mẫu';
    });
}

function resetOcrSample() {
    ocrEpoch += 1;
    if (ocrSample) void ocrSample.pdf.destroy();
    ocrSample = null;
    if (ocrEditor) ocrEditor.close();
}

function validateOcrRegion(region) {
    const b = region?.bbox;
    return ['first', 'last', 'number', 'anchor'].includes(region?.page_mode)
        && Number.isInteger(region.page_number) && region.page_number > 0
        && (region.page_mode !== 'anchor' || !!region.anchor?.trim())
        && Array.isArray(b) && b.length === 4 && b.every(Number.isFinite)
        && b[0] >= 0 && b[1] >= 0 && b[2] > 0 && b[3] > 0
        && b[0] + b[2] <= 1.000001 && b[1] + b[3] <= 1.000001;
}

function openOcrRegionEditor(col) {
    if (!Number.isInteger(col) || !document.getElementById(`chk_ocr_${col}`)) return;
    const templateId = currentConfigTemplateId;
    const saved = (currentConfigObj.ocr_regions || []).find(r => Number(r.col) === col);
    const dialog = document.createElement('dialog');
    dialog.className = 'ocr-region-dialog';
    dialog.setAttribute('aria-labelledby', 'ocrRegionTitle');
    dialog.innerHTML = `
        <h5 id="ocrRegionTitle"></h5>
        <p class="small text-muted">Chọn PDF mẫu rồi kéo khoanh vùng, hoặc nhập tọa độ %. PDF gốc không bị thay đổi.
        Bản thử này lưu vùng và dấu nhận diện mẫu, không lưu PDF mẫu lên server; mở lại cần chọn lại cùng file.</p>
        <label for="ocrSampleFile" class="form-label">PDF mẫu (tối đa 50 MB)</label>
        <input id="ocrSampleFile" type="file" accept="application/pdf,.pdf" class="form-control mb-2">
        <div class="row g-2 mb-2">
            <div class="col-md-4"><label for="ocrPageMode" class="form-label">Quy tắc trang</label>
                <select id="ocrPageMode" class="form-select">
                    <option value="first">Trang đầu</option><option value="last">Trang cuối</option>
                    <option value="number">Trang số N</option><option value="anchor">Tìm theo chữ mốc</option>
                </select></div>
            <div class="col-md-3"><label for="ocrPageNumber" class="form-label">Trang mẫu để chọn vùng</label>
                <input id="ocrPageNumber" type="number" min="1" value="1" step="1" class="form-control"></div>
            <div class="col-md-5"><label for="ocrAnchor" class="form-label">Chữ mốc trên trang</label>
                <input id="ocrAnchor" maxlength="200" class="form-control" disabled></div>
        </div>
        <p class="small text-muted">Ảnh xem trước được làm sạch và căn nghiêng nhẹ trên máy này; PDF mẫu gốc không bị thay đổi. Chữ mốc chỉ dùng để tìm trang khi nhân viên nhận dạng.</p>
        <div id="ocrSampleStatus" class="small mb-2" role="status"></div>
        <canvas id="ocrRegionCanvas" class="ocr-region-canvas" aria-label="PDF mẫu để khoanh vùng OCR"></canvas>
        <div class="row g-2 my-2">
            ${[['X', 'Trái'], ['Y', 'Trên'], ['W', 'Rộng'], ['H', 'Cao']].map(([id, label]) => `<div class="col-6 col-md-3"><label class="form-label" for="ocr${id}">${label} (%)</label><input id="ocr${id}" type="number" min="0" max="100" step="0.01" class="form-control" value="0"></div>`).join('')}
        </div>
        <div id="ocrRegionError" class="text-danger small mb-2" role="alert"></div>
        <div class="d-flex justify-content-end gap-2">
            <button id="ocrRegionCancel" type="button" class="btn btn-secondary">Hủy</button>
            <button id="ocrRegionApply" type="button" class="btn btn-primary" disabled>Áp dụng vùng</button>
        </div>
        <p class="small text-muted mt-2 mb-0">Sau khi áp dụng, nhấn Lưu cấu hình biểu mẫu để lưu lên hệ thống.</p>`;
    document.querySelector('#configModal .modal-content').appendChild(dialog);
    ocrEditor = dialog;
    const el = id => dialog.querySelector(`#${id}`);
    el('ocrRegionTitle').textContent = `Vùng OCR — ${getFieldName(col)}`;
    const canvas = el('ocrRegionCanvas');
    const ctx = canvas.getContext('2d');
    const base = document.createElement('canvas');
    let rendered = false;
    let previewPreprocessing = 'raw';
    let start = null;
    let renderSequence = 0;
    const current = () => dialog.open && currentConfigTemplateId === templateId;
    const error = message => { el('ocrRegionError').textContent = message; };
    const box = () => ['X', 'Y', 'W', 'H'].map(id => Number(el(`ocr${id}`).value) / 100);
    const setBox = values => values.forEach((v, i) => { el(`ocr${['X', 'Y', 'W', 'H'][i]}`).value = (v * 100).toFixed(2); });
    const draw = () => {
        if (!rendered) return;
        ctx.drawImage(base, 0, 0);
        const [x, y, w, h] = box();
        ctx.strokeStyle = '#d32f2f';
        ctx.lineWidth = 3;
        ctx.strokeRect(x * canvas.width, y * canvas.height, w * canvas.width, h * canvas.height);
    };
    const render = async () => {
        const seq = ++renderSequence;
        rendered = false;
        el('ocrRegionApply').disabled = true;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        if (!ocrSample) return;
        const sample = ocrSample;
        const mode = el('ocrPageMode').value;
        if (mode === 'first') el('ocrPageNumber').value = '1';
        if (mode === 'last') el('ocrPageNumber').value = String(sample.pdf.numPages);
        const n = Number(el('ocrPageNumber').value);
        if (!Number.isInteger(n) || n < 1 || n > sample.pdf.numPages) {
            error(`Chọn trang từ 1 đến ${sample.pdf.numPages}.`);
            return;
        }
        try {
            error('');
            const page = await sample.pdf.getPage(n);
            const original = page.getViewport({ scale: 1 });
            const viewport = page.getViewport({ scale: Math.min(1.5, 1400 / Math.max(original.width, original.height)) });
            // Separate target for each render prevents rapid page changes sharing a canvas.
            const target = document.createElement('canvas');
            target.width = Math.ceil(viewport.width);
            target.height = Math.ceil(viewport.height);
            await page.render({ canvasContext: target.getContext('2d'), viewport }).promise;
            if (!current() || seq !== renderSequence || ocrSample !== sample) return;
            let prepared = { canvas: target, angle: 0, preprocessing: 'raw' };
            if (window.OcrImage && typeof window.OcrImage.prepare === 'function') {
                try {
                    prepared = await window.OcrImage.prepare(target, { clean: true, deskew: true });
                } catch (_error) {
                    // A browser that cannot process ImageData can still use
                    // the raw PDF preview and save a valid region.
                    prepared = { canvas: target, angle: 0, preprocessing: 'raw' };
                }
            }
            if (!current() || seq !== renderSequence || ocrSample !== sample) return;
            base.width = canvas.width = prepared.canvas.width;
            base.height = canvas.height = prepared.canvas.height;
            base.getContext('2d').drawImage(prepared.canvas, 0, 0);
            previewPreprocessing = prepared.preprocessing || 'raw';
            rendered = true;
            draw();
            el('ocrRegionApply').disabled = false;
            const correction = Math.abs(Number(prepared.angle) || 0) > 0.001
                ? ` · căn ${(Number(prepared.angle) * 180 / Math.PI).toFixed(1)}°`
                : '';
            el('ocrSampleStatus').textContent = `${sample.name} — trang ${n}/${sample.pdf.numPages} · đã làm sạch${correction}`;
        } catch (e) {
            if (current() && seq === renderSequence) error('Không thể hiển thị trang PDF. Vui lòng chọn lại tài liệu hợp lệ.');
        }
    };
    el('ocrSampleFile').addEventListener('change', async () => {
        const file = el('ocrSampleFile').files[0];
        if (!file) return;
        const epoch = ++ocrEpoch;
        ++renderSequence;
        rendered = false;
        el('ocrRegionApply').disabled = true;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        error('');
        el('ocrSampleStatus').textContent = 'Đang mở PDF mẫu…';
        try {
            if (file.size > 50 * 1024 * 1024 || !/\.pdf$/i.test(file.name)) throw new Error('Chọn file PDF không quá 50 MB.');
            const bytes = await file.arrayBuffer();
            const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');
            const existing = currentConfigObj.ocr_sample;
            if (existing?.sha256 && existing.sha256 !== hash && currentConfigObj.ocr_regions?.length) {
                throw new Error('PDF khác mẫu đã cấu hình. Vui lòng chọn lại PDF mẫu ban đầu.');
            }
            const pdfjs = await import('/vendor/pdfjs/pdf.js');
            pdfjs.GlobalWorkerOptions.workerSrc = '/vendor/pdfjs/pdf.worker.js';
            const task = pdfjs.getDocument({ data: new Uint8Array(bytes), isEvalSupported: false, useWasm: false });
            task.onPassword = () => { void task.destroy(); };
            const pdf = await task.promise;
            if (!current() || epoch !== ocrEpoch) { await pdf.destroy(); return; }
            if (ocrSample) await ocrSample.pdf.destroy();
            ocrSample = { pdf, name: file.name, sha256: hash };
            el('ocrPageNumber').max = String(pdf.numPages);
            await render();
        } catch (e) {
            if (current() && epoch === ocrEpoch) {
                el('ocrSampleStatus').textContent = '';
                error(e.message || 'Không đọc được PDF; thử file không khóa mật khẩu.');
            }
        }
    });
    const modeChanged = () => {
        el('ocrAnchor').disabled = el('ocrPageMode').value !== 'anchor';
        el('ocrPageNumber').disabled = ['first', 'last'].includes(el('ocrPageMode').value);
        void render();
    };
    el('ocrPageMode').addEventListener('change', modeChanged);
    el('ocrPageNumber').addEventListener('change', () => { void render(); });
    ['X', 'Y', 'W', 'H'].forEach(id => el(`ocr${id}`).addEventListener('input', draw));
    const point = event => {
        const rect = canvas.getBoundingClientRect();
        return [Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)), Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))];
    };
    canvas.addEventListener('pointerdown', event => {
        if (!rendered || event.button !== 0) return;
        start = point(event);
        canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener('pointermove', event => {
        if (!start) return;
        const end = point(event);
        setBox([Math.min(start[0], end[0]), Math.min(start[1], end[1]), Math.abs(end[0] - start[0]), Math.abs(end[1] - start[1])]);
        draw();
    });
    canvas.addEventListener('pointerup', () => { start = null; });
    canvas.addEventListener('pointercancel', () => { start = null; });
    el('ocrRegionCancel').addEventListener('click', () => dialog.close());
    el('ocrRegionApply').addEventListener('click', () => {
        if (!current() || !rendered || !ocrSample) return;
        const region = { col, page_mode: el('ocrPageMode').value, page_number: Number(el('ocrPageNumber').value), anchor: el('ocrAnchor').value.trim(), bbox: box(), preprocessing: previewPreprocessing };
        if (!validateOcrRegion(region)) { error('Chọn vùng nằm trong trang, có chiều rộng/cao lớn hơn 0; nhập chữ mốc nếu dùng quy tắc tìm mốc.'); return; }
        currentConfigObj.ocr_sample = { name: ocrSample.name, sha256: ocrSample.sha256, pages: ocrSample.pdf.numPages };
        currentConfigObj.ocr_regions = [...(currentConfigObj.ocr_regions || []).filter(r => Number(r.col) !== col), region];
        buildConfigFromUI();
        refreshOcrButtons();
        dialog.close();
    });
    dialog.addEventListener('close', () => {
        ++renderSequence;
        ++ocrEpoch;
        dialog.remove();
        if (ocrEditor === dialog) ocrEditor = null;
        document.querySelector(`.ocr-region-button[data-col="${col}"]`)?.focus();
    }, { once: true });
    if (saved) {
        el('ocrPageMode').value = saved.page_mode;
        el('ocrPageNumber').value = String(saved.page_number);
        el('ocrAnchor').value = saved.anchor || '';
        setBox(saved.bbox);
    }
    dialog.showModal();
    modeChanged();
}

document.addEventListener('click', event => {
    const button = event.target.closest?.('.ocr-region-button');
    if (button && !button.disabled) openOcrRegionEditor(Number(button.dataset.col));
});
document.addEventListener('change', event => {
    if (!event.target.matches?.('.unified-chk-ocr')) return;
    buildConfigFromUI();
    refreshOcrButtons();
});
document.addEventListener('hidden.bs.modal', event => {
    if (event.target.id === 'configModal') resetOcrSample();
});
