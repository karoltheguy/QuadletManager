(function () {
    try {
        const saved = localStorage.getItem('qm-theme-override');
        if (saved === 'light' || saved === 'dark') {
            document.documentElement.dataset.theme = saved;
        }
    } catch {
        // localStorage is unavailable (private mode / blocked storage);
        // fall through and keep the default theme.
    }
})();
