const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const sandbox = {};
sandbox.window = sandbox;
vm.createContext(sandbox);

const source = fs.readFileSync('frontend/js/pdf_link_state.js', 'utf8');
vm.runInContext(source, sandbox);

assert.equal(sandbox.pdfLinkState.isLinked(), false);
assert.equal(sandbox.pdfLinkState.setLinked(true), true);
assert.equal(sandbox.pdfLinkState.isLinked(), true);
assert.equal(sandbox.pdfLinkState.toggle(), false);
assert.equal(sandbox.pdfLinkState.isLinked(), false);

const originalState = sandbox.pdfLinkState;
vm.runInContext(source, sandbox);
assert.equal(sandbox.pdfLinkState, originalState, 'Nạp lại script không được làm mất trạng thái hiện tại');

console.log('PDF link state self-check: OK');
