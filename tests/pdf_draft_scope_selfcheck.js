const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const storage = new Map();
const fields = [
    { name: 'col_0', value: '' },
    { name: 'col_1', value: '' },
];
const dataForm = {
    querySelectorAll() { return fields; },
};
const sandbox = {
    console,
    currentUser: { id: 2, username: 'member' },
    window: {
        activeProjectId: 7,
        activeTemplateId: 11,
        activeTemplateConfig: { cover_cols: [] },
    },
    localStorage: {
        getItem(key) { return storage.has(key) ? storage.get(key) : null; },
        setItem(key, value) { storage.set(key, String(value)); },
        removeItem(key) { storage.delete(key); },
    },
    document: {
        getElementById(id) { return id === 'dataForm' ? dataForm : null; },
        querySelectorAll() { return fields; },
    },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/form_renderer.js', 'utf8'), sandbox);

const pdfA = { uuid: 'pdf-a', project_id: 7, template_id: 11 };
const pdfB = { uuid: 'pdf-b', project_id: 7, template_id: 11 };
const pdfC = { relative_path: 'folder/pdf-c.pdf', project_id: 7, template_id: 11 };

sandbox.setActivePdfDraftFile(pdfA);
const keyA = sandbox.getDraftStorageKey();
assert(keyA.includes('7') && keyA.includes('11') && keyA.includes('pdf-a'));
fields[0].value = 'A cover';
fields[1].value = 'A data';
sandbox.saveFormDraft();

sandbox.setActivePdfDraftFile(pdfB);
assert.notEqual(keyA, sandbox.getDraftStorageKey(), 'each PDF must have an isolated draft key');
sandbox.applyDraftForActivePdf();
assert.deepEqual(fields.map(field => field.value), ['', ''], 'cover_cols=[] must clear every field for a new PDF');

sandbox.setActivePdfDraftFile(pdfA);
sandbox.applyDraftForActivePdf();
assert.deepEqual(fields.map(field => field.value), ['A cover', 'A data'], 'returning to a PDF must restore its draft');
fields[1].value = 'unsaved change';
sandbox.applyDraftForActivePdf();
assert.equal(fields[1].value, 'unsaved change', 'reselecting the same PDF must not erase in-progress data');

sandbox.window.activeTemplateConfig = { cover_cols: [1] };
fields[0].value = 'shared cover';
fields[1].value = 'stale data';
sandbox.setActivePdfDraftFile(pdfC);
sandbox.applyDraftForActivePdf();
assert.deepEqual(fields.map(field => field.value), ['shared cover', ''], 'configured cover columns may carry over, other fields must clear');

console.log('PDF draft scope self-check: OK');
