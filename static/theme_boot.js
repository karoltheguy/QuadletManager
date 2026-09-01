(function () {
    try {
        var pref = document.documentElement.dataset.themePref || 'auto';
        var quickOverride = localStorage.getItem('qm-theme-override');
        var effective = quickOverride || pref || 'auto';
        var resolved = effective === 'auto'
            ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
            : effective;
        document.documentElement.dataset.theme = resolved;
    } catch {
        // localStorage is unavailable (private mode / blocked storage);
        // fall through and keep the default theme.
    }
    try {
        var density = localStorage.getItem('qm-density');
        if (density === 'compact') {
            document.documentElement.dataset.density = 'compact';
        }
    } catch {
        // localStorage is unavailable (private mode / blocked storage);
        // density preference will remain unset.
    }
})();
