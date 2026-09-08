// =============================================================================
// PROJECT UPLOAD & CHUNKED ENGINE (Số hóa All in One)
// Chuyên trách: Duyệt thư mục PDF, tính SHA-256, chia chunk và upload tiến trình
// =============================================================================

var selectedProjectFileRows = [];
var selectedProjectRootName = '';
var selectedProjectMaximumDepth = 0;
var projectUpdateTargetId = null;

function setProjectUploadStatus(message, tone = 'muted') {
    const status = document.getElementById('projectUploadStatus');
    if (!status) return;
    status.textContent = message || '';
    status.className = `small mt-3 text-${tone}`;
}

function setProjectUploadProgress(done, total) {
    const wrapper = document.getElementById('projectUploadProgressWrap');
    const bar = document.getElementById('projectUploadProgress');
    if (!wrapper || !bar) return;

    if (total === 0) {
        wrapper.classList.add('d-none');
        return;
    }
    wrapper.classList.remove('d-none');

    const percent = Math.min(100, Math.round((done / total) * 100));
    bar.style.width = `${percent}%`;
    bar.textContent = `${percent}%`;
    bar.setAttribute('aria-valuenow', String(percent));

    // Tự động ẩn thanh trạng thái sau 1.5 giây khi hoàn thành
    if (percent === 100) {
        if (window.projectUploadProgressTimeout) clearTimeout(window.projectUploadProgressTimeout);
        window.projectUploadProgressTimeout = setTimeout(() => {
            wrapper.classList.add('d-none');
        }, 1500);
    }
}

function projectRelativeFileRow(file) {
    const browserPath = String(file.webkitRelativePath || file.name || '').replace(/\\/g, '/');
    const parts = browserPath.split('/').filter(Boolean);
    const rootName = parts.length > 1 ? parts[0] : '';
    const relativeParts = parts.length > 1 ? parts.slice(1) : parts;
    return {
        file,
        rootName,
        relativePath: relativeParts.join('/'),
        folderDepth: Math.max(0, relativeParts.length - 1),
    };
}

function handleProjectFolderSelection() {
    const picker = document.getElementById('projectFolderPicker');
    const summary = document.getElementById('projectFolderSummary');
    const rows = Array.from((picker && picker.files) || [])
        .filter(file => String(file.name || '').toLocaleLowerCase('vi-VN').endsWith('.pdf'))
        .map(projectRelativeFileRow);
    selectedProjectFileRows = rows;
    selectedProjectRootName = rows[0] ? rows[0].rootName : '';
    selectedProjectMaximumDepth = rows.reduce((maximum, row) => Math.max(maximum, row.folderDepth), 0);

    if (!rows.length) {
        if (summary) summary.textContent = 'Folder không có PDF.';
        updateProjectLevelOptions();
        return;
    }
    const roots = new Set(rows.map(row => row.rootName));
    if (roots.size !== 1 || !selectedProjectRootName) {
        selectedProjectFileRows = [];
        if (summary) summary.textContent = 'Không xác định được một folder gốc duy nhất.';
        updateProjectLevelOptions();
        return;
    }
    const nameInput = document.getElementById('projectNameInput');
    if (nameInput && !nameInput.value.trim()) nameInput.value = selectedProjectRootName;
    if (summary) {
        summary.textContent = `${rows.length.toLocaleString('vi-VN')} PDF; ${selectedProjectMaximumDepth} cấp folder bên dưới “${selectedProjectRootName}”.`;
    }
    updateProjectLevelOptions();
    const resume = getProjectUploadResumeState();
    if (resume && resume.root_name === selectedProjectRootName) {
        setProjectUploadStatus(`Đã tìm thấy phiên tải dở của dự án #${resume.project_id}; bấm nút để tiếp tục.`, 'warning');
    }
}

