// Run with NODE_PATH pointing to a Playwright installation; no production login/DB needed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '../frontend');
function samplePdf() {
    let pdf = '%PDF-1.4\n';
    const offsets = [0];
    const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 500] /Contents 4 0 R /Resources << >> >>', '<< /Length 0 >>\nstream\n\nendstream'];
    objects.forEach((o, i) => { offsets.push(Buffer.byteLength(pdf)); pdf += `${i + 1} 0 obj\n${o}\nendobj\n`; });
    const xref = Buffer.byteLength(pdf);
    pdf += `xref\n0 5\n0000000000 65535 f \n${offsets.slice(1).map(n => String(n).padStart(10, '0') + ' 00000 n \n').join('')}trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
    return Buffer.from(pdf);
}
(async () => {
    const server = http.createServer((req, res) => {
        const pathname = new URL(req.url, 'http://localhost').pathname;
        const file = pathname === '/' ? path.join(root, 'admin.html') : path.resolve(root, '.' + pathname);
        if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) { res.writeHead(404).end(); return; }
        const type = path.extname(file);
        res.setHeader('Content-Type', ({ '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css' })[type] || 'application/octet-stream');
        res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; font-src 'self'; worker-src 'self' blob:");
        const content = fs.readFileSync(file);
        res.end(type === '.html' ? content.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '') : content);
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    let browser;
    try {
        browser = await chromium.launch({ channel: 'msedge', headless: true });
        const page = await browser.newPage();
        const errors = [];
        page.on('pageerror', e => errors.push(e.message));
        await page.goto(`http://127.0.0.1:${server.address().port}/`);
        for (const src of ['/vendor/bootstrap/js/bootstrap.bundle.min.js', '/js/template_config.js', '/js/ocr_image.js', '/js/ocr_config.js']) await page.addScriptTag({ url: src });
        await page.evaluate(() => {
            window.escapeHTML = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
            currentConfigTemplateId = 7;
            templateFields = [{ col: 1, label: 'Ngày văn bản' }, { col: 2, label: 'Số văn bản' }];
            currentConfigObj = { required_cols: [2] };
            populateColDropdowns(); renderVisualUiFromJSON(); initConfigModal(); configModalInstance.show();
        });
        assert.equal(await page.locator('.ocr-region-button').first().isDisabled(), false);
        assert.equal(await page.locator('.ocr-region-button').first().innerText(), 'Chọn vùng');
        await page.locator('.ocr-region-button').first().click();
        await page.locator('#ocrSampleFile').setInputFiles({ name: 'sample.pdf', mimeType: 'application/pdf', buffer: samplePdf() });
        await page.waitForFunction(() => !document.getElementById('ocrRegionApply').disabled);
        assert.match(await page.locator('#ocrSampleStatus').innerText(), /đã làm sạch/);
        await page.screenshot({ path: '.tools/ocr-region-editor-check.png' });
        const bounds = await page.locator('#ocrRegionCanvas').boundingBox();
        await page.mouse.move(bounds.x + bounds.width * .1, bounds.y + bounds.height * .1);
        await page.mouse.down();
        await page.mouse.move(bounds.x + bounds.width * .5, bounds.y + bounds.height * .3, { steps: 4 });
        await page.mouse.up();
        await page.locator('#ocrRegionApply').click();
        const config = await page.evaluate(() => JSON.parse(document.getElementById('configJsonInput').value));
        assert.deepEqual(config.required_cols, [2]);
        assert.deepEqual(config.ocr_cols, []);
        assert.equal(config.ocr_regions.length, 1);
        assert(Math.abs(config.ocr_regions[0].bbox[2] - .4) < .01);
        assert.equal(config.ocr_sample.sha256.length, 64);
        await page.locator('#chk_ocr_1').check();
        await page.locator('#chk_ocr_1').uncheck();
        assert.equal(await page.locator('.ocr-region-button').first().isDisabled(), false);
        assert.equal(await page.locator('#chk_required_2').isChecked(), true);
        await page.locator('#chk_ocr_1').check();
        await page.locator('.ocr-region-button').first().click();
        await page.locator('#ocrPageMode').selectOption('anchor');
        await page.waitForFunction(() => !document.getElementById('ocrRegionApply').disabled);
        await page.locator('#ocrRegionApply').click();
        assert(await page.locator('#ocrRegionError').innerText());
        await page.locator('#ocrAnchor').fill('Ngày ban hành');
        await page.locator('#ocrRegionApply').click();
        assert.equal(await page.evaluate(() => currentConfigObj.ocr_regions[0].page_mode), 'anchor');
        assert.deepEqual(errors, []);
        console.log('OCR browser check: PASS (PDF render, drag, save, toggle independence, anchor validation).');
    } finally { if (browser) await browser.close(); server.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
