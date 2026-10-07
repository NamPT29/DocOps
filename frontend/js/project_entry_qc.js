/* global authFetch, formatApiErrorDetail, formatVietnamDateTime, refreshProjectWorkflow, projectWorkflowProjectId, scanSubmitErrorText, WORKFLOW_STATUS_LABELS, currentUser */

function _entryQcElement(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined && text !== null) el.textContent = String(text);
    return el;
}

// Dùng cả ở index.html (người kiểm tra), nơi không có project_workflow.js / project_management.js.
const ENTRY_QC_STAGE_LABELS = { pending: 'Chờ', in_progress: 'Đang làm', done: 'Xong', rejected: 'Trả lại' };

/** Giờ API: chuỗi không kèm múi giờ là giờ UTC; hiện theo giờ Việt Nam "YYYY-MM-DD HH:mm". */
function _entryQcTime(value) {
    if (!value) return '—';
    const text = String(value);
    const utc = /(Z|[+-]\d{2}:?\d{2})$/.test(text) ? text : `${text}Z`;
    if (typeof formatVietnamDateTime === 'function') return formatVietnamDateTime(utc);
    const date = new Date(utc);
    if (isNaN(date.getTime())) return text;
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
        timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', hour12: false,
    }).formatToParts(date).map(part => [part.type, part.value]));
    return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
}

/** Duyệt kèm lý do (BR-07) chỉ Admin; người kiểm tra chỉ thấy lời nhắc. */
function _entryQcIsAdmin() {
    return typeof currentUser !== 'undefined' && Boolean(currentUser) && currentUser.role === 'admin';
}

async function _loadEntryQcData(projectId, caseId, body, errorBox) {
    body.replaceChildren();
    errorBox.textContent = '';
    errorBox.classList.add('d-none');
    
    const res = await authFetch(`/api/projects/${projectId}/workflow/cases/${caseId}/entry-qc`);
    if (!res) return null;
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.status !== 'ok') {
        errorBox.textContent = scanSubmitErrorText(payload, 'Lỗi khi tải dữ liệu Check nhập liệu.');
        errorBox.classList.remove('d-none');
        return null;
    }
    return payload.data;
}

