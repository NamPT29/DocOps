const fs = require('fs');
const jsdom = require('jsdom');
const { JSDOM } = jsdom;

const html = `
<!DOCTYPE html>
<html>
<body>
    <li id="myWorkTabItem" class="d-none"></li>
    <select id="myWorkProjectSelect"></select>
    <table id="myWorkTable"><tbody></tbody></table>
</body>
</html>
`;

const dom = new JSDOM(html);
global.document = dom.window.document;
global.window = dom.window;

let myWorkJs = fs.readFileSync('frontend/js/my_work.js', 'utf-8');

global.authFetchRequests = [];
global.authFetchMockResponses = {};
global.authFetch = async (url, options = {}) => {
    global.authFetchRequests.push({ url, options });
    if (global.authFetchMockResponses[url]) {
        return global.authFetchMockResponses[url](options);
    }
    return { ok: true, json: async () => ({}) };
};

global.openScanSubmitCalls = [];
global.openScanSubmit = (caseId, displayName) => {
    global.openScanSubmitCalls.push({ caseId, displayName });
};

global.alertCalls = [];
global.alert = (msg) => { global.alertCalls.push(msg); };

global.confirmMock = true;
global.confirm = () => global.confirmMock;

global.promptMock = null;
global.prompt = () => global.promptMock;

global.localStorage = {
    getItem: () => null,
    setItem: () => {}
};

eval(myWorkJs);

