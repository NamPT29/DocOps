const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

class FakeElement {
    constructor(tagName) {
        this.tagName = tagName;
        this.children = [];
        this.dataset = {};
        this.style = {};
        this.value = '';
        this.listeners = {};
        const classes = new Set();
        this.classList = {
            add: (...names) => names.forEach(name => classes.add(name)),
            remove: (...names) => names.forEach(name => classes.delete(name)),
            contains: name => classes.has(name),
            toggle: (name, force) => force ? classes.add(name) : classes.delete(name),
        };
        Object.defineProperty(this, 'className', {
            get: () => Array.from(classes).join(' '),
            set: value => {
                classes.clear();
                String(value || '').split(/\s+/).filter(Boolean).forEach(name => classes.add(name));
            },
        });
    }

    appendChild(child) {
        this.children.push(child);
        child.parentNode = this;
        return child;
    }

    addEventListener(type, listener) {
        this.listeners[type] = listener;
    }

    setAttribute(name, value) {
        this[name] = value;
    }
}

const sandbox = {
    assert,
    alert(message) {
        throw new Error(message);
    },
    console,
    currentUser: { id: 1, username: 'tester' },
    document: {
        createElement: tagName => new FakeElement(tagName),
        getElementById: () => null,
        querySelectorAll: () => [],
    },
    localStorage: {
        getItem: () => null,
        removeItem() {},
        setItem() {},
    },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

const source = [
    fs.readFileSync('frontend/js/pdf_handler.js', 'utf8'),
    fs.readFileSync('frontend/js/form_renderer.js', 'utf8'),
    `
    saveFormDraft = () => {};
    let pdfLinkUiUpdates = 0;
    updatePdfLinkUI = () => { pdfLinkUiUpdates++; };
    activeDocumentRelativePath = 'du-an/ho-so/bao-cao.pdf';
    isPdfLinked = false;

    const fieldGroup = _buildFieldGroup(
        { name: 'col_2', label: 'Đường dẫn PDF', col_index: 2 },
        { linked_pdf_path: { enabled: true, col: 3, folder_levels: 1 } },
        {},
    );
    const inputGroup = fieldGroup.children[0].children[1];
    const pathInput = inputGroup.children[0];
    const linkButton = inputGroup.children[1];

    linkButton.listeners.click();
    assert.equal(pathInput.value, 'ho-so/bao-cao.pdf');
    assert.equal(isPdfLinked, true, 'Lưu liên kết phải bật metadata PDF cho báo cáo');
    assert.equal(pdfLinkUiUpdates, 1, 'Nhãn trạng thái PDF phải được đồng bộ sau khi liên kết');

    linkButton.listeners.click();
    assert.equal(pathInput.value, '');
    assert.equal(isPdfLinked, false, 'Hủy liên kết phải bỏ metadata PDF khỏi báo cáo');
    assert.equal(pdfLinkUiUpdates, 2, 'Nhãn trạng thái PDF phải được đồng bộ sau khi hủy');
    `,
].join('\n');

vm.runInContext(source, sandbox, { filename: 'linked_pdf_path_button_selfcheck.js' });
console.log('Linked PDF path button self-check: OK');
