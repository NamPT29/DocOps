function initApp() {
    // Only run form-related stuff if form-container exists (i.e. not on admin.html)
    if (document.getElementById('form-container')) {
        fetchSchema();
        setupPdfUpload();
        restoreQueue();
        
        // Wait a brief moment to ensure UI is ready
        setTimeout(() => {
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.has('check_id')) {
                const checkId = parseInt(urlParams.get('check_id'));
                const backBtn = document.getElementById('backToAdminBtn');
                if (backBtn) backBtn.classList.remove('d-none');
                
                // Ẩn UI không cần thiết cho Admin
                const employeeTabs = document.getElementById('employeeTabs');
                if (employeeTabs) employeeTabs.classList.add('d-none');
                
                const fileSidebar = document.getElementById('fileSidebar');
                if (fileSidebar) fileSidebar.classList.add('d-none');
                
                const pdfViewerCol = document.getElementById('pdfViewerCol');
                if (pdfViewerCol) {
                    pdfViewerCol.classList.remove('col-md-9');
                    pdfViewerCol.classList.add('col-md-12');
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