function updateProjectLevelOptions() {
    const caseSelect = document.getElementById('projectCaseLevel');
    const reportSelect = document.getElementById('projectReportLevel');
    if (!caseSelect || !reportSelect) return;
    const previousCase = Number(caseSelect.value || 0);
    caseSelect.replaceChildren();
    if (selectedProjectMaximumDepth < 1) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = 'Folder cần ít nhất 1 cấp hồ sơ';
        caseSelect.appendChild(option);
    } else {
        for (let level = 1; level <= selectedProjectMaximumDepth; level += 1) {
            const option = document.createElement('option');
            option.value = String(level);
            option.textContent = `Cấp ${level}`;
            caseSelect.appendChild(option);
        }
        caseSelect.value = String(
            previousCase >= 1 && previousCase <= selectedProjectMaximumDepth ? previousCase : 1,
        );
    }

    const caseLevel = Number(caseSelect.value || 0);
    reportSelect.replaceChildren();
    for (let level = caseLevel + 1; level <= selectedProjectMaximumDepth; level += 1) {
        const option = document.createElement('option');
        option.value = String(level);
        option.textContent = `Cấp ${level}`;
        reportSelect.appendChild(option);
    }
    if (!reportSelect.options.length) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = 'Không còn cấp folder sâu hơn';
        reportSelect.appendChild(option);
    }
    syncProjectReportMode();
}

function syncProjectReportMode() {
    const mode = document.getElementById('projectReportMode');
    const group = document.getElementById('projectReportLevelGroup');
    const reportSelect = document.getElementById('projectReportLevel');
    const folderMode = !mode || mode.value === 'folder_level';
    if (group) group.classList.toggle('d-none', !folderMode);
    if (reportSelect) reportSelect.disabled = !folderMode;
}

function prepareProjectFolderUpdate(projectId) {
    const project = (typeof projectManagementProjects !== 'undefined' ? projectManagementProjects : []).find(item => Number(item.id) === Number(projectId));
    if (!project) return alert('Không tìm thấy dự án trong danh sách hiện tại.');
    projectUpdateTargetId = Number(project.id);
    clearProjectUploadResumeState();
    selectedProjectFileRows = [];
    selectedProjectRootName = '';
    selectedProjectMaximumDepth = 0;
    const picker = document.getElementById('projectFolderPicker');
    if (picker) picker.value = '';
    const summary = document.getElementById('projectFolderSummary');
    if (summary) summary.textContent = `Chọn lại folder gốc “${project.root_folder_name}”.`;
    const banner = document.getElementById('projectUpdateTargetBanner');
    if (banner) banner.classList.remove('d-none');
    const name = document.getElementById('projectUpdateTargetName');
    if (name) name.textContent = project.name;
    const buttonText = document.getElementById('createProjectButtonText');
    if (buttonText) buttonText.textContent = 'Cập nhật PDF cho dự án đã chọn';
    setProjectUploadStatus('Chọn lại folder để đối chiếu manifest với dữ liệu hiện có.', 'warning');
    document.getElementById('projects-pane')?.scrollIntoView({behavior: 'smooth', block: 'start'});
    if (picker) picker.click();
}

function cancelProjectFolderUpdate() {
    projectUpdateTargetId = null;
    clearProjectUploadResumeState();
    const banner = document.getElementById('projectUpdateTargetBanner');
    if (banner) banner.classList.add('d-none');
    const buttonText = document.getElementById('createProjectButtonText');
    if (buttonText) buttonText.textContent = 'Tạo dự án và tải PDF';
    setProjectUploadStatus('');
}

function projectUploadResumeStorageKey() {
    return 'projectUploadResumeV1';
}

function getProjectUploadResumeState() {
    try {
        return JSON.parse(localStorage.getItem(projectUploadResumeStorageKey()) || 'null');
    } catch (_) {
        return null;
    }
}

function saveProjectUploadResumeState(state) {
    localStorage.setItem(projectUploadResumeStorageKey(), JSON.stringify(state));
}

function clearProjectUploadResumeState() {
    localStorage.removeItem(projectUploadResumeStorageKey());
}

async function sha256ProjectFile(file) {
    const buffer = await file.arrayBuffer();
    const digest = await crypto.subtle.digest('SHA-256', buffer);
    return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
}

async function buildProjectManifest() {
    const manifest = [];
    for (let index = 0; index < selectedProjectFileRows.length; index += 1) {
        const row = selectedProjectFileRows[index];
        setProjectUploadStatus(`Đang kiểm tra SHA-256: ${index + 1}/${selectedProjectFileRows.length}`);
        setProjectUploadProgress(index, selectedProjectFileRows.length);
        manifest.push({
            relative_path: row.relativePath,
            size: row.file.size,
            sha256: await sha256ProjectFile(row.file),
            last_modified: String(row.file.lastModified || ''),
        });
    }
    setProjectUploadProgress(selectedProjectFileRows.length, selectedProjectFileRows.length);
    return manifest;
}

