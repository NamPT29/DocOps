const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const projectRoot = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(projectRoot, 'frontend', 'login.html'), 'utf8');
const script = fs.readFileSync(path.join(projectRoot, 'frontend', 'login.js'), 'utf8');

assert(!/<script\b(?![^>]*\bsrc\s*=)[^>]*>/i.test(html), 'Login page must not contain inline scripts.');
assert(!/\bon[a-z]+\s*=/i.test(html), 'Login page must not contain inline event handlers.');
assert(!/<style\b/i.test(html), 'Login page must not contain inline style elements.');
assert(!/\bstyle\s*=/i.test(html), 'Login page must not contain inline style attributes.');
assert(/<script\s+src=["']login\.js\?v=[^"']+["']><\/script>/i.test(html), 'Login page must load its external script.');

function element(initial = {}) {
    const listeners = {};
    return {
        value: '',
        hidden: true,
        textContent: '',
        focusCalled: false,
        ...initial,
        addEventListener(type, handler) { listeners[type] = handler; },
        focus() { this.focusCalled = true; },
        dispatch(type, event = {}) { return listeners[type]?.(event); },
    };
}

const elements = {
    loginUsername: element({ value: 'employee' }),
    loginPassword: element({ value: 'secret' }),
    loginButton: element(),
    loginError: element(),
};
let readyHandler;
const storage = new Map();
const context = {
    document: {
        addEventListener(type, handler) { if (type === 'DOMContentLoaded') readyHandler = handler; },
        getElementById(id) { return elements[id] || null; },
    },
    fetch: async () => ({ json: async () => ({ status: 'ok', token: 'token-1', user: { role: 'user' } }) }),
    localStorage: {
        setItem(key, value) { storage.set(key, value); },
        getItem(key) { return storage.get(key); },
    },
    sessionStorage: {
        getItem() { return null; },
        removeItem() {},
    },
    window: { location: { href: '' } },
};

vm.runInNewContext(script, context, { filename: 'frontend/login.js' });
assert.equal(typeof readyHandler, 'function', 'Login script must initialize after DOM readiness.');
readyHandler();
assert(elements.loginUsername.focusCalled, 'Login script must preserve username autofocus behavior.');

(async () => {
    await elements.loginButton.dispatch('click');
    assert.equal(storage.get('token'), 'token-1');
    assert.equal(context.window.location.href, '/index.html');

    context.fetch = async () => ({ json: async () => ({ status: 'error', message: 'Sai thông tin' }) });
    await elements.loginPassword.dispatch('keyup', { key: 'Enter' });
    assert.equal(elements.loginError.textContent, 'Sai thông tin');
    assert.equal(elements.loginError.hidden, false);
    console.log('Login CSP self-check passed.');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