async function openEntryQc(caseId, caseName) {
    const projectId = Number(projectWorkflowProjectId);
    
    const overlay = _entryQcElement('div', 'modal fade show');
    overlay.style.display = 'block';
    overlay.style.backgroundColor = 'rgba(0,0,0,0.5)';
    
    const dialog = _entryQcElement('div', 'modal-dialog modal-dialog-scrollable modal-lg');
    const content = _entryQcElement('div', 'modal-content');
    
    const header = _entryQcElement('div', 'modal-header bg-info text-white');
    const title = _entryQcElement('h5', 'modal-title', `Check nhập liệu: ${caseName}`);
    const closeBtn = _entryQcElement('button', 'btn-close btn-close-white');
    closeBtn.type = 'button';
    closeBtn.setAttribute('aria-label', 'Đóng');
    
    header.append(title, closeBtn);
    
    const bodyContainer = _entryQcElement('div', 'modal-body');
    const errorBox = _entryQcElement('div', 'alert alert-danger d-none');
    const contentBox = _entryQcElement('div', '');
    bodyContainer.append(errorBox, contentBox);
    
    const footer = _entryQcElement('div', 'modal-footer');
    
    const closeOverlay = () => overlay.remove();
    closeBtn.addEventListener('click', closeOverlay);
    
    async function render() {
        const data = await _loadEntryQcData(projectId, caseId, contentBox, errorBox);
        if (!data) return;
        
        // 1. Trạng thái
        const statusDiv = _entryQcElement('div', 'mb-3');
        statusDiv.appendChild(_entryQcElement('strong', '', 'Trạng thái Check nhập liệu: '));
        const statusLabels = typeof WORKFLOW_STATUS_LABELS !== 'undefined' ? WORKFLOW_STATUS_LABELS : ENTRY_QC_STAGE_LABELS;
        const statusLabel = statusLabels[data.entry_qc_status] || data.entry_qc_status;
        statusDiv.appendChild(document.createTextNode(statusLabel));
        contentBox.appendChild(statusDiv);
        
        // 2. Số liệu hiện tại (live)
        const liveDiv = _entryQcElement('div', 'card mb-3');
        const liveHeader = _entryQcElement('div', 'card-header fw-bold', 'Số liệu hiện tại');
        const liveBody = _entryQcElement('div', 'card-body');
        
        if (!data.live) {
            liveBody.appendChild(_entryQcElement('div', 'text-muted fst-italic', 'Chưa có biên bản nào được kiểm.'));
        } else {
            const l = data.live;
            liveBody.appendChild(_entryQcElement('div', '', `Biên bản đã kiểm ${l.reports_assessed}/${l.reports_total}; Biên bản lỗi ${l.error_reports}`));
            liveBody.appendChild(_entryQcElement('div', '', `Trường lỗi ${l.error_fields}/${l.total_fields}`));
            
            const rateStr = `Tỷ lệ lỗi ${l.rate_percent}% (ngưỡng ${l.threshold_percent}%)`;
            const predictStr = l.would_pass ? 'Dự kiến: Đạt' : 'Dự kiến: Không đạt';
            const rateDiv = _entryQcElement('div', 'fw-bold mt-2', `${rateStr} -> ${predictStr}`);
            if (l.would_pass) {
                rateDiv.classList.add('text-success');
            } else {
                rateDiv.classList.add('text-danger');
            }
            liveBody.appendChild(rateDiv);
        }
        liveDiv.append(liveHeader, liveBody);
        contentBox.appendChild(liveDiv);
        
        // 3. Kết quả đã chốt (rounds)
        if (data.rounds && data.rounds.length > 0) {
            const roundsDiv = _entryQcElement('div', 'card mb-3');
            const roundsHeader = _entryQcElement('div', 'card-header fw-bold', 'Kết quả đã chốt');
            const roundsList = _entryQcElement('ul', 'list-group list-group-flush');
            
            data.rounds.forEach(r => {
                const li = _entryQcElement('li', 'list-group-item');
                const pText = r.passed ? 'Đạt' : 'Không đạt';
                const mainStr = `Vòng ${r.round}: ${r.rate_percent}% / ngưỡng ${r.threshold_percent}% - ${pText}`;
                
                const mDiv = _entryQcElement('div', 'fw-bold', mainStr);
                if (r.passed) mDiv.classList.add('text-success');
                else mDiv.classList.add('text-danger');
                li.appendChild(mDiv);
                
                const dt = _entryQcTime(r.created_at);
                const createdBy = r.created_by_name || '—';
                li.appendChild(_entryQcElement('div', 'small text-muted', `Chốt bởi ${createdBy} lúc ${dt}`));
                
                if (r.resolution) {
                    const rdt = _entryQcTime(r.resolved_at);
                    const resDiv = _entryQcElement('div', 'small mt-1');
                    resDiv.appendChild(_entryQcElement('strong', '', 'Admin duyệt: '));
                    const resolvedBy = r.resolved_by_name || '—';
                    resDiv.appendChild(document.createTextNode(`${resolvedBy} lúc ${rdt}. Lý do: ${r.resolution_reason}`));
                    li.appendChild(resDiv);
                }
                
                roundsList.appendChild(li);
            });
            roundsDiv.append(roundsHeader, roundsList);
            contentBox.appendChild(roundsDiv);
        }
        
        // 4. Ô gate
        if (data.gate) {
            if (data.gate.blocked) {
                contentBox.appendChild(_entryQcElement('div', 'alert alert-warning', data.gate.message));
            } else {
                contentBox.appendChild(_entryQcElement('div', 'alert alert-success', 'Hộp được phép chuyển bước sau.'));
            }
        }
        
        // Vòng 2
        const r2Div = _entryQcElement('div', 'card mb-3');
        const r2Header = _entryQcElement('div', 'card-header fw-bold', 'Vòng 2 (Check chéo)');
        const r2Body = _entryQcElement('div', 'card-body');
        
        const round1 = (data.rounds || []).find(r => r.round === 1);
        const round1Done = round1 && (round1.passed || round1.resolution);
        const round2 = (data.rounds || []).find(r => r.round === 2);
        
        let canFinalizeRound2 = false;
        let canResolveRound2 = false;
        let canSampleRound2 = false;
        
        if (data.round2) {
            if (!data.round2.enabled) {
                r2Body.appendChild(_entryQcElement('div', 'text-muted', 'Dự án không bật Check vòng 2.'));
            } else {
                if (data.round2.sampling === null) {
                    if (round1Done) {
                        canSampleRound2 = true;
                    } else {
                        r2Body.appendChild(_entryQcElement('div', 'text-muted', 'Cần xong vòng 1 trước khi lấy mẫu.'));
                    }
                } else {
                    const sample = data.round2.sampling;
                    const items = sample.items || [];
                    
                    r2Body.appendChild(_entryQcElement('div', 'fw-bold mb-2', `Mẫu: ${sample.sample_size}/${sample.population_count} phiếu (tỷ lệ ${sample.sample_rate_percent}%)`));
                    
                    if (items.length > 0) {
                        const table = _entryQcElement('table', 'table table-sm table-bordered');
                        const thead = _entryQcElement('thead', 'table-light');
                        const htr = _entryQcElement('tr', '');
                        ['Tên biên bản', 'Trạng thái', 'Người check', 'Trường sửa', 'Thao tác'].forEach(t => htr.appendChild(_entryQcElement('th', '', t)));
                        thead.appendChild(htr);
                        
                        const tbody = _entryQcElement('tbody', '');
                        let allChecked = true;
                        
                        items.forEach(item => {
                            const tr = _entryQcElement('tr', '');
                            tr.appendChild(_entryQcElement('td', '', item.report_name));
                            if (item.checked === true) {
                                tr.appendChild(_entryQcElement('td', 'text-success', 'Đã check'));
                                tr.appendChild(_entryQcElement('td', '', item.checked_by_name || '—'));
                                tr.appendChild(_entryQcElement('td', '', `${item.changed_field_count}/${item.visible_field_count} trường sửa`));
                            } else {
                                allChecked = false;
                                tr.appendChild(_entryQcElement('td', 'text-warning', 'Chưa check'));
                                tr.appendChild(_entryQcElement('td', '', '—'));
                                tr.appendChild(_entryQcElement('td', '', '—'));
                            }
                            
                            const tdAction = _entryQcElement('td', '');
                            const btnAction = _entryQcElement('button', 'btn btn-sm btn-outline-primary', item.checked ? 'Xem' : 'Check');
                            btnAction.addEventListener('click', () => openRound2Item(projectId, caseId, item.submission_id, render));
                            tdAction.appendChild(btnAction);
                            tr.appendChild(tdAction);
                            
                            tbody.appendChild(tr);
                        });
                        
                        table.append(thead, tbody);
                        r2Body.appendChild(table);
                        
                        if (allChecked && !round2) {
                            canFinalizeRound2 = true;
                        }
                    }
                }
            }
            r2Div.append(r2Header, r2Body);
            contentBox.appendChild(r2Div);
            
            if (round2 && round2.passed === false && !round2.resolution) {
                canResolveRound2 = true;
            }
        }
        
        // 5. Buttons (footer)
        footer.replaceChildren();
        
        const closeBtn2 = _entryQcElement('button', 'btn btn-secondary', 'Đóng');
        closeBtn2.addEventListener('click', closeOverlay);
        footer.appendChild(closeBtn2);
        
        
        if (data.entry_qc_status === 'done' && !round1) {
            const chotBtn = _entryQcElement('button', 'btn btn-primary ms-2', 'Chốt vòng 1');
            chotBtn.addEventListener('click', async () => {
                if (!window.confirm(`Chốt kết quả vòng 1 cho hộp ${caseName}? Sau khi chốt không sửa được.`)) return;
                chotBtn.disabled = true;
                const r = await authFetch(`/api/projects/${projectId}/workflow/cases/${caseId}/entry-qc/round1`, { method: 'POST' });
                if (!r) {
                    chotBtn.disabled = false;
                    return;
                }
                const rData = await r.json().catch(() => ({}));
                if (!r.ok || rData.status !== 'ok') {
                    errorBox.textContent = scanSubmitErrorText(rData, 'Lỗi khi chốt kết quả.');
                    errorBox.classList.remove('d-none');
                    chotBtn.disabled = false;
                } else {
                    await render();
                    if (typeof refreshProjectWorkflow === 'function') refreshProjectWorkflow();
                }
            });
            footer.appendChild(chotBtn);
        }
        
        const waitingAdmin = (round1 && round1.passed === false && !round1.resolution) || canResolveRound2;
        if (waitingAdmin && !_entryQcIsAdmin()) {
            footer.appendChild(_entryQcElement('span', 'text-muted small me-auto', 'Hộp vượt ngưỡng lỗi: chờ Admin duyệt kèm lý do.'));
        }

        if (round1 && round1.passed === false && !round1.resolution && _entryQcIsAdmin()) {
            const resolveBtn = _entryQcElement('button', 'btn btn-warning ms-2', 'Duyệt kèm lý do');
            resolveBtn.addEventListener('click', async () => {
                let reason = window.prompt('Nhập lý do duyệt:');
                if (reason === null) return;
                reason = reason.trim();
                if (!reason) return;
                if (reason.length > 500) {
                    window.alert('Lý do quá dài (tối đa 500 ký tự).');
                    return;
                }
                resolveBtn.disabled = true;
                const r = await authFetch(`/api/projects/${projectId}/workflow/cases/${caseId}/entry-qc/resolve`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reason })
                });
                if (!r) {
                    resolveBtn.disabled = false;
                    return;
                }
                const rData = await r.json().catch(() => ({}));
                if (!r.ok || rData.status !== 'ok') {
                    errorBox.textContent = scanSubmitErrorText(rData, 'Lỗi khi duyệt.');
                    errorBox.classList.remove('d-none');
                    resolveBtn.disabled = false;
                } else {
                    await render();
                    if (typeof refreshProjectWorkflow === 'function') refreshProjectWorkflow();
                }
            });
            footer.appendChild(resolveBtn);
        }
        
        if (canSampleRound2) {
            const sampleBtn = _entryQcElement('button', 'btn btn-primary ms-2', 'Lấy mẫu vòng 2');
            sampleBtn.addEventListener('click', async () => {
                if (!window.confirm('Lấy mẫu ngẫu nhiên cho vòng 2? Sau khi lấy không đổi được.')) return;
                sampleBtn.disabled = true;
                const r = await authFetch(`/api/projects/${projectId}/workflow/cases/${caseId}/entry-qc/round2/sample`, { method: 'POST' });
                if (!r) {
                    sampleBtn.disabled = false;
                    return;
                }
                const rData = await r.json().catch(() => ({}));
                if (!r.ok || rData.status !== 'ok') {
                    errorBox.textContent = scanSubmitErrorText(rData, 'Lỗi khi lấy mẫu.');
                    errorBox.classList.remove('d-none');
                    sampleBtn.disabled = false;
                } else {
                    await render();
                    if (typeof refreshProjectWorkflow === 'function') refreshProjectWorkflow();
                }
            });
            footer.appendChild(sampleBtn);
        }
        
        if (canFinalizeRound2) {
            const r2ChotBtn = _entryQcElement('button', 'btn btn-primary ms-2', 'Chốt vòng 2');
            r2ChotBtn.addEventListener('click', async () => {
                if (!window.confirm('Chốt kết quả vòng 2?')) return;
                r2ChotBtn.disabled = true;
                const r = await authFetch(`/api/projects/${projectId}/workflow/cases/${caseId}/entry-qc/round2`, { method: 'POST' });
                if (!r) {
                    r2ChotBtn.disabled = false;
                    return;
                }
                const rData = await r.json().catch(() => ({}));
                if (!r.ok || rData.status !== 'ok') {
                    errorBox.textContent = scanSubmitErrorText(rData, 'Lỗi khi chốt.');
                    errorBox.classList.remove('d-none');
                    r2ChotBtn.disabled = false;
                } else {
                    await render();
                    if (typeof refreshProjectWorkflow === 'function') refreshProjectWorkflow();
                }
            });
            footer.appendChild(r2ChotBtn);
        }
        
        if (canResolveRound2 && _entryQcIsAdmin()) {
            const r2ResolveBtn = _entryQcElement('button', 'btn btn-warning ms-2', 'Duyệt vòng 2 kèm lý do');
            r2ResolveBtn.addEventListener('click', async () => {
                let reason = window.prompt('Nhập lý do duyệt:');
                if (reason === null) return;
                reason = reason.trim();
                if (!reason) return;
                if (reason.length > 500) {
                    window.alert('Lý do quá dài (tối đa 500 ký tự).');
                    return;
                }
                r2ResolveBtn.disabled = true;
                const r = await authFetch(`/api/projects/${projectId}/workflow/cases/${caseId}/entry-qc/round2/resolve`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reason })
                });
                if (!r) {
                    r2ResolveBtn.disabled = false;
                    return;
                }
                const rData = await r.json().catch(() => ({}));
                if (!r.ok || rData.status !== 'ok') {
                    errorBox.textContent = scanSubmitErrorText(rData, 'Lỗi khi duyệt.');
                    errorBox.classList.remove('d-none');
                    r2ResolveBtn.disabled = false;
                } else {
                    await render();
                    if (typeof refreshProjectWorkflow === 'function') refreshProjectWorkflow();
                }
            });
            footer.appendChild(r2ResolveBtn);
        }
    }
    
    content.append(header, bodyContainer, footer);
    dialog.appendChild(content);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    
    await render();
}

