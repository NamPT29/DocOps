const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const tableBody = { innerHTML: '' };
const calls = [];
const sandbox = {
    console,
    escapeHTML: value => String(value || ''),
    document: {
        getElementById(id) {
            return id === 'dictionaryItemsTableBody' ? tableBody : null;
        },
    },
    apiCall: async url => {
        calls.push(url);
        const page = Number(new URL(url, 'http://localhost').searchParams.get('page'));
        return page === 1
            ? {
                data: [{ id: 1, code: '001', value: 'Một' }],
                pagination: { page: 1, page_size: 100, total: 2, total_pages: 2 },
            }
            : {
                data: [{ id: 2, code: '002', value: 'Hai' }],
                pagination: { page: 2, page_size: 100, total: 2, total_pages: 2 },
            };
    },
};

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/js/template_config.js', 'utf8'), sandbox);

vm.runInContext('currentDictId = 7; fetchDictionaryItems()', sandbox)
    .then(() => {
        assert.deepEqual(calls, [
            '/api/dictionaries/7/items?page=1&page_size=100',
            '/api/dictionaries/7/items?page=2&page_size=100',
        ]);
        assert(tableBody.innerHTML.includes('001'));
        assert(tableBody.innerHTML.includes('002'));
        console.log('Dictionary pagination self-check: OK');
    })
    .catch(error => {
        console.error(error);
        process.exitCode = 1;
    });
