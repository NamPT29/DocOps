const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function createClassList(initial = []) {
    const values = new Set(initial);
    return {
        contains(value) { return values.has(value); },
        toggle(value, force) {
            if (force === true) values.add(value);
            else if (force === false) values.delete(value);
            else if (values.has(value)) values.delete(value);
            else values.add(value);
        },
    };
}

const fields = {
    dashTotalDocs: { innerText: '0' },
    dashboardPeriodFilter: { value: 'week' },
    dashboardReferenceDate: { value: '2026-08-14', max: '' },
    dashboardReferenceDateGroup: { classList: createClassList() },
    dashboardDateRangeFields: { classList: createClassList(['d-none']) },
    dashboardStartDate: { value: '', max: '' },
    dashboardEndDate: { value: '', min: '', max: '' },
    dashPeriodDocs: { innerText: '0' },
    dashPeriodTitle: { textContent: '' },
    dashPeriodRange: { textContent: '' },
};
const apiUrls = [];
const authSource = fs.readFileSync('frontend/auth.js', 'utf8');
const adminHtml = fs.readFileSync('frontend/admin.html', 'utf8');
const sandbox = {
    console,
    URLSearchParams,
    apiUrls,
    alert() {},
    document: {
        addEventListener() {},
        getElementById(id) { return fields[id] || null; },
    },
    localStorage: {
        getItem() { return null; },
        setItem() {},
        removeItem() {},
    },
    window: { location: { pathname: '/admin.html' } },
    async fetch() {
        throw new Error('fetch should be replaced before dashboard loading');
    },
};

vm.createContext(sandbox);
vm.runInContext(authSource, sandbox);

(async () => {
    const dashboardPane = adminHtml.split('id="dashboard-pane"')[1].split('id="kpi-pane"')[0];
    const inventoryPane = adminHtml.split('id="inventory-pane"')[1].split('id="assignment-pane"')[0];
    assert.match(dashboardPane, /id="dashPeriodDocs"/);
    assert.match(dashboardPane, /option value="range">Từ ngày đến ngày<\/option>/);
    assert.match(dashboardPane, /type="datetime-local" id="dashboardStartDate"/);
    assert.match(dashboardPane, /type="datetime-local" id="dashboardEndDate"/);
    assert.doesNotMatch(inventoryPane, /id="dashPeriodDocs"/);

    const day = sandbox.getDashboardPeriodRange('day', '2026-08-14');
    assert.deepEqual(JSON.parse(JSON.stringify(day)), {
        startDate: '2026-08-14',
        endDate: '2026-08-14',
        startUtc: '2026-08-13T17:00:00.000',
        endUtc: '2026-08-14T16:59:59.999',
    });

    const week = sandbox.getDashboardPeriodRange('week', '2026-08-14');
    assert.equal(week.startDate, '2026-08-10');
    assert.equal(week.endDate, '2026-08-16');
    assert.equal(week.startUtc, '2026-08-09T17:00:00.000');
    assert.equal(week.endUtc, '2026-08-16T16:59:59.999');

    const month = sandbox.getDashboardPeriodRange('month', '2026-08-14');
    assert.equal(month.startDate, '2026-08-01');
    assert.equal(month.endDate, '2026-08-31');
    assert.equal(month.startUtc, '2026-07-31T17:00:00.000');
    assert.equal(month.endUtc, '2026-08-31T16:59:59.999');

    vm.runInContext(`
        currentUser = { role: 'admin' };
        apiCall = async (url) => {
            apiUrls.push(url);
            if (url === '/api/submissions') {
                return { status: 'ok', data: [], pagination: { total: 1088 } };
            }
            if (url.startsWith('/api/submissions?')) {
                return { status: 'ok', data: [], pagination: { total: 37 } };
            }
            return { status: 'ok', data: [] };
        };
        populateTemplatesDropdown = async () => {};
    `, sandbox);

    await sandbox.fetchDashboardStats();
    assert.equal(fields.dashTotalDocs.innerText, 1088);
    assert.equal(fields.dashPeriodDocs.innerText, 37);
    assert.equal(fields.dashPeriodTitle.textContent, 'Hồ sơ nhập trong tuần');
    assert.equal(fields.dashPeriodRange.textContent, '10/08/2026 – 16/08/2026');

    const filteredUrl = apiUrls.find(url => url.startsWith('/api/submissions?'));
    const params = new URLSearchParams(filteredUrl.split('?')[1]);
    assert.equal(params.get('start_date'), '2026-08-09T17:00:00.000');
    assert.equal(params.get('end_date'), '2026-08-16T16:59:59.999');
    assert.equal(params.get('page_size'), '1');

    const customRange = sandbox.getDashboardCustomRange('2026-08-01T08:30', '2026-08-14T17:45');
    assert.deepEqual(JSON.parse(JSON.stringify(customRange)), {
        startDateTime: '2026-08-01T08:30',
        endDateTime: '2026-08-14T17:45',
        startUtc: '2026-08-01T01:30:00.000',
        endUtc: '2026-08-14T10:45:00.000',
    });
    assert.equal(sandbox.getDashboardCustomRange('2026-08-14T17:46', '2026-08-14T17:45'), null);

    apiUrls.length = 0;
    fields.dashboardPeriodFilter.value = 'range';
    fields.dashboardStartDate.value = '2026-08-01T08:30';
    fields.dashboardEndDate.value = '2026-08-14T17:45';
    await sandbox.fetchDashboardStats();

    assert.equal(fields.dashboardReferenceDateGroup.classList.contains('d-none'), true);
    assert.equal(fields.dashboardDateRangeFields.classList.contains('d-none'), false);
    assert.equal(fields.dashPeriodDocs.innerText, 37);
    assert.equal(fields.dashPeriodTitle.textContent, 'Hồ sơ nhập từ ngày đến ngày');
    assert.equal(fields.dashPeriodRange.textContent, '08:30 01/08/2026 – 17:45 14/08/2026');
    const customUrl = apiUrls.find(url => url.startsWith('/api/submissions?'));
    const customParams = new URLSearchParams(customUrl.split('?')[1]);
    assert.equal(customParams.get('start_date'), '2026-08-01T01:30:00.000');
    assert.equal(customParams.get('end_date'), '2026-08-14T10:45:00.000');
    console.log('Dashboard period filter self-check: OK');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
