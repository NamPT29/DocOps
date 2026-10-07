// js/my_work.js

var projectWorkflowProjectId = null;
var myWorkHasProjects = false;

/**
 * Hiện tab "Việc của tôi" khi người dùng có việc quy trình. auth.js
 * (configureCapabilityUI) ẩn cả thanh tab với người không có quyền nhập/kiểm tra
 * và gọi lại hàm này ở cuối, nên thứ tự chạy của hai bên không quan trọng.
 */
function applyMyWorkVisibility() {
    const item = document.getElementById('myWorkTabItem');
    if (!item) return;
    item.classList.toggle('d-none', !myWorkHasProjects);
    if (!myWorkHasProjects) return;
    const tabs = document.getElementById('employeeTabs');
    if (tabs) tabs.classList.remove('d-none');
    const notice = document.getElementById('noAssignmentNotice');
    if (notice) notice.classList.add('d-none');
    const hasOtherTab = ['inputTabItem', 'dataTabItem', 'reviewTabItem'].some(id => {
        const node = document.getElementById(id);
        return node && !node.classList.contains('d-none');
    });
    if (hasOtherTab) return;
    // Chỉ làm việc quy trình: mở luôn tab này.
    document.querySelectorAll('#appTabsContent > .tab-pane').forEach(pane => pane.classList.remove('show', 'active'));
    document.querySelectorAll('#employeeTabs .nav-link').forEach(link => link.classList.remove('active'));
    const pane = document.getElementById('my-work-pane');
    if (pane) pane.classList.add('show', 'active');
    const button = document.getElementById('my-work-tab');
    if (button) button.classList.add('active');
}

async function refreshProjectWorkflow() {
    await fetchMyWork();
}

async function fetchMyProjects() {
    try {
        const response = await authFetch('/api/workflow/my-projects');
        if (!response.ok) throw new Error('Không thể tải danh sách dự án');
        
        const data = await response.json();
        const myWorkProjectSelect = document.getElementById('myWorkProjectSelect');
        
        myWorkHasProjects = Boolean(data.data && data.data.length > 0);
        applyMyWorkVisibility();
        if (myWorkHasProjects) {
            myWorkProjectSelect.replaceChildren();
            
            data.data.forEach(proj => {
                const option = document.createElement('option');
                option.value = proj.project_id;
                option.textContent = proj.name;
                myWorkProjectSelect.appendChild(option);
            });
            
            
            await fetchMyWork();
        }
    } catch (error) {
        console.error('Lỗi tải danh sách dự án Việc của tôi:', error);
    }
}

async function fetchMyWork() {
    const projectId = document.getElementById('myWorkProjectSelect').value;
    if (!projectId) return;
    
    const tbody = document.querySelector('#myWorkTable tbody');
    setMyWorkMessage(tbody, 'Đang tải...', 'text-muted');
    
    try {
        const response = await authFetch(`/api/projects/${projectId}/workflow/my-work`);
        if (!response.ok) throw new Error('Lỗi tải việc của tôi');
        
        const data = await response.json();
        renderMyWorkTable(data.data);
    } catch (error) {
        setMyWorkMessage(tbody, `Lỗi: ${error.message}`, 'text-danger');
    }
}

function setMyWorkMessage(tbody, text, className) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 4;
    td.className = `text-center ${className}`;
    td.textContent = text;
    tr.appendChild(td);
    tbody.replaceChildren(tr);
}

const STAGE_LABELS = {
    arrangement: "Chỉnh lý",
    scan: "Scan",
    scan_qc: "Check scan",
    entry_qc: "Check nhập"
};

const STATUS_LABELS = {
    pending: "Chờ",
    in_progress: "Đang làm",
    rejected: "Bị trả lại",
    done: "Xong",
    
    // entry_qc gate codes
    entry_qc_not_finalized: "Chưa chốt vòng 1",
    entry_qc_failed: "Vòng 1 vượt ngưỡng, chờ Admin duyệt",
    entry_qc_round2_required: "Cần lấy mẫu vòng 2",
    entry_qc_round2_pending: "Vòng 2 chưa chốt",
    entry_qc_round2_failed: "Vòng 2 vượt ngưỡng, chờ Admin duyệt"
};

function renderMyWorkTable(items) {
    const tbody = document.querySelector('#myWorkTable tbody');
    tbody.replaceChildren();
    
    if (!items || items.length === 0) {
        setMyWorkMessage(tbody, 'Không có việc cần làm', 'text-muted');
        return;
    }
    
    items.forEach(item => {
        const tr = document.createElement('tr');
        
        const tdCase = document.createElement('td');
        tdCase.textContent = item.display_name || item.case_key;
        tr.appendChild(tdCase);
        
        const tdStage = document.createElement('td');
        tdStage.textContent = STAGE_LABELS[item.stage_key] || item.stage_key;
        tr.appendChild(tdStage);
        
        const tdStatus = document.createElement('td');
        const statusLabel = item.gate_code ? STATUS_LABELS[item.gate_code] : STATUS_LABELS[item.status] || item.status;
        tdStatus.textContent = statusLabel || item.status;
        tr.appendChild(tdStatus);
        
        const tdAction = document.createElement('td');
        renderActionButtons(tdAction, item);
        tr.appendChild(tdAction);
        
        tbody.appendChild(tr);
    });
}

