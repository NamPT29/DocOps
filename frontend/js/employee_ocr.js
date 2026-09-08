/*
 * Employee-side OCR queue.
 *
 * Recognition is deliberately opt-in (the employee presses "Nhận dạng"),
 * sequential, and local to the browser.  The server is used only for the
 * protected PDF download and a small liveness check; no OCR image or result
 * is uploaded by this module.
 */
(function (root) {
    'use strict';

    const TESSERACT_WORKER_PATH = '/vendor/tesseract/worker.min.js';
    const TESSERACT_CORE_PATH = '/vendor/tesseract/core';
    const TESSERACT_LANG_PATH = '/vendor/tesseract/lang';
    const HEARTBEAT_INTERVAL_MS = 5000;
    const MAX_RENDER_PIXELS = 3200;
    const OCR_CACHE_VERSION = 'ocr-v1';

    const state = {
        worker: null,
        workerPromise: null,
        pdfjsPromise: null,
        heartbeatTimer: null,
        connected: false,
        running: false,
        paused: false,
        pauseRequested: false,
        queuePromise: null,
        hydrated: false,
        lastRenderedAt: 0,
    };

    class OcrPauseError extends Error {
        constructor(message = 'OCR đang tạm dừng vì mất kết nối hoặc người dùng yêu cầu.') {
            super(message);
            this.name = 'OcrPauseError';
        }
    }

    function el(id) {
        return document.getElementById(id);
    }

    function canRun() {
        if (typeof currentUserCanInput === 'function' && !currentUserCanInput()) return false;
        return !new URLSearchParams(window.location.search).has('check_id');
    }

    function setStatus(message, tone = 'muted') {
        const status = el('ocrQueueStatus');
        if (!status) return;
        status.className = `small text-${tone}`;
        status.textContent = message;
    }

    function selectedFile() {
        if (typeof uploadedFilesQueue === 'undefined' || typeof iframeCurrentIndex === 'undefined') return null;
        return uploadedFilesQueue[iframeCurrentIndex] || null;
    }

    function safeSaveQueue() {
        if (typeof saveQueueState !== 'function') return;
        try {
            saveQueueState();
        } catch (error) {
            // OCR remains usable for the current tab even if a browser's
            // localStorage quota is exhausted; the final draft still follows
            // the existing save flow.
            console.warn('Không thể lưu trạng thái OCR cục bộ:', error);
        }
    }

    function renderQueue(force = false) {
        const now = Date.now();
        if (!force && now - state.lastRenderedAt < 350) return;
        state.lastRenderedAt = now;
        if (typeof renderFileQueue === 'function') renderFileQueue();
    }

    function setButtonState() {
        const start = el('ocrStartButton');
        const resume = el('ocrResumeButton');
        const pause = el('ocrPauseButton');
        const retry = el('ocrRetryButton');
        if (!start || !resume || !pause || !retry) return;
        const enabled = canRun();
        [start, resume, pause, retry].forEach(button => {
            button.classList.toggle('d-none', !enabled);
        });
        if (!enabled) return;
        const hasQueue = typeof uploadedFilesQueue !== 'undefined' && uploadedFilesQueue.length > 0;
        start.hidden = state.paused && !state.running;
        start.disabled = state.running || !state.connected || !hasQueue;
        start.textContent = state.paused ? 'Tiếp tục OCR' : 'Nhận dạng';
        pause.hidden = !state.running;
        pause.disabled = !state.running;
        resume.hidden = !(state.paused && state.connected && !state.running);
        resume.disabled = !state.paused || !state.connected || state.running;
        retry.disabled = state.running || !state.connected || !selectedFile();
    }

    function pauseForConnectivity() {
        state.connected = false;
        if (state.running) {
            state.pauseRequested = true;
            // Do not keep running local OCR after the server heartbeat fails.
            // Terminating the single worker also releases CPU promptly.
            void closeWorker();
        }
        setStatus('Mất kết nối máy chủ — OCR đang tạm dừng.', 'danger');
        setButtonState();
    }

    function fileLabel(file) {
        if (typeof getQueueDocumentName === 'function') return getQueueDocumentName(file);
        return file?.name || file?.relative_path || 'PDF';
    }

    function setFileState(file, status, progress, message = '') {
        if (!file) return;
        file.ocr_status = status;
        if (Number.isFinite(progress)) file.ocr_progress = Math.max(0, Math.min(100, Math.round(progress)));
        if (message) file.ocr_message = String(message).slice(0, 240);
        else if (status === 'done') delete file.ocr_message;
        safeSaveQueue();
        renderQueue(status === 'done' || status === 'paused' || status === 'error');
    }

    function normalizeText(value) {
        if (!value) return '';
        let text = String(value)
            .normalize('NFC')
            .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, ' ')
            .replace(/[\r\n]+/g, ' ')
            .trim();

        // Xóa ký tự rác mép viền do bảng hoặc viền scan: | _ - ~ = ' " ` • ° « » \ / – —
        text = text.replace(/^[\s|_\-~=`'".,:;•°«»\\/–—]+/g, '')
                   .replace(/[\s|_\-~=`'"•°«»\\/–—]+$/g, '')
                   .trim();

        // Chuẩn hóa dấu gạch chéo không có khoảng trắng thừa: ví dụ "45 / 2021 / QĐ - UBND" -> "45/2021/QĐ-UBND"
        text = text.replace(/(\S)\s*\/\s*(\S)/gu, '$1/$2');

        // Chuẩn hóa dấu gạch ngang giữa các từ viết tắt / mã số
        text = text.replace(/([A-Za-zÀ-ỹ0-9])\s*-\s*([A-Za-zÀ-ỹ0-9])/gu, '$1-$2');

        // Chuẩn hóa ngày tháng: "15 / 08 / 2023" hoặc "15 . 08 . 2023" -> "15/08/2023"
        text = text.replace(/(\b\d{1,2})\s*[\/\.]\s*(\d{1,2})\s*[\/\.]\s*(\d{4}\b)/g, '$1/$2/$3');

        // Khử khoảng trắng trước dấu câu
        text = text.replace(/\s+([,.:;!?])/g, '$1');

        // Gộp khoảng trắng thừa
        text = text.replace(/\s+/gu, ' ').trim();

        // Khắc phục các lỗi chữ viết tắt hành chính phổ biến
        text = text.replace(/\bQĐ\s*-\s*UBND\b/gu, 'QĐ-UBND');
        text = text.replace(/\bUBND\s*-\s*TP\b/gu, 'UBND-TP');
        text = text.replace(/\bHĐND\s*-\s*UBND\b/gu, 'HĐND-UBND');

        return text;
    }

    function normalizeAnchor(value) {
        return normalizeText(value)
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '')
            .toLowerCase();
    }

    function getOcrColumns(config) {
        return [...new Set((Array.isArray(config?.ocr_cols) ? config.ocr_cols : [])
            .map(Number)
            .filter(col => Number.isInteger(col) && col > 0))];
    }

    function getRegions(config, columns) {
        const regionMap = new Map();
        (Array.isArray(config?.ocr_regions) ? config.ocr_regions : []).forEach(region => {
            const col = Number(region?.col);
            if (Number.isInteger(col) && col > 0 && columns.includes(col)) regionMap.set(col, region);
        });
        return regionMap;
    }

    function validRegion(region) {
        const bbox = Array.isArray(region?.bbox) ? region.bbox.map(Number) : [];
        return bbox.length === 4
            && bbox.every(Number.isFinite)
            && bbox[0] >= 0 && bbox[1] >= 0
            && bbox[2] > 0 && bbox[3] > 0
            && bbox[0] + bbox[2] <= 1.000001
            && bbox[1] + bbox[3] <= 1.000001;
    }

    async function heartbeat() {
        if (!canRun()) return false;
        if (navigator['on' + 'Line'] === false) {
            pauseForConnectivity();
            return false;
        }
        let timeout = null;
        try {
            const controller = typeof AbortController === 'function' ? new AbortController() : null;
            timeout = controller ? window.setTimeout(() => controller.abort(), 4000) : null;
            const response = await fetch('/health/live', {
                cache: 'no-store',
                headers: { 'X-OCR-Heartbeat': '1' },
                ...(controller ? { signal: controller.signal } : {}),
            });
            state.connected = response.ok;
        } catch (_error) {
            state.connected = false;
        } finally {
            if (timeout) window.clearTimeout(timeout);
        }
        if (!state.connected) {
            pauseForConnectivity();
        } else if (!state.running && !state.paused) {
            setStatus('OCR trên máy này; kết quả cần được kiểm tra trước khi lưu nháp.', 'muted');
        }
        setButtonState();
        return state.connected;
    }

    async function ensureOnline() {
        if (state.pauseRequested || state.paused) throw new OcrPauseError();
        if (!(await heartbeat())) throw new OcrPauseError('Không thể kết nối máy chủ; OCR đã tạm dừng.');
        if (state.pauseRequested || state.paused) throw new OcrPauseError();
    }

    async function ensurePdfJs() {
        if (!state.pdfjsPromise) {
            state.pdfjsPromise = import('/vendor/pdfjs/pdf.js').then(pdfjs => {
                pdfjs.GlobalWorkerOptions.workerSrc = '/vendor/pdfjs/pdf.worker.js';
                return pdfjs;
            });
        }
        return state.pdfjsPromise;
    }

    async function ensureWorker() {
        await ensureOnline();
        if (state.worker) return state.worker;
        if (state.workerPromise) return state.workerPromise;
        if (!root.Tesseract || typeof root.Tesseract.createWorker !== 'function') {
            throw new Error('Trình duyệt chưa tải được mô-đun OCR cục bộ. Hãy dùng Chrome/Edge mới rồi tải lại trang.');
        }
        setStatus('Đang tải mô hình OCR tiếng Việt trên máy này…', 'primary');
        const workerTimeoutMs = 30000;
        let timer = null;
        const timeoutPromise = new Promise((_, reject) => {
            timer = setTimeout(() => {
                reject(new Error('Tải bộ máy OCR quá thời gian (30 giây). Có thể trình duyệt chặn WebAssembly hoặc máy chủ chưa khởi động lại để cập nhật CSP.'));
            }, workerTimeoutMs);
        });
        const loadPromise = root.Tesseract.createWorker('vie', 1, {
            workerPath: TESSERACT_WORKER_PATH,
            corePath: TESSERACT_CORE_PATH,
            langPath: TESSERACT_LANG_PATH,
            cachePath: OCR_CACHE_VERSION,
            cacheMethod: 'write',
            gzip: true,
            errorHandler: error => {
                console.error('Tesseract worker error:', error);
            },
            logger: message => {
                if (!state.running || !message) return;
                if (message.status === 'loading tesseract core') setStatus('Đang tải bộ máy OCR…', 'primary');
                else if (message.status === 'loading language traineddata') setStatus('Đang tải dữ liệu tiếng Việt…', 'primary');
            },
        });
        state.workerPromise = Promise.race([loadPromise, timeoutPromise])
            .finally(() => {
                if (timer) clearTimeout(timer);
            })
            .then(async worker => {
                await worker.setParameters({
                    tessedit_pageseg_mode: '6',
                    preserve_interword_spaces: '1',
                });
                state.worker = worker;
                return worker;
            }).catch(error => {
                state.workerPromise = null;
                throw error;
            });
        return state.workerPromise;
    }

    async function closeWorker() {
        const worker = state.worker;
        const pending = state.workerPromise;
        state.worker = null;
        state.workerPromise = null;
        if (worker && typeof worker.terminate === 'function') {
            try { await worker.terminate(); } catch (_error) { /* best effort */ }
        } else if (pending) {
            // If initialization was still downloading the local model, clean
            // up the worker as soon as that promise settles.
            void pending.then(nextWorker => {
                if (state.worker === nextWorker) state.worker = null;
                return nextWorker?.terminate?.();
            }).catch(() => {});
        }
    }

    function normalizePdfUrlForOcr(url) {
        if (typeof normalizePdfUrl === 'function') return normalizePdfUrl(url);
        if (String(url || '').startsWith('/uploads/')) return `/api/files/${String(url).slice('/uploads/'.length)}`;
        return url;
    }

    async function downloadPdf(file) {
        await ensureOnline();
        const url = normalizePdfUrlForOcr(file?.url);
        if (!url) throw new Error('PDF không có đường dẫn tải hợp lệ.');
        const response = typeof authFetch === 'function'
            ? await authFetch(url, { cache: 'no-store' })
            : await fetch(url, { cache: 'no-store' });
        if (!response) throw new OcrPauseError('Phiên đăng nhập không còn hiệu lực.');
        if (!response.ok) throw new Error(`Không tải được PDF (HTTP ${response.status}).`);
        const bytes = await response.arrayBuffer();
        if (!bytes.byteLength) throw new Error('PDF rỗng.');
        return new Uint8Array(bytes);
    }

    async function openPdf(file) {
        const pdfjs = await ensurePdfJs();
        const data = await downloadPdf(file);
        await ensureOnline();
        const task = pdfjs.getDocument({ data, isEvalSupported: false, useWasm: false });
        task.onPassword = () => { void task.destroy(); };
        return task.promise;
    }

    function renderScale(page) {
        const original = page.getViewport({ scale: 1 });
        return Math.min(3.8, MAX_RENDER_PIXELS / Math.max(original.width, original.height));
    }

    async function renderPage(pdf, pageNumber) {
        await ensureOnline();
        const page = await pdf.getPage(pageNumber);
        const viewport = page.getViewport({ scale: renderScale(page) });
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.ceil(viewport.width));
        canvas.height = Math.max(1, Math.ceil(viewport.height));
        await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise;
        return canvas;
    }

    function upscale(canvas) {
        const longest = Math.max(canvas.width, canvas.height);
        const factor = longest < 900 ? 2 : (longest < 1400 ? 1.35 : 1);
        if (factor === 1) return canvas;
        const output = document.createElement('canvas');
        output.width = Math.max(1, Math.round(canvas.width * factor));
        output.height = Math.max(1, Math.round(canvas.height * factor));
        const context = output.getContext('2d');
        context.imageSmoothingEnabled = true;
        context.imageSmoothingQuality = 'high';
        context.drawImage(canvas, 0, 0, output.width, output.height);
        return output;
    }

    async function recognize(canvas) {
        await ensureOnline();
        const worker = await ensureWorker();
        await ensureOnline();
        // Áp dụng linh hoạt PSM: PSM 7 cho các trường văn bản 1 dòng (Số văn bản, Ngày ký, Tên người ký, STT),
        // và PSM 6 cho các đoạn văn bản nhiều dòng (như Trích yếu nội dung)
        const isSingleLine = canvas.height <= 95 || (canvas.width / canvas.height >= 2.5);
        const psm = isSingleLine ? '7' : '6';
        try {
            await worker.setParameters({ tessedit_pageseg_mode: psm });
        } catch (_paramError) { /* best effort */ }
        const result = await worker.recognize(upscale(canvas), {}, { text: true });
        await ensureOnline();
        return normalizeText(result?.data?.text);
    }

    async function preparePage(pageCanvas, cache, pageNumber) {
        if (cache.has(pageNumber)) return cache.get(pageNumber);
        await ensureOnline();
        if (!root.OcrImage || typeof root.OcrImage.prepare !== 'function') {
            throw new Error('Chưa tải mô-đun làm sạch ảnh OCR.');
        }
        const prepared = await root.OcrImage.prepare(pageCanvas, { clean: true, deskew: true });
        cache.set(pageNumber, prepared.canvas);
        return prepared.canvas;
    }

    async function findAnchorPage(pdf, region, pageCache) {
        const anchor = normalizeAnchor(region?.anchor);
        if (!anchor) return null;
        const anchorKey = `anchor:${anchor}`;
        if (pageCache.has(anchorKey)) return pageCache.get(anchorKey) || null;
        for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
            await ensureOnline();
            let pageCanvas = pageCache.get(`raw:${pageNumber}`);
            if (!pageCanvas) {
                pageCanvas = await renderPage(pdf, pageNumber);
                pageCache.set(`raw:${pageNumber}`, pageCanvas);
            }
            const prepared = await preparePage(pageCanvas, pageCache, pageNumber);
            setStatus(`Đang tìm trang theo chữ mốc (${pageNumber}/${pdf.numPages})…`, 'primary');
            const textKey = `text:${pageNumber}`;
            const text = pageCache.has(textKey)
                ? pageCache.get(textKey)
                : normalizeAnchor(await recognize(prepared));
            pageCache.set(textKey, text);
            if (text.includes(anchor)) {
                pageCache.set(anchorKey, pageNumber);
                return pageNumber;
            }
        }
        pageCache.set(anchorKey, 0);
        return null;
    }

    async function resolveRegionPage(pdf, region, pageCache) {
        const mode = String(region?.page_mode || '');
        if (mode === 'first') return 1;
        if (mode === 'last') return pdf.numPages;
        if (mode === 'number') {
            const pageNumber = Number(region.page_number);
            return Number.isInteger(pageNumber) && pageNumber >= 1 && pageNumber <= pdf.numPages ? pageNumber : null;
        }
        if (mode === 'anchor') return findAnchorPage(pdf, region, pageCache);
        return null;
    }

    function getPageCanvasFromCache(pageCache, pageNumber) {
        return pageCache.get(pageNumber) || pageCache.get(`raw:${pageNumber}`) || null;
    }

    function getInputForColumn(col) {
        return document.getElementById(`col_${col - 1}`)
            || document.querySelector(`[name="col_${col - 1}"]`);
    }

    function getOcrFields(file) {
        if (!file.ocr_fields || typeof file.ocr_fields !== 'object' || Array.isArray(file.ocr_fields)) file.ocr_fields = {};
        return file.ocr_fields;
    }

    function getAppliedColumns(file) {
        if (!Array.isArray(file.ocr_applied_fields)) file.ocr_applied_fields = [];
        return file.ocr_applied_fields;
    }

    function applyProposals(file) {
        if (!file || file !== selectedFile()) return false;
        const fields = getOcrFields(file);
        const applied = getAppliedColumns(file);
        let changed = false;
        Object.entries(fields).forEach(([column, proposal]) => {
            const col = Number(column);
            const value = typeof proposal === 'string' ? proposal : proposal?.text;
            const input = Number.isInteger(col) ? getInputForColumn(col) : null;
            if (!input || !value || input.readOnly || applied.includes(col)) return;
            if (String(input.value || '').trim()) {
                // Never overwrite a value entered by a person.
                applied.push(col);
                changed = true;
                return;
            }
            input.value = value;
            input.dataset.ocrProposed = 'true';
            input.dataset.ocrColumn = String(col);
            applied.push(col);
            changed = true;
            if (typeof resizeDynamicFormInput === 'function') resizeDynamicFormInput(input);
        });
        if (changed) {
            safeSaveQueue();
            if (typeof saveFormDraft === 'function') {
                try { saveFormDraft(); } catch (error) { console.warn('Không thể lưu nháp OCR cục bộ:', error); }
            }
        }
        return changed;
    }

    function hydrateQueue() {
        // The project workspace can replace uploadedFilesQueue after a refresh.
        // Reconcile on every selection so OCR state survives that replacement.
        if (typeof currentUser === 'undefined' || !currentUser) return;
        let stored;
        try {
            stored = JSON.parse(localStorage.getItem(`pdfQueue_${currentUser.username}`) || '[]');
        } catch (_error) {
            stored = [];
        }
        if (!Array.isArray(stored) || typeof uploadedFilesQueue === 'undefined') return;
        const storedById = new Map(stored.map(file => [String(file.uuid || file.url || ''), file]));
        let changed = false;
        uploadedFilesQueue.forEach(file => {
            const old = storedById.get(String(file.uuid || file.url || ''));
            if (!old || (!old.ocr_status && !old.ocr_fields)) return;
            ['ocr_status', 'ocr_progress', 'ocr_message', 'ocr_fields', 'ocr_applied_fields'].forEach(key => {
                if (old[key] !== undefined) {
                    file[key] = old[key];
                    changed = true;
                }
            });
        });
        if (changed) safeSaveQueue();
    }

    async function processFile(file, position, total, force = false) {
        if (!file) return { status: 'skipped' };
        if (!force && file.ocr_status === 'done' && Number(file.ocr_progress) === 100) return { status: 'done' };
        await ensureOnline();
        const config = root.activeTemplateConfig || {};
        const columns = getOcrColumns(config);
        const regions = getRegions(config, columns);
        if (!columns.length || !regions.size) {
            setFileState(file, 'error', 0, 'Biểu mẫu chưa có vùng OCR.');
            return { status: 'error' };
        }

        setFileState(file, 'processing', 0);
        const fields = getOcrFields(file);
        const pageCache = new Map();
        let pdf = null;
        let processed = 0;
        const configuredRegions = columns.filter(col => regions.has(col));
        try {
            pdf = await openPdf(file);
            for (const col of configuredRegions) {
                await ensureOnline();
                const region = regions.get(col);
                if (!validRegion(region)) {
                    processed += 1;
                    setFileState(file, 'processing', processed / configuredRegions.length * 100);
                    continue;
                }
                const pageNumber = await resolveRegionPage(pdf, region, pageCache);
                if (pageNumber) {
                    let raw = getPageCanvasFromCache(pageCache, pageNumber);
                    if (!raw) {
                        raw = await renderPage(pdf, pageNumber);
                        pageCache.set(`raw:${pageNumber}`, raw);
                    }
                    const prepared = await preparePage(raw, pageCache, pageNumber);
                    const crop = root.OcrImage.crop(prepared, region.bbox, { snap: true });
                    const text = await recognize(crop);
                    if (text) {
                        fields[col] = { text, preprocessing: 'v1', page: pageNumber };
                        applyProposals(file);
                    }
                }
                processed += 1;
                const progress = processed / configuredRegions.length * 100;
                setFileState(file, 'processing', progress);
                setStatus(`Đang OCR ${position + 1}/${total}: ${fileLabel(file)} — ${Math.round(progress)}%`, 'primary');
            }
            setFileState(file, 'done', 100);
            return { status: 'done' };
        } catch (error) {
            if (error instanceof OcrPauseError || state.pauseRequested || state.paused) {
                setFileState(file, 'paused', file.ocr_progress || 0, 'Chờ kết nối hoặc người dùng tiếp tục.');
                throw new OcrPauseError();
            }
            setFileState(file, 'error', file.ocr_progress || 0, error.message || 'OCR thất bại.');
            return { status: 'error', error };
        } finally {
            if (pdf && typeof pdf.destroy === 'function') {
                try { await pdf.destroy(); } catch (_error) { /* best effort */ }
            }
        }
    }

    function queueFiles() {
        if (typeof uploadedFilesQueue === 'undefined') return [];
        return uploadedFilesQueue.filter(file => file && file.temporary_view !== true);
    }

    async function startQueue() {
        if (state.running) return state.queuePromise;
        hydrateQueue();
        if (!queueFiles().length) {
            setStatus('Chưa có PDF trong hàng chờ.', 'muted');
            setButtonState();
            return null;
        }
        if (!root.activeTemplateConfig) {
            setStatus('Đang tải cấu hình biểu mẫu; thử lại sau một lát.', 'warning');
            setButtonState();
            return null;
        }
        state.paused = false;
        state.pauseRequested = false;
        if (!(await heartbeat())) {
            state.paused = true;
            setButtonState();
            return null;
        }
        const files = queueFiles();
        const pending = files.filter(file => !(file.ocr_status === 'done' && Number(file.ocr_progress) === 100));
        if (!pending.length) {
            setStatus('Tất cả PDF đã có trạng thái ocr done.', 'success');
            setButtonState();
            return null;
        }
        state.running = true;
        setButtonState();
        state.queuePromise = (async () => {
            let completed = 0;
            let errors = 0;
            try {
                await ensureWorker();
                for (let index = 0; index < pending.length; index += 1) {
                    const result = await processFile(pending[index], index, pending.length);
                    if (result?.status === 'done') completed += 1;
                    else if (result?.status === 'error') errors += 1;
                }
                if (!state.paused && state.connected) {
                    setStatus(
                        errors
                            ? `Đã OCR ${completed}/${pending.length} PDF; ${errors} PDF cần xử lý lại.`
                            : `Đã OCR ${completed}/${pending.length} PDF. Kiểm tra kết quả rồi lưu nháp.`,
                        errors ? 'warning' : 'success',
                    );
                }
            } catch (error) {
                if (error instanceof OcrPauseError) {
                    state.paused = true;
                    setStatus('OCR tạm dừng — kiểm tra kết nối máy chủ rồi bấm Tiếp tục OCR.', 'warning');
                } else {
                    console.error('Employee OCR queue failed:', error);
                    setStatus(error.message || 'OCR bị dừng do lỗi không xác định.', 'danger');
                }
            } finally {
                state.running = false;
                state.pauseRequested = false;
                setButtonState();
            }
        })();
        await state.queuePromise;
        return state.queuePromise;
    }

    function pauseQueue() {
        if (!state.running) return;
        state.pauseRequested = true;
        state.paused = true;
        setStatus('Sẽ tạm dừng sau vùng OCR đang xử lý…', 'warning');
        setButtonState();
    }

    async function retrySelected() {
        if (state.running) return;
        const file = selectedFile();
        if (!file) return;
        if (!(await heartbeat())) {
            state.paused = true;
            setButtonState();
            return;
        }
        file.ocr_status = null;
        file.ocr_progress = 0;
        delete file.ocr_message;
        file.ocr_fields = {};
        file.ocr_applied_fields = [];
        safeSaveQueue();
        renderQueue(true);
        state.running = true;
        setButtonState();
        try {
            await ensureWorker();
            await processFile(file, 0, 1, true);
            setStatus(`Đã OCR lại ${fileLabel(file)}. Kiểm tra kết quả rồi lưu nháp.`, 'success');
        } catch (error) {
            if (error instanceof OcrPauseError) {
                state.paused = true;
                setStatus('OCR tạm dừng — kiểm tra kết nối máy chủ rồi bấm Tiếp tục OCR.', 'warning');
            } else {
                setStatus(error.message || 'Không thể OCR lại PDF.', 'danger');
            }
        } finally {
            state.running = false;
            state.pauseRequested = false;
            setButtonState();
        }
    }

    function appendStatus(button, file) {
        if (!button || !file || !file.ocr_status) return;
        const badge = document.createElement('span');
        badge.className = 'badge ms-2 text-nowrap';
        if (file.ocr_status === 'done') {
            badge.classList.add('bg-success');
            badge.textContent = 'ocr done';
        } else if (file.ocr_status === 'processing') {
            badge.classList.add('bg-info', 'text-dark');
            badge.textContent = `${Math.round(Number(file.ocr_progress) || 0)}%`;
        } else if (file.ocr_status === 'paused') {
            badge.classList.add('bg-warning', 'text-dark');
            badge.textContent = 'OCR tạm dừng';
        } else if (file.ocr_status === 'error') {
            badge.classList.add('bg-danger');
            badge.textContent = 'OCR lỗi';
            if (file.ocr_message) button.title = `${button.title || ''} — ${file.ocr_message}`;
        }
        button.appendChild(badge);
    }

    function selectionStarted(file) {
        if (!canRun()) return;
        hydrateQueue();
        if (file) applyProposals(file);
    }

    async function selected(file) {
        if (!canRun()) return;
        hydrateQueue();
        applyProposals(file);
        setButtonState();
    }

    function formReady() {
        if (!canRun()) return;
        const file = selectedFile();
        if (file) applyProposals(file);
    }

    function init() {
        const start = el('ocrStartButton');
        const resume = el('ocrResumeButton');
        const pause = el('ocrPauseButton');
        const retry = el('ocrRetryButton');
        if (!start || !resume || !pause || !retry) return;
        start.addEventListener('click', () => { void startQueue(); });
        resume.addEventListener('click', () => { void startQueue(); });
        pause.addEventListener('click', pauseQueue);
        retry.addEventListener('click', () => { void retrySelected(); });
        window.addEventListener('offline', () => {
            pauseForConnectivity();
        });
        window.addEventListener('online', () => { void heartbeat(); });
        state.heartbeatTimer = window.setInterval(() => { void heartbeat(); }, HEARTBEAT_INTERVAL_MS);
        void heartbeat();
        setButtonState();
    }

    root.EmployeeOcr = Object.freeze({
        appendStatus,
        selectionStarted,
        selected,
        formReady,
        hydrateQueue,
        start: startQueue,
        pause: pauseQueue,
        retry: retrySelected,
        state,
    });

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
    else init();
}(window));
