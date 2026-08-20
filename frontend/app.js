async function initApp() {
    // Only run form-related stuff if form-container exists (i.e. not on admin.html)
    if (document.getElementById('form-container')) {
        setupPdfUpload();
        restoreQueue();
        // Reconcile persisted local files with the current assignment first.
        const hasCheckId = new URLSearchParams(window.location.search).has('check_id');
        let projectWorkspaceLoaded = false;
        if (!hasCheckId && typeof initializeEmployeeProjectWorkspace === 'function') {
            projectWorkspaceLoaded = await initializeEmployeeProjectWorkspace();
        }
        if (!projectWorkspaceLoaded) {
            await fetchSchema();
            if (!hasCheckId && typeof fetchMyQueue === 'function') {
                fetchMyQueue(true);
            }
        }
        
        // Wait a brief moment to ensure UI is ready
        setTimeout(() => {
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.has('check_id')) {
                const checkId = parseInt(urlParams.get('check_id'));
                const backBtn = document.getElementById('backToAdminBtn');
                if (backBtn) {
                    backBtn.classList.remove('d-none');
                    if (currentUser && currentUser.role === 'admin') {
                        const returnTarget = urlParams.get('return_to');
                        const returnFolder = urlParams.get('return_folder');
                        if (returnTarget === 'review') {
                            const adminParams = new URLSearchParams();
                            if (returnFolder) adminParams.set('return_folder', returnFolder);
                            const query = adminParams.toString();
                            backBtn.href = `/admin.html${query ? `?${query}` : ''}#review`;
                            backBtn.innerHTML = '<i class="fas fa-arrow-left"></i> Về kiểm duyệt hồ sơ';
                        } else {
                            backBtn.href = '/admin.html#data';
                            backBtn.innerHTML = '<i class="fas fa-arrow-left"></i> Về hồ sơ hoàn chỉnh';
                        }
                    } else if (currentUser) {
                        backBtn.href = '/index.html#review';
                        backBtn.innerHTML = '<i class="fas fa-arrow-left"></i> Về danh sách kiểm tra';
                    }
                }
                
                // Ẩn UI không cần thiết cho Admin
                const employeeTabs = document.getElementById('employeeTabs');
                if (employeeTabs) employeeTabs.classList.add('d-none');
                
                const fileSidebar = document.getElementById('fileSidebar');
                if (fileSidebar) fileSidebar.classList.remove('d-none');
                
                const pdfViewerCol = document.getElementById('pdfViewerCol');
                if (pdfViewerCol) {
                    pdfViewerCol.classList.remove('col-md-12');
                    pdfViewerCol.classList.add('col-md-9');
                }
                
                const templateSelectContainer = document.getElementById('templateSelectContainer');
                if (templateSelectContainer) templateSelectContainer.style.setProperty('display', 'none', 'important');
                
                if (checkId && !isNaN(checkId)) {
                    editSubmission(checkId);
                }
            }
        }, 500);
    }
}