async function runTests() {
    console.log("Running selfcheck...");

    // Test (a) my-projects [] -> tab vẫn ẩn
    global.authFetchMockResponses['/api/workflow/my-projects'] = () => ({
        ok: true, json: async () => ({ data: [] })
    });
    await fetchMyProjects();
    if (!document.getElementById('myWorkTabItem').classList.contains('d-none')) {
        throw new Error("Test a1 failed: Tab should be hidden");
    }

    // Test (a) có dự án -> tab hiện, ô chọn có đủ dự án
    global.authFetchMockResponses['/api/workflow/my-projects'] = () => ({
        ok: true, json: async () => ({
            data: [
                { project_id: 1, name: "Project 1" },
                { project_id: 2, name: "Project 2" }
            ]
        })
    });
    global.authFetchMockResponses['/api/projects/1/workflow/my-work'] = () => ({
        ok: true, json: async () => ({ data: [] })
    });
    await fetchMyProjects();
    if (document.getElementById('myWorkTabItem').classList.contains('d-none')) {
        throw new Error("Test a2 failed: Tab should be visible");
    }
    if (document.getElementById('myWorkProjectSelect').options.length !== 2) {
        throw new Error("Test a3 failed: Select should have 2 options");
    }

    // Test (b) bảng có đúng nút theo từng bước/trạng thái ở mục 3 (kiểm chữ trên nút).
    const mockMyWorkData = [
        { case_id: 1, display_name: "Case 1", stage_key: "arrangement", status: "pending" },
        { case_id: 2, display_name: "Case 2", stage_key: "arrangement", status: "in_progress" },
        { case_id: 3, display_name: "Case 3", stage_key: "scan", status: "in_progress" },
        { case_id: 4, display_name: "Case 4", stage_key: "scan_qc", status: "in_progress" },
        { case_id: 5, display_name: "Case 5", stage_key: "entry_qc", gate_code: "entry_qc_not_finalized" },
        { case_id: 6, display_name: "Case 6", stage_key: "scan_qc", status: "pending" }
    ];
    global.authFetchMockResponses['/api/projects/1/workflow/my-work'] = () => ({
        ok: true, json: async () => ({ data: mockMyWorkData })
    });
    await fetchMyWork();
    
    const rows = document.querySelectorAll('#myWorkTable tbody tr');
    const getButtons = (tr) => Array.from(tr.querySelectorAll('button')).map(b => b.textContent);
    
    if (getButtons(rows[0]).join(',') !== 'Bắt đầu') throw new Error("Test b1 failed");
    if (getButtons(rows[1]).join(',') !== 'Hoàn tất') throw new Error("Test b2 failed");
    if (getButtons(rows[2]).join(',') !== 'Nộp S,Hoàn tất scan') throw new Error("Test b3 failed");
    if (getButtons(rows[3]).join(',') !== 'Xem so khớp,Duyệt,Trả lại') throw new Error("Test b4 failed");
    if (getButtons(rows[5]).join(',') !== 'Xem so khớp,Bắt đầu') throw new Error("Test b5 failed");
    
    // Test (c) Trả lại
    const rejectBtn = Array.from(rows[3].querySelectorAll('button')).find(b => b.textContent === 'Trả lại');
    
    global.promptMock = null;
    const reqCountBefore = global.authFetchRequests.length;
    rejectBtn.click();
    if (global.authFetchRequests.length !== reqCountBefore) throw new Error("Test c1 failed: Should not send request if prompt is null");
    
    global.promptMock = "Thiếu trang";
    global.authFetchMockResponses['/api/projects/1/workflow/cases/4/stages/scan_qc/transition'] = () => ({
        ok: true, json: async () => ({})
    });
    rejectBtn.click();
    await new Promise(r => setTimeout(r, 100)); // wait for async
    const lastReq = global.authFetchRequests.find(r => r.options && r.options.method === 'POST');
    if (lastReq.url !== '/api/projects/1/workflow/cases/4/stages/scan_qc/transition') throw new Error("Test c2 failed: URL mismatch. Actual: " + lastReq.url);
    const bodyObj = JSON.parse(lastReq.options.body);
    if (bodyObj.action !== 'reject' || bodyObj.reason !== 'Thiếu trang') throw new Error("Test c3 failed: body mismatch");

    // Test (d) Duyệt -> POST {action: "complete"}; phản hồi 409 {detail: {code, message}} -> alert đúng message
    const completeBtn = Array.from(rows[3].querySelectorAll('button')).find(b => b.textContent === 'Duyệt');
    global.authFetchMockResponses['/api/projects/1/workflow/cases/4/stages/scan_qc/transition'] = () => ({
        ok: false, status: 409, json: async () => ({ detail: { code: "err", message: "Chỉ Admin được duyệt" } })
    });
    global.alertCalls = [];
    completeBtn.click();
    await new Promise(r => setTimeout(r, 10)); // wait for async
    if (global.alertCalls[0] !== "Chỉ Admin được duyệt") throw new Error("Test d1 failed: alert mismatch: " + global.alertCalls[0]);
    
    // thành công -> bảng được tải lại
    global.authFetchMockResponses['/api/projects/1/workflow/cases/4/stages/scan_qc/transition'] = () => ({
        ok: true, json: async () => ({})
    });
    let fetchMyWorkCalled = 0;
    global.authFetchMockResponses['/api/projects/1/workflow/my-work'] = () => {
        fetchMyWorkCalled++;
        return { ok: true, json: async () => ({ data: mockMyWorkData }) };
    };
    completeBtn.click();
    await new Promise(r => setTimeout(r, 10)); // wait for async
    if (fetchMyWorkCalled === 0) throw new Error("Test d2 failed: Should reload table");

    // Test (e) Nộp S
    const nopsBtn = Array.from(rows[2].querySelectorAll('button')).find(b => b.textContent === 'Nộp S');
    global.openScanSubmitCalls = [];
    nopsBtn.click();
    if (global.openScanSubmitCalls.length === 0) throw new Error("Test e1 failed: openScanSubmit not called");
    if (global.openScanSubmitCalls[0].caseId !== 3 || global.openScanSubmitCalls[0].displayName !== 'Case 3') throw new Error("Test e2 failed");
    if (projectWorkflowProjectId != 1) throw new Error("Test e3 failed: projectWorkflowProjectId mismatch");

    // Test (f) entry_qc: hiện nhãn theo gate_code, không có nút
    if (getButtons(rows[4]).length !== 0) throw new Error("Test f1 failed: Should have no buttons");
    const statusText = rows[4].querySelectorAll('td')[2].textContent;
    if (statusText !== "Chưa chốt vòng 1") throw new Error("Test f2 failed: status text mismatch");

    console.log("Selfcheck passed!");
}

runTests().catch(error => { console.error(error); process.exitCode = 1; });
