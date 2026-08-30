const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class FakeElement {
    constructor(tagName) {
        this.tagName = tagName;
        this.children = [];
        this.dataset = {};
        this.style = {};
        this.listeners = {};
        this.attributes = {};
        this.value = '';
        const classes = new Set();
        this.classList = {
            add: (...names) => names.forEach(name => classes.add(name)),
            remove: (...names) => names.forEach(name => classes.delete(name)),
            contains: name => classes.has(name),
            replace: (oldName, newName) => {
                if (classes.delete(oldName)) classes.add(newName);
            },
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
        (this.listeners[type] ||= []).push(listener);
    }

    setAttribute(name, value) {
        this.attributes[name] = String(value);
        if (name === 'class') {
            this.className = value;
        } else {
            this[name] = String(value);
        }
    }

    getAttribute(name) {
        return this.attributes[name] ?? null;
    }
}

const documentListeners = {};
const sandbox = {
    console,
    document: {
        createElement: tagName => new FakeElement(tagName),
        addEventListener(type, listener) {
            (documentListeners[type] ||= []).push(listener);
        },
        getElementById: () => null,
        getElementsByClassName: () => [],
    },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/form_renderer.js', 'utf8'), sandbox);

const freeTextGroup = sandbox._buildFieldGroup(
    { name: 'col_0', label: 'Họ tên', col_index: 0, type: 'text' },
    {},
    {},
);
const freeTextInput = freeTextGroup.children[0].children[1];
assert.equal(freeTextInput.getAttribute('autocomplete'), 'on', 'free text must keep browser autocomplete');
assert.equal(freeTextInput.listeners.keydown, undefined, 'free text must not get custom dropdown handlers');

const dropdownGroup = sandbox._buildFieldGroup(
    {
        name: 'col_1',
        label: 'Dân tộc',
        col_index: 1,
        type: 'dropdown',
        options: ['Kinh', 'Tày'],
    },
    {},
    {},
);
const dropdownInput = dropdownGroup.children[0].children[1];
assert.equal(dropdownInput.getAttribute('autocomplete'), 'off', 'custom dropdown must disable browser autocomplete');
assert(dropdownInput.listeners.keydown?.length, 'custom dropdown keyboard handler must be attached');
assert(dropdownInput.listeners.focus?.length, 'custom dropdown focus handler must be attached');
assert(documentListeners.click?.length, 'custom dropdown outside-click handler must be attached');

dropdownInput.listeners.input.at(-1).call(dropdownInput, {});
assert.equal(dropdownInput.parentNode.children.at(-1).className, 'autocomplete-items');

for (const htmlPath of ['frontend/index.html', 'frontend/admin.html', 'frontend/temp.html']) {
    const html = fs.readFileSync(htmlPath, 'utf8');
    assert.match(html, /<script src="js\/form_renderer\.js\?v=[^"]+"><\/script>/, `${htmlPath} must cache-bust form_renderer.js`);
}

console.log('Form renderer autocomplete self-check: OK');
