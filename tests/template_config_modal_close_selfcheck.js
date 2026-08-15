const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function createClassList(initial = []) {
    const values = new Set(initial);
    return {
        add(value) { values.add(value); },
        remove(value) { values.delete(value); },
        contains(value) { return values.has(value); },
    };
}

const events = [];
let hiddenHandler = null;
const backdrop = { remove() { events.push('backdrop-removed'); } };
const modalElement = {
    classList: createClassList(['show']),
    style: { display: 'block' },
    addEventListener(eventName, handler) {
        if (eventName === 'hidden.bs.modal') hiddenHandler = handler;
    },
    setAttribute() {},
    removeAttribute() {},
};
const modalInstance = {
    hide() {
        events.push('hide');
        modalElement.classList.remove('show');
        if (hiddenHandler) hiddenHandler();
    },
};
const elements = {
    configModal: modalElement,
    configJsonInput: { value: '{}' },
    configJsonError: { style: { display: 'none' }, innerText: '' },
};
const sandbox = {
    console,
    bootstrap: {
        Modal: {
            getInstance() { return modalInstance; },
        },
    },
    document: {
        body: {
            classList: createClassList(['modal-open']),
            style: { removeProperty() {} },
        },
        getElementById(id) { return elements[id] || null; },
        querySelector(selector) {
            if (selector === '.modal.show') return modalElement.classList.contains('show') ? modalElement : null;
            return null;
        },
        querySelectorAll(selector) { return selector === '.modal-backdrop' ? [backdrop] : []; },
    },
    alert(message) { events.push(`alert:${message}`); },
    apiCall: async () => ({ status: 'ok' }),
    setTimeout(callback) { callback(); },
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/template_config.js', 'utf8'), sandbox);
vm.runInContext('currentConfigTemplateId = 7; configModalInstance = bootstrap.Modal.getInstance(); buildConfigFromUI = () => {};', sandbox);

(async () => {
    await sandbox.saveTemplateConfig();
    assert.equal(events[0], 'hide');
    assert.equal(events.at(-1), 'alert:Đã lưu cấu hình biểu mẫu thành công!');
    assert.equal(modalElement.classList.contains('show'), false);
    assert.equal(documentBodyHasModalOpen(), false);
    assert(events.includes('backdrop-removed'));
    console.log('Template config modal close self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});

function documentBodyHasModalOpen() {
    return sandbox.document.body.classList.contains('modal-open');
}
