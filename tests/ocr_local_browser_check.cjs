// Browser smoke test for the local OCR assets and immutable image cleanup.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '../frontend');
const mime = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.wasm': 'application/wasm',
    '.gz': 'application/gzip',
};

(async () => {
    const server = http.createServer((req, res) => {
        const pathname = new URL(req.url, 'http://localhost').pathname;
        if (pathname === '/test.html') {
            res.setHeader('Content-Type', mime['.html']);
            res.end('<!doctype html><html><body><div id="status"></div><script src="/js/ocr_image.js"></script><script src="/vendor/tesseract/tesseract.min.js"></script></body></html>');
            return;
        }
        const file = path.resolve(root, `.${pathname}`);
        if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
            res.writeHead(404).end();
            return;
        }
        res.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
        res.end(fs.readFileSync(file));
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    let browser;
    try {
        browser = await chromium.launch({ channel: 'msedge', headless: true });
        const page = await browser.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.goto(`http://127.0.0.1:${server.address().port}/test.html`);
        const result = await page.evaluate(async () => {
            const source = document.createElement('canvas');
            source.width = 240;
            source.height = 80;
            const context = source.getContext('2d');
            context.fillStyle = '#fff';
            context.fillRect(0, 0, source.width, source.height);
            context.fillStyle = '#111';
            context.font = '28px Arial';
            context.fillText('OCR TEST 123', 18, 48);
            const before = context.getImageData(0, 0, source.width, source.height).data[0];
            const prepared = await window.OcrImage.prepare(source, { clean: true, deskew: true });
            const after = context.getImageData(0, 0, source.width, source.height).data[0];
            const worker = await window.Tesseract.createWorker('eng', 1, {
                workerPath: '/vendor/tesseract/worker.min.js',
                corePath: '/vendor/tesseract/core',
                langPath: '/vendor/tesseract/lang',
                cachePath: 'ocr-smoke-v1',
                cacheMethod: 'write',
                gzip: true,
            });
            const recognized = await worker.recognize(prepared.canvas, {}, { text: true });

            // Test text snapping on a canvas with text and an intentionally misaligned box
            const snapCanvas = document.createElement('canvas');
            snapCanvas.width = 400;
            snapCanvas.height = 200;
            const snapCtx = snapCanvas.getContext('2d');
            snapCtx.fillStyle = '#fff';
            snapCtx.fillRect(0, 0, snapCanvas.width, snapCanvas.height);
            snapCtx.fillStyle = '#000';
            snapCtx.font = '24px Arial';
            // Text drawn inside range roughly x=[100, 240], y=[80, 110]
            snapCtx.fillText('TEST-SNAP-123', 100, 100);

            // Misaligned box: shifted left and down, e.g. x=0.20 (80px), y=0.35 (70px), w=0.45 (180px), h=0.25 (50px)
            const looseBbox = [0.20, 0.35, 0.45, 0.25];
            const croppedSnapped = window.OcrImage.crop(snapCanvas, looseBbox, { snap: true });
            const croppedNoSnap = window.OcrImage.crop(snapCanvas, looseBbox, { snap: false });
            const snappedRecognized = await worker.recognize(croppedSnapped, {}, { text: true });

            // Blank area test: should safely fallback to looseBbox without error
            const blankBbox = [0.01, 0.01, 0.1, 0.1];
            const blankCrop = window.OcrImage.crop(snapCanvas, blankBbox, { snap: true });

            await worker.terminate();
            return {
                sameSize: prepared.canvas.width === source.width && prepared.canvas.height === source.height,
                sourceUnchanged: before === after,
                text: recognized?.data?.text || '',
                snappedRecognized: snappedRecognized?.data?.text || '',
                snappedWidth: croppedSnapped.width,
                noSnapWidth: croppedNoSnap.width,
                blankWidth: blankCrop.width,
            };
        });
        assert.equal(result.sameSize, true);
        assert.equal(result.sourceUnchanged, true);
        assert.match(result.text, /OCR/i);
        assert.match(result.snappedRecognized, /TEST-SNAP/i);
        assert(result.snappedWidth > 0);
        assert(result.blankWidth > 0);
        assert.deepEqual(errors, []);
        console.log(`Local OCR browser check: PASS (${JSON.stringify(result)})`);
    } finally {
        if (browser) await browser.close();
        server.close();
    }
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
