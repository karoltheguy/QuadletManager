(function () {
    try {
        const pref = document.documentElement.dataset.themePref || 'auto';
        const quickOverride = localStorage.getItem('qm-theme-override');
        const effective = quickOverride || pref || 'auto';
        let resolved = effective;
        if (effective === 'auto') {
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            resolved = prefersDark ? 'dark' : 'light';
        }
        document.documentElement.dataset.theme = resolved;
    } catch {
        // localStorage is unavailable (private mode / blocked storage);
        // fall through and keep the default theme.
    }
    try {
        const density = localStorage.getItem('qm-density');
        if (density === 'compact') {
            document.documentElement.dataset.density = 'compact';
        }
    } catch {
        // localStorage is unavailable (private mode / blocked storage);
        // density preference will remain unset.
    }
})();
