// Alpine store `app` — the name the card partials (templates/analysis/_*.html) reference.
document.addEventListener('alpine:init', () => {
    Alpine.store('app', {
        formatNumber(num) {
            if (!num && num !== 0) return '—';
            return new Intl.NumberFormat('de-DE').format(Math.round(num));
        },
        formatPrice(price) {
            if (!price && price !== 0) return '? €';
            return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(price);
        },
        formatDistance(meters) {
            if (!meters) return '—';
            if (meters < 1000) return `${Math.round(meters)}m`;
            return `${(meters / 1000).toFixed(1)}km`;
        },
        getFloodRiskClass(level) {
            switch (level) {
                case 'high': return 'bg-red-100 text-red-700';
                case 'medium': return 'bg-yellow-100 text-yellow-700';
                default: return 'bg-green-100 text-green-700';
            }
        },
        getAirQualityColor(ratingColor) {
            const colors = {
                green: 'bg-green-100 text-green-800', yellow: 'bg-yellow-100 text-yellow-800',
                orange: 'bg-orange-100 text-orange-800', red: 'bg-red-100 text-red-800', gray: 'bg-gray-100 text-gray-800',
            };
            return colors[ratingColor] || colors.gray;
        },
        wmsLayerConfigs: typeof MapUtils !== 'undefined' ? MapUtils.getWMSLayerConfigs() : {},
        toggleWMSLayer(map, wmsLayers, key, enabled) {
            if (typeof MapUtils !== 'undefined') MapUtils.toggleWMSLayer(map, wmsLayers, key, enabled);
        },
    });
});

function debounce(func, wait) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func(...args), wait);
    };
}

function attachAutocomplete(input){
    if (!input) return;
    if (input.dataset.autocompleteAttached === '1') return;
    input.dataset.autocompleteAttached = '1';

    const wrap = document.createElement('div');
    wrap.style.position = 'relative';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    const menu = document.createElement('div');
    menu.style.position = 'absolute';
    menu.style.left = '0';
    menu.style.right = '0';
    menu.style.top = '100%';
    menu.style.zIndex = '50';
    menu.style.background = 'white';
    menu.style.border = '1px solid #e2e8f0';
    menu.style.borderTop = 'none';
    menu.style.borderRadius = '0 0 0.5rem 0.5rem';
    menu.style.boxShadow = '0 4px 12px rgba(0,0,0,0.08)';
    menu.style.maxHeight = '240px';
    menu.style.overflowY = 'auto';
    menu.style.display = 'none';
    wrap.appendChild(menu);

    let items = [];
    let active = -1;

    function close(){ menu.style.display='none'; items=[]; active=-1; }

    function render(){
        menu.innerHTML='';
        if (!items.length) { close(); return; }
        items.forEach((it, idx) => {
            const row = document.createElement('div');
            row.textContent = it.formatted;
            row.style.padding = '8px 12px';
            row.style.cursor = 'pointer';
            row.style.fontSize = '0.875rem';
            row.style.color = '#1e293b';
            row.style.background = (idx===active) ? '#f0fdfa' : 'white';
            row.addEventListener('mousedown', (e)=>{
                e.preventDefault();
                input.value = it.formatted;
                input.dataset.lat = it.lat;
                input.dataset.lon = it.lon;
                close();
                input.dispatchEvent(new Event('input', {bubbles:true}));
                input.dispatchEvent(new Event('change', {bubbles:true}));
            });
            menu.appendChild(row);
        });
        menu.style.display='block';
    }

    const fetchSuggestions = debounce(async () => {
        const q = (input.value || '').trim();
        if (q.length < 3) { close(); return; }
        try {
            const url = `/api/v1/autocomplete?` + new URLSearchParams({text:q, limit:'8'});
            const r = await fetch(url);
            if (!r.ok) { close(); return; }
            const data = await r.json();
            items = (data.results || []).slice(0, 8);
            active = -1;
            render();
        } catch(e){ close(); }
    }, 250);

    input.addEventListener('input', fetchSuggestions);
    input.addEventListener('blur', ()=> setTimeout(close, 150));
    input.addEventListener('keydown', (e)=>{
        if (menu.style.display !== 'block') return;
        if (e.key === 'Escape') { close(); return; }
        if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(items.length-1, active+1); render(); }
        if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(0, active-1); render(); }
        if (e.key === 'Enter') {
            if (active >= 0 && items[active]) {
                e.preventDefault();
                input.value = items[active].formatted;
                input.dataset.lat = items[active].lat;
                input.dataset.lon = items[active].lon;
                close();
                input.dispatchEvent(new Event('input', {bubbles:true}));
                input.dispatchEvent(new Event('change', {bubbles:true}));
            }
        }
    });
    document.addEventListener('click', (e)=>{ if (!wrap.contains(e.target)) close(); });
}

window.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('input[data-geoapify-autocomplete="1"]').forEach(attachAutocomplete);
});