function renderActionButtons(td, item) {
    const { stage_key, status, case_id, display_name, gate_code } = item;
    const cid = case_id;
    const btnClass = 'btn btn-sm btn-primary me-2 mb-1';
    
    if (stage_key === 'arrangement') {
        if (status === 'pending' || status === 'rejected') {
            const btn = document.createElement('button');
            btn.className = btnClass;
            btn.textContent = 'Bắt đầu';
            btn.addEventListener('click', () => transitionStage(cid, stage_key, 'start'));
            td.appendChild(btn);
        } else if (status === 'in_progress') {
            const btn = document.createElement('button');
            btn.className = 'btn btn-sm btn-success me-2 mb-1';
            btn.textContent = 'Hoàn tất';
            btn.addEventListener('click', () => transitionStage(cid, stage_key, 'complete'));
            td.appendChild(btn);
        }
    } else if (stage_key === 'scan') {
        if (['pending', 'rejected', 'in_progress'].includes(status)) {
            const btnSubmit = document.createElement('button');
            btnSubmit.className = 'btn btn-sm btn-outline-primary me-2 mb-1';
            btnSubmit.textContent = 'Nộp S';
            btnSubmit.addEventListener('click', () => {
                projectWorkflowProjectId = document.getElementById('myWorkProjectSelect').value;
                if (typeof openScanSubmit === 'function') {
                    openScanSubmit(cid, display_name);
                }
            });
            td.appendChild(btnSubmit);
        }
        if (status === 'in_progress') {
            const btn = document.createElement('button');
            btn.className = 'btn btn-sm btn-success me-2 mb-1';
            btn.textContent = 'Hoàn tất scan';
            btn.addEventListener('click', () => {
                if (confirm('Xác nhận hoàn tất scan hộp này?')) {
                    transitionStage(cid, stage_key, 'complete');
                }
            });
            td.appendChild(btn);
        }
    } else if (stage_key === 'scan_qc') {
        const btnMatch = document.createElement('button');
        btnMatch.className = 'btn btn-sm btn-outline-info me-2 mb-1';
        btnMatch.textContent = 'Xem so khớp';
        btnMatch.addEventListener('click', () => {
            projectWorkflowProjectId = document.getElementById('myWorkProjectSelect').value;
            if (typeof openScanMatch === 'function') {
                openScanMatch(cid, display_name);
            }
        });
        td.appendChild(btnMatch);
        
        if (status === 'pending' || status === 'rejected') {
            const btn = document.createElement('button');
            btn.className = btnClass;
            btn.textContent = 'Bắt đầu';
            btn.addEventListener('click', () => transitionStage(cid, stage_key, 'start'));
            td.appendChild(btn);
        } else if (status === 'in_progress') {
            const btnComplete = document.createElement('button');
            btnComplete.className = 'btn btn-sm btn-success me-2 mb-1';
            btnComplete.textContent = 'Duyệt';
            btnComplete.addEventListener('click', () => {
                if (confirm('Xác nhận hộp đạt kiểm tra scan?')) {
                    transitionStage(cid, stage_key, 'complete');
                }
            });
            td.appendChild(btnComplete);
            
            const btnReject = document.createElement('button');
            btnReject.className = 'btn btn-sm btn-danger mb-1';
            btnReject.textContent = 'Trả lại';
            btnReject.addEventListener('click', () => {
                const reason = (prompt('Lý do trả lại (bắt buộc):') || '').trim();
                if (reason) {
                    transitionStage(cid, stage_key, 'reject', reason);
                }
            });
            td.appendChild(btnReject);
        }
    } else if (stage_key === 'entry_qc') {
        // Lát này chưa có nút cho entry_qc
    }
}

async function transitionStage(caseId, stageKey, action, reason = null) {
    const pid = document.getElementById('myWorkProjectSelect').value;
    if (!pid) return;
    
    try {
        const body = { action };
        if (reason) body.reason = reason;
        
        const response = await authFetch(`/api/projects/${pid}/workflow/cases/${caseId}/stages/${stageKey}/transition`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            const detail = err.detail;
            const message = typeof detail === 'string' ? detail : (detail && detail.message) ? detail.message : 'Đã có lỗi xảy ra';
            alert(message);
        } else {
            await fetchMyWork();
        }
    } catch (error) {
        alert('Lỗi: ' + error.message);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // Add event listeners when DOM is loaded
    const btnRefresh = document.getElementById('btnRefreshMyWork');
    if (btnRefresh) {
        btnRefresh.addEventListener('click', fetchMyWork);
    }
    
    const projectSelect = document.getElementById('myWorkProjectSelect');
    if (projectSelect) {
        projectSelect.addEventListener('change', fetchMyWork);
    }
    
    // Auto-fetch if user is logged in
    // This assumes fetchMyProjects is called from somewhere or we can call it here if we have a token
    if (localStorage.getItem('token')) {
        fetchMyProjects();
    }
});
