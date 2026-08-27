const assert = require('assert');
const fs = require('fs');
const path = require('path');

const projectRoot = path.resolve(__dirname, '..');
const frontendRoot = path.join(projectRoot, 'frontend');

function listFiles(directory, predicate) {
    const files = [];
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
        const fullPath = path.join(directory, entry.name);
        if (entry.isDirectory()) {
            if (entry.name !== 'vendor') files.push(...listFiles(fullPath, predicate));
        } else if (predicate(fullPath)) {
            files.push(fullPath);
        }
    }
    return files;
}

function count(source, pattern) {
    return (source.match(pattern) || []).length;
}

const findings = {
    inlineScripts: 0,
    eventHandlerAttributes: 0,
    inlineStyleElements: 0,
    inlineStyleAttributes: 0,
    remoteAssets: 0,
};

for (const filePath of listFiles(frontendRoot, file => file.endsWith('.html'))) {
    const source = fs.readFileSync(filePath, 'utf8');
    findings.inlineScripts += count(source, /<script\b(?![^>]*\bsrc\s*=)[^>]*>/gi);
    findings.eventHandlerAttributes += count(source, /\bon[a-z]+\s*=/gi);
    findings.inlineStyleElements += count(source, /<style\b/gi);
    findings.inlineStyleAttributes += count(source, /\bstyle\s*=/gi);
    findings.remoteAssets += count(source, /\b(?:src|href)\s*=\s*["']https?:\/\//gi);
}

// First-party scripts generate additional HTML at runtime. Attribute-bearing
// markup is subject to CSP in the same way as markup in the page source.
for (const filePath of listFiles(frontendRoot, file => file.endsWith('.js'))) {
    const source = fs.readFileSync(filePath, 'utf8');
    findings.eventHandlerAttributes += count(source, /<[^>]*\bon[a-z]+\s*=/gi);
    findings.inlineStyleAttributes += count(source, /<[^>]*\bstyle\s*=/gi);
    findings.remoteAssets += count(source, /\b(?:src|href)\s*=\s*["']https?:\/\//gi);
}

const headerSource = fs.readFileSync(path.join(projectRoot, 'server', 'security_headers.py'), 'utf8');
const hasEnforcingPolicy = /^\s*["']Content-Security-Policy["']\s*:/m.test(headerSource);
const hasReportOnlyPolicy = /^\s*["']Content-Security-Policy-Report-Only["']\s*:/m.test(headerSource);
const hasHsts = /^\s*["']Strict-Transport-Security["']\s*:/m.test(headerSource);
const blockerCount = findings.inlineScripts
    + findings.eventHandlerAttributes
    + findings.inlineStyleElements
    + findings.inlineStyleAttributes
    + findings.remoteAssets;

if (blockerCount > 0) {
    assert(hasReportOnlyPolicy, 'CSP findings must remain observable while enforcement is deferred.');
    assert(!hasEnforcingPolicy, `Blocking CSP is unsafe with ${blockerCount} detected frontend findings.`);
} else {
    assert(hasEnforcingPolicy, 'A clean static scan must enable the enforcing CSP header.');
    assert(!hasReportOnlyPolicy, 'Report-only CSP must be retired once enforcement is enabled.');
}
assert(!hasHsts, 'HSTS requires a confirmed HTTPS-only deployment configuration.');
assert.equal(findings.remoteAssets, 0, 'Frontend assets must be served locally before CSP enforcement.');
assert(!headerSource.includes("'unsafe-inline'"), 'Do not normalize inline code with unsafe-inline.');

const readiness = blockerCount > 0 ? 'enforcement deferred' : 'static scan ready for browser validation';
console.log(`CSP readiness self-check: ${readiness}; ${JSON.stringify(findings)}`);