async function uploadOneProjectFile(session, fileInfo, fileByPath, progressState) {
    const file = fileByPath.get(String(fileInfo.relative_path).toLocaleLowerCase('vi-VN'));
    if (!file) throw new Error(`Không tìm thấy file đã chọn: ${fileInfo.relative_path}`);
    let offset = Number(fileInfo.next_offset || 0);
    while (offset < file.size) {
        const chunk = file.slice(offset, Math.min(file.size, offset + session.chunk_size_bytes));
        let responseData = null;
        let lastError = null;
        for (let attempt = 1; attempt <= 5; attempt += 1) {
            try {
                const response = await authFetch(
                    `/api/project-upload-sessions/${encodeURIComponent(session.id)}/files/${Number(fileInfo.file_id)}`,
                    {
                        method: 'PUT',
                        headers: {'X-Upload-Offset': String(offset)},
                        body: chunk,
                    },
                );
                if (!response) throw new Error('Phiên đăng nhập đã hết hạn');
                responseData = await response.json().catch(() => ({}));
                if (response.status === 429 && attempt < 5) {
                    const retryAfterSeconds = Math.max(
                        1,
                        Number(response.headers.get('Retry-After') || 1),
                    );
                    setProjectUploadStatus(
                        `Máy chủ đang điều tiết tốc độ; tự tiếp tục sau ${retryAfterSeconds} giây...`,
                        'warning',
                    );
                    await new Promise(resolve => setTimeout(
                        resolve,
                        retryAfterSeconds * 1000,
                    ));
                    continue;
                }
                if (!response.ok) {
                    throw new Error(formatApiErrorDetail(responseData.detail || responseData.message));
                }
                break;
            } catch (error) {
                lastError = error;
                if (attempt < 5) await new Promise(resolve => setTimeout(resolve, attempt * 500));
            }
        }
        if (!responseData || responseData.status !== 'ok') throw lastError || new Error('Không tải được chunk');
        const nextOffset = Number(responseData.next_offset);
        if (!Number.isFinite(nextOffset) || nextOffset <= offset) throw new Error('Máy chủ trả offset không hợp lệ');
        progressState.doneBytes += nextOffset - offset;
        offset = nextOffset;
        setProjectUploadProgress(progressState.doneBytes, progressState.totalBytes);
        setProjectUploadStatus(
            `Đang tải ${progressState.finishedFiles + 1}/${progressState.totalFiles}: ${fileInfo.relative_path}`,
        );
    }
    progressState.finishedFiles += 1;
}

async function uploadProjectSessionFiles(session) {
    const fileByPath = new Map(
        selectedProjectFileRows.map(row => [row.relativePath.toLocaleLowerCase('vi-VN'), row.file]),
    );
    const queue = session.files.filter(item => item.state !== 'uploaded');
    const progressState = {
        doneBytes: session.files.reduce((sum, item) => sum + Number(item.next_offset || 0), 0),
        totalBytes: session.files.reduce((sum, item) => sum + Number(item.size || 0), 0),
        finishedFiles: session.files.filter(item => item.state === 'uploaded').length,
        totalFiles: session.files.length,
    };
    setProjectUploadProgress(progressState.doneBytes, progressState.totalBytes);
    let cursor = 0;
    async function worker() {
        while (cursor < queue.length) {
            const item = queue[cursor];
            cursor += 1;
            await uploadOneProjectFile(session, item, fileByPath, progressState);
        }
    }
    const workerCount = Math.min(Number(session.concurrency || 4), queue.length);
    await Promise.all(Array.from({length: workerCount}, () => worker()));
}

function projectDateValue(elementId) {
    const value = document.getElementById(elementId)?.value;
    return value ? `${value}T00:00:00` : null;
}

