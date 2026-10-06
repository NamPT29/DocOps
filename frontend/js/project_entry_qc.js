/* global authFetch, formatApiErrorDetail, formatVietnamDateTime, refreshProjectWorkflow, projectWorkflowProjectId, scanSubmitErrorText, WORKFLOW_STATUS_LABELS */

function _entryQcElement(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined && text !== null) el.textContent = String(text);
    return el;
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
        const statusLabel = WORKFLOW_STATUS_LABELS[data.entry_qc_status] || data.entry_qc_status;
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
                
                const dt = typeof formatVietnamDateTime === 'function' ? formatVietnamDateTime(r.created_at) : r.created_at;
                const createdBy = r.created_by_name || '—';
                li.appendChild(_entryQcElement('div', 'small text-muted', `Chốt bởi ${createdBy} lúc ${dt}`));
                
                if (r.resolution) {
                    const rdt = typeof formatVietnamDateTime === 'function' ? formatVietnamDateTime(r.resolved_at) : r.resolved_at;
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
                        ['Tên biên bản', 'Trạng thái', 'Người check', 'Trường sửa'].forEach(t => htr.appendChild(_entryQcElement('th', '', t)));
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
        
        if (round1 && round1.passed === false && !round1.resolution) {
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
        
        if (canResolveRound2) {
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