async function openRound2Item(projectId, caseId, submissionId, reload) {
    const overlay = _entryQcElement('div', 'modal text-dark');
    overlay.style.display = 'block';
    overlay.style.backgroundColor = 'rgba(0,0,0,0.5)';
    overlay.style.zIndex = '1060';
    
    const dialog = _entryQcElement('div', 'modal-dialog modal-xl modal-dialog-centered modal-dialog-scrollable');
    const content = _entryQcElement('div', 'modal-content');
    
    const header = _entryQcElement('div', 'modal-header');
    const title = _entryQcElement('h5', 'modal-title', 'Đang tải...');
    const closeBtn = _entryQcElement('button', 'btn-close');
    header.append(title, closeBtn);
    
    const bodyContainer = _entryQcElement('div', 'modal-body');
    const errorBox = _entryQcElement('div', 'alert alert-danger d-none');
    bodyContainer.appendChild(errorBox);
    
    const row = _entryQcElement('div', 'row d-none');
    const colLeft = _entryQcElement('div', 'col-md-6');
    const colRight = _entryQcElement('div', 'col-md-6');
    row.append(colLeft, colRight);
    bodyContainer.appendChild(row);
    
    const footer = _entryQcElement('div', 'modal-footer');
    const closeBtn2 = _entryQcElement('button', 'btn btn-secondary', 'Đóng');
    footer.appendChild(closeBtn2);
    
    let objectUrl = null;
    const closeOverlay = () => {
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        overlay.remove();
    };
    closeBtn.addEventListener('click', closeOverlay);
    closeBtn2.addEventListener('click', closeOverlay);
    
    content.append(header, bodyContainer, footer);
    dialog.appendChild(content);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
    
    const res = await authFetch(`/api/projects/${projectId}/workflow/cases/${caseId}/entry-qc/round2/items/${submissionId}`);
    if (!res) {
        title.textContent = 'Lỗi';
        return;
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.status !== 'ok') {
        title.textContent = 'Không thể xem phiếu';
        errorBox.textContent = scanSubmitErrorText(data, 'Lỗi tải phiếu.');
        errorBox.classList.remove('d-none');
        return;
    }
    
    const item = data.data;
    title.textContent = `Check vòng 2: ${item.report_name}`;
    row.classList.remove('d-none');
    
    const pdfRes = await authFetch(item.pdf_url);
    if (!pdfRes || !pdfRes.ok) {
        colLeft.appendChild(_entryQcElement('div', 'alert alert-warning', 'Không mở được PDF.'));
    } else {
        const blob = await pdfRes.blob();
        objectUrl = URL.createObjectURL(blob);
        const iframe = _entryQcElement('iframe', 'w-100 h-100');
        iframe.style.minHeight = '500px';
        iframe.src = objectUrl;
        colLeft.appendChild(iframe);
    }
    
    const form = _entryQcElement('div', '');
    if (item.checked) {
        const infoDiv = _entryQcElement('div', 'alert alert-info', `Đã check bởi ${item.checked_by_name}: ${item.changed_field_count}/${item.visible_field_count} trường sửa`);
        form.appendChild(infoDiv);
    }
    
    const inputs = {};
    item.fields.forEach(f => {
        const grp = _entryQcElement('div', 'mb-2');
        grp.appendChild(_entryQcElement('label', 'form-label fw-bold', f.label || f.name));
        
        let input;
        if (f.type === 'dropdown') {
            input = _entryQcElement('select', 'form-select');
            const emptyOpt = _entryQcElement('option', '', '— Chưa chọn —');
            emptyOpt.value = '';
            input.appendChild(emptyOpt);
            
            let found = false;
            (f.options || []).forEach(opt => {
                const o = _entryQcElement('option', '', opt);
                o.value = opt;
                if (opt === f.value) {
                    o.selected = true;
                    found = true;
                }
                input.appendChild(o);
            });
            if (f.value !== null && f.value !== undefined && f.value !== '' && !found) {
                const o = _entryQcElement('option', '', f.value);
                o.value = f.value;
                o.selected = true;
                input.appendChild(o);
            }
            if (!f.value) emptyOpt.selected = true;
        } else {
            input = _entryQcElement('input', 'form-control');
            input.type = 'text';
            input.value = (f.value !== null && f.value !== undefined) ? f.value : '';
        }
        
        if (item.checked) input.disabled = true;
        
        grp.appendChild(input);
        form.appendChild(grp);
        inputs[f.name] = input;
    });
    colRight.appendChild(form);
    
    if (!item.checked) {
        const saveBtn = _entryQcElement('button', 'btn btn-primary', 'Lưu kết quả check');
        saveBtn.addEventListener('click', async () => {
            if (!window.confirm('Lưu kết quả check phiếu này? Sau khi lưu không sửa được.')) return;
            
            saveBtn.disabled = true;
            errorBox.classList.add('d-none');
            
            const payload = { data: {} };
            for (const [name, el] of Object.entries(inputs)) {
                payload.data[name] = el.value;
            }
            
            const r = await authFetch(`/api/projects/${projectId}/workflow/cases/${caseId}/entry-qc/round2/items/${submissionId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!r) {
                saveBtn.disabled = false;
                return;
            }
            const rData = await r.json().catch(() => ({}));
            if (!r.ok || rData.status !== 'ok') {
                errorBox.textContent = scanSubmitErrorText(rData, 'Lỗi khi lưu.');
                errorBox.classList.remove('d-none');
                saveBtn.disabled = false;
            } else {
                closeOverlay();
                await reload();
                if (typeof refreshProjectWorkflow === 'function') refreshProjectWorkflow();
            }
        });
        footer.insertBefore(saveBtn, closeBtn2);
    }
}
