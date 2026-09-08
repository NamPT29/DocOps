const assert = require('node:assert/strict');
const fs = require('node:fs');

const authSource = fs.readFileSync('frontend/auth.js', 'utf8');
const loginSource = fs.readFileSync('frontend/login.js', 'utf8');

assert(authSource.includes("fetch('/api/session/heartbeat'"));
assert(authSource.includes("fetch('/api/session/closing'"));
assert(authSource.includes("window.addEventListener('pagehide'"));
assert(authSource.includes("window.addEventListener('storage'"));
assert(authSource.includes('sendSessionHeartbeat(false)'));
assert(authSource.includes('sessionIdleTimeoutMs()'));
assert(authSource.includes('expireLocalSession('));
assert(authSource.includes("localStorage.removeItem('token')"));
assert(loginSource.includes("localStorage.setItem('sessionIdleTimeoutMinutes'"));

for (const [page, version] of [
    ['frontend/admin.html', 'auth.js?v=102.00'],
    ['frontend/index.html', 'auth.js?v=102.00'],
]) {
    assert(fs.readFileSync(page, 'utf8').includes(version));
}

console.log('Auth session lifecycle self-check: OK');
