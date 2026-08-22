(function initializePdfLinkState(global) {
    if (global.pdfLinkState) return;

    let linked = false;

    global.pdfLinkState = Object.freeze({
        isLinked() {
            return linked;
        },
        setLinked(value) {
            linked = value === true;
            return linked;
        },
        toggle() {
            linked = !linked;
            return linked;
        },
    });
})(window);
