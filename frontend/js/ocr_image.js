/*
 * Client-side OCR image preparation.
 *
 * The source canvas is treated as immutable.  The helper deliberately keeps
 * the output dimensions and normalized coordinates stable so a region saved
 * by the administrator can be reused for every PDF page.
 */
(function (root) {
    'use strict';

    const VERSION = 'v1';
    const MAX_SKEW_DEGREES = 4;
    const SKEW_STEP_DEGREES = 0.5;

    function assertCanvas(canvas) {
        if (!canvas || typeof canvas.getContext !== 'function') {
            throw new TypeError('OCR cần một canvas ảnh hợp lệ.');
        }
        return canvas;
    }

    function throwIfAborted(signal) {
        if (signal?.aborted) {
            const error = new DOMException('OCR image preparation aborted', 'AbortError');
            throw error;
        }
    }

    function clamp(value, min, max) {
        return Math.max(min, Math.min(max, value));
    }

    function copyCanvas(source) {
        assertCanvas(source);
        const output = document.createElement('canvas');
        output.width = Math.max(1, Number(source.width) || 1);
        output.height = Math.max(1, Number(source.height) || 1);
        output.getContext('2d', { willReadFrequently: true }).drawImage(source, 0, 0);
        return output;
    }

    function cleanPixels(canvas, signal) {
        throwIfAborted(signal);
        const context = canvas.getContext('2d', { willReadFrequently: true });
        const image = context.getImageData(0, 0, canvas.width, canvas.height);
        const { data, width, height } = image;
        const totalPixels = width * height;
        const gray = new Uint8Array(totalPixels);

        for (let index = 0, pixel = 0; index < data.length; index += 4, pixel += 1) {
            gray[pixel] = Math.round(
                data[index] * 0.299 + data[index + 1] * 0.587 + data[index + 2] * 0.114,
            );
        }

        // Ước tính mức độ sáng nền giấy scan từ biểu đồ tần suất (histogram)
        const hist = new Int32Array(256);
        const sampleStep = Math.max(1, Math.floor(totalPixels / 10000));
        for (let p = 0; p < totalPixels; p += sampleStep) {
            hist[gray[p]] += 1;
        }

        let bgLuminance = 240;
        let maxPeak = 0;
        for (let lum = 180; lum < 255; lum += 1) {
            if (hist[lum] > maxPeak) {
                maxPeak = hist[lum];
                bgLuminance = lum;
            }
        }

        // Ngưỡng làm sạch nền giấy: các điểm gần màu nền giấy được đưa về trắng tinh 255
        const bgThreshold = Math.max(195, Math.min(245, bgLuminance - 15));
        const inkThreshold = Math.max(80, Math.min(160, bgLuminance - 60));

        const cleaned = new Uint8ClampedArray(data.length);
        for (let y = 0; y < height; y += 1) {
            if ((y & 63) === 0) throwIfAborted(signal);
            const rowOffset = y * width;
            for (let x = 0; x < width; x += 1) {
                const pixelIndex = rowOffset + x;
                const offset = pixelIndex * 4;
                const value = gray[pixelIndex];

                // Tuyệt đối không xóa điểm ảnh cô lập để bảo toàn dấu nặng (.), dấu chấm i, j
                let out;
                if (value >= bgThreshold) {
                    out = 255;
                } else if (value <= inkThreshold) {
                    out = clamp(Math.round(value * 0.85), 0, 255);
                } else {
                    const ratio = (value - inkThreshold) / (bgThreshold - inkThreshold);
                    out = clamp(Math.round(inkThreshold * 0.85 + ratio * (255 - inkThreshold * 0.85)), 0, 255);
                }

                cleaned[offset] = out;
                cleaned[offset + 1] = out;
                cleaned[offset + 2] = out;
                cleaned[offset + 3] = 255;
            }
        }
        context.putImageData(new ImageData(cleaned, width, height), 0, 0);
        return canvas;
    }

    function collectDarkPixels(canvas, signal) {
        const context = canvas.getContext('2d', { willReadFrequently: true });
        const image = context.getImageData(0, 0, canvas.width, canvas.height);
        const width = image.width;
        const height = image.height;
        const step = Math.max(1, Math.ceil(Math.max(width, height) / 700));
        const points = [];
        const data = image.data;
        for (let y = 0; y < height; y += step) {
            if ((y & 63) === 0) throwIfAborted(signal);
            for (let x = 0; x < width; x += step) {
                const offset = (y * width + x) * 4;
                const luminance = data[offset] * 0.299 + data[offset + 1] * 0.587 + data[offset + 2] * 0.114;
                if (luminance < 160) points.push([x, y]);
                if (points.length >= 7000) return points;
            }
        }
        return points;
    }

    function estimateDeskewAngle(canvas, signal) {
        const points = collectDarkPixels(canvas, signal);
        if (points.length < 30) return 0;
        const cx = canvas.width / 2;
        const cy = canvas.height / 2;
        let bestAngle = 0;
        let bestScore = -Infinity;
        const bins = Math.max(16, Math.ceil(canvas.height / 8));

        for (let degrees = -MAX_SKEW_DEGREES; degrees <= MAX_SKEW_DEGREES + 0.001; degrees += SKEW_STEP_DEGREES) {
            throwIfAborted(signal);
            const radians = degrees * Math.PI / 180;
            const sine = Math.sin(radians);
            const cosine = Math.cos(radians);
            const rows = new Uint16Array(bins);
            points.forEach(([x, y]) => {
                // Canvas uses a downward-positive Y axis. This is the same
                // transform used by ctx.rotate below.
                const rotatedY = sine * (x - cx) + cosine * (y - cy) + cy;
                const row = clamp(Math.floor(rotatedY / canvas.height * bins), 0, bins - 1);
                rows[row] += 1;
            });
            let score = 0;
            rows.forEach(count => { score += count * count; });
            if (score > bestScore) {
                bestScore = score;
                bestAngle = radians;
            }
        }
        return Math.abs(bestAngle) < 0.15 * Math.PI / 180 ? 0 : bestAngle;
    }

    function rotateSameSize(canvas, angle, signal) {
        throwIfAborted(signal);
        if (!angle) return canvas;
        const output = document.createElement('canvas');
        output.width = canvas.width;
        output.height = canvas.height;
        const context = output.getContext('2d');
        context.fillStyle = '#fff';
        context.fillRect(0, 0, output.width, output.height);
        context.translate(output.width / 2, output.height / 2);
        context.rotate(angle);
        context.drawImage(canvas, -canvas.width / 2, -canvas.height / 2);
        return output;
    }

    async function prepare(sourceCanvas, options = {}) {
        const source = assertCanvas(sourceCanvas);
        const signal = options.signal;
        throwIfAborted(signal);
        // Always copy before touching pixels. The PDF.js render canvas and the
        // administrator's preview are never modified in place.
        let output = copyCanvas(source);
        if (options.clean !== false) output = cleanPixels(output, signal);
        const angle = options.deskew === false ? 0 : estimateDeskewAngle(output, signal);
        output = rotateSameSize(output, angle, signal);
        // Yield once so the UI can paint progress before a large page begins
        // OCR. This is still a local operation; no file is uploaded.
        await Promise.resolve();
        throwIfAborted(signal);
        return { canvas: output, angle, preprocessing: VERSION, worker: false };
    }

    function detectTextBounds(canvas, options = {}) {
        assertCanvas(canvas);
        const ctx = canvas.getContext('2d', { willReadFrequently: true });
        const { width, height, data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const threshold = Number.isFinite(options.threshold) ? options.threshold : 165;

        let minX = width;
        let minY = height;
        let maxX = -1;
        let maxY = -1;
        let inkCount = 0;

        const rowInk = new Uint16Array(height);
        const colInk = new Uint16Array(width);

        for (let y = 0; y < height; y += 1) {
            for (let x = 0; x < width; x += 1) {
                const idx = (y * width + x) * 4;
                const lum = data[idx] * 0.299 + data[idx + 1] * 0.587 + data[idx + 2] * 0.114;
                if (lum < threshold) {
                    rowInk[y] += 1;
                    colInk[x] += 1;
                }
            }
        }

        // Phát hiện đường kẻ bảng hoặc gạch chân: bất kỳ hàng/cột nào có tỷ lệ mực > 62%
        // nằm trong khoảng 25% sát mép thì được xác định là đường kẻ bảng/gạch chân
        const borderBandY = Math.max(8, Math.floor(height * 0.25));
        const borderBandX = Math.max(8, Math.floor(width * 0.25));
        const isBorderLineY = y => rowInk[y] > width * 0.62 && (y < borderBandY || y > height - borderBandY);
        const isBorderLineX = x => colInk[x] > height * 0.62 && (x < borderBandX || x > width - borderBandX);

        for (let y = 0; y < height; y += 1) {
            if (isBorderLineY(y) || rowInk[y] < 2) continue;
            for (let x = 0; x < width; x += 1) {
                if (isBorderLineX(x) || colInk[x] < 2) continue;
                const idx = (y * width + x) * 4;
                const lum = data[idx] * 0.299 + data[idx + 1] * 0.587 + data[idx + 2] * 0.114;
                if (lum < threshold) {
                    inkCount += 1;
                    if (x < minX) minX = x;
                    if (x > maxX) maxX = x;
                    if (y < minY) minY = y;
                    if (y > maxY) maxY = y;
                }
            }
        }

        if (inkCount < 15 || minX > maxX || minY > maxY) {
            return null;
        }

        return { minX, minY, maxX, maxY, inkCount };
    }

    function crop(sourceCanvas, bbox, options = {}) {
        const source = assertCanvas(sourceCanvas);
        const values = Array.isArray(bbox) ? bbox.map(Number) : [];
        const x = clamp(Number.isFinite(values[0]) ? values[0] : 0, 0, 1);
        const y = clamp(Number.isFinite(values[1]) ? values[1] : 0, 0, 1);
        const maxWidth = 1 - x;
        const maxHeight = 1 - y;
        const width = clamp(Number.isFinite(values[2]) ? values[2] : maxWidth, 0, maxWidth);
        const height = clamp(Number.isFinite(values[3]) ? values[3] : maxHeight, 0, maxHeight);

        let pixelX = Math.floor(x * source.width);
        let pixelY = Math.floor(y * source.height);
        let pixelWidth = Math.max(1, Math.ceil(width * source.width));
        let pixelHeight = Math.max(1, Math.ceil(height * source.height));

        const shouldSnap = options.snap !== false;
        if (shouldSnap && pixelWidth >= 10 && pixelHeight >= 10) {
            const padX = Math.round(pixelWidth * (Number(options.paddingPercent) || 0.08));
            const padY = Math.round(pixelHeight * (Number(options.paddingPercent) || 0.08));

            const searchX = Math.max(0, pixelX - padX);
            const searchY = Math.max(0, pixelY - padY);
            const searchW = Math.min(source.width - searchX, pixelWidth + padX * 2);
            const searchH = Math.min(source.height - searchY, pixelHeight + padY * 2);

            const searchCanvas = document.createElement('canvas');
            searchCanvas.width = searchW;
            searchCanvas.height = searchH;
            searchCanvas.getContext('2d').drawImage(
                source,
                searchX, searchY, searchW, searchH,
                0, 0, searchW, searchH,
            );

            const bounds = detectTextBounds(searchCanvas, options);
            if (bounds) {
                const margin = Number.isFinite(options.margin) ? options.margin : 10;
                const snappedX = Math.max(0, searchX + bounds.minX - margin);
                const snappedY = Math.max(0, searchY + bounds.minY - margin);
                const snappedRight = Math.min(source.width, searchX + bounds.maxX + 1 + margin);
                const snappedBottom = Math.min(source.height, searchY + bounds.maxY + 1 + margin);

                pixelX = snappedX;
                pixelY = snappedY;
                pixelWidth = Math.max(1, snappedRight - snappedX);
                pixelHeight = Math.max(1, snappedBottom - snappedY);
            }
        }

        // Bổ sung lề đệm trắng (quiet zone) xung quanh để mô hình Tesseract nhận dạng chữ đầu/cuối chuẩn xác
        const quietZone = Number.isFinite(options.quietZone) ? Math.max(0, options.quietZone) : 12;
        const output = document.createElement('canvas');
        output.width = pixelWidth + quietZone * 2;
        output.height = pixelHeight + quietZone * 2;
        const outCtx = output.getContext('2d');
        outCtx.fillStyle = '#ffffff';
        outCtx.fillRect(0, 0, output.width, output.height);
        outCtx.drawImage(
            source,
            pixelX,
            pixelY,
            Math.max(1, Math.min(source.width - pixelX, pixelWidth)),
            Math.max(1, Math.min(source.height - pixelY, pixelHeight)),
            quietZone,
            quietZone,
            pixelWidth,
            pixelHeight,
        );
        return output;
    }

    root.OcrImage = Object.freeze({ VERSION, prepare, crop, estimateDeskewAngle, detectTextBounds });
}(window));