async function createAndUploadProject() {
    if (!selectedProjectFileRows.length) return alert('Vui lòng chọn folder có PDF.');
    const projectsList = typeof projectManagementProjects !== 'undefined' ? projectManagementProjects : [];
    const updateProject = projectUpdateTargetId
        ? projectsList.find(project => Number(project.id) === Number(projectUpdateTargetId))
        : null;
    if (projectUpdateTargetId && !updateProject) return alert('Dự án cần cập nhật không còn trong danh sách.');
    if (
        updateProject
        && String(selectedProjectRootName).toLocaleLowerCase('vi-VN')
            !== String(updateProject.root_folder_name).toLocaleLowerCase('vi-VN')
    ) {
        return alert(`Folder đã chọn là “${selectedProjectRootName}”, cần chọn đúng folder “${updateProject.root_folder_name}”.`);
    }
    const templateId = Number(document.getElementById('projectTemplateSelect')?.value || 0);
    const caseLevel = Number(document.getElementById('projectCaseLevel')?.value || 0);
    const reportMode = document.getElementById('projectReportMode')?.value || 'folder_level';
    const reportLevel = reportMode === 'folder_level'
        ? Number(document.getElementById('projectReportLevel')?.value || 0)
        : null;
    if (!updateProject && !templateId) return alert('Vui lòng chọn biểu mẫu.');
    if (!updateProject && !caseLevel) return alert('Vui lòng chọn cấp hồ sơ.');
    if (!updateProject && reportMode === 'folder_level' && (!reportLevel || reportLevel <= caseLevel)) {
        return alert('Cấp báo cáo phải sâu hơn cấp hồ sơ.');
    }

    const button = document.getElementById('createProjectButton');
    if (button) button.disabled = true;
    try {
        const manifest = await buildProjectManifest();
        let resume = getProjectUploadResumeState();
        const targetProjectId = updateProject ? Number(updateProject.id) : null;
        if (
            !resume
            || resume.root_name !== selectedProjectRootName
            || (targetProjectId && Number(resume.project_id) !== targetProjectId)
        ) {
            let projectId = targetProjectId;
            if (!projectId) {
                const created = await apiCall('/api/projects', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        name: document.getElementById('projectNameInput')?.value.trim() || null,
                        root_folder_name: selectedProjectRootName,
                        template_id: templateId,
                        start_date: projectDateValue('projectStartDate'),
                        end_date: projectDateValue('projectEndDate'),
                        case_level: caseLevel,
                        report_mode: reportMode,
                        report_level: reportLevel,
                        input_user_ids: typeof checkedProjectUserIds === 'function' ? checkedProjectUserIds('project-input-user') : [],
                        reviewer_user_ids: typeof checkedProjectUserIds === 'function' ? checkedProjectUserIds('project-reviewer-user') : [],
                    }),
                });
                if (!created) return;
                projectId = Number(created.project_id);
            }
            resume = {
                project_id: projectId,
                client_session_key: `browser-${crypto.randomUUID()}`,
                root_name: selectedProjectRootName,
            };
            saveProjectUploadResumeState(resume);
        }

        setProjectUploadStatus('Đang đối chiếu manifest với máy chủ...');
        const sessionData = await apiCall(`/api/projects/${resume.project_id}/upload-sessions`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                client_session_key: resume.client_session_key,
                files: manifest,
            }),
        });
        if (!sessionData) return;
        const session = sessionData.session;
        setProjectUploadStatus(
            `Máy chủ yêu cầu tải ${session.requested_files.toLocaleString('vi-VN')}/${session.total_files.toLocaleString('vi-VN')} PDF.`,
        );
        await uploadProjectSessionFiles(session);
        setProjectUploadStatus('Đang hoàn tất và kiểm tra dữ liệu trên máy chủ...');
        const finalized = await apiCall(
            `/api/project-upload-sessions/${encodeURIComponent(session.id)}/finalize`,
            {method: 'POST'},
        );
        if (!finalized) return;
        clearProjectUploadResumeState();
        if (updateProject) cancelProjectFolderUpdate();
        setProjectUploadProgress(1, 1);
        setProjectUploadStatus(
            `Hoàn tất: ${finalized.session.imported_files || 0} PDF mới, ${finalized.session.reused_files || 0} PDF đã có.`,
            'success',
        );
        if (typeof loadProjectList === 'function') await loadProjectList();
    } catch (error) {
        setProjectUploadStatus(`Tạm dừng: ${error.message}. Chọn lại cùng folder để tiếp tục.`, 'danger');
    } finally {
        if (button) button.disabled = false;
    }
}
