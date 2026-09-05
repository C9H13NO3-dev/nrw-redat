// frontend/static/js/analysis.js
/**
 * Analyze page component. The server injects config = {address, plot_size_m2,
 * living_space_m2, listing_id, sections (manifest), auto_run}; every card is
 * rendered from the manifest and fed by one /api/v1/section/{key} call
 * returning the fixed envelope {key, tier, status, data, message, source, took_ms}.
 * The map is always mounted and pinned by a plain call — no $watch, no polling.
 * config.run (a stored run) renders without fetching.
 */
window.analysisPage = function (config) {
    const manifest = config.sections || [];
    const emptyState = () => Object.fromEntries(manifest.map(s => [s.key, null]));

    return {
        address: config.address || '',
        plotSize: config.plot_size_m2 ?? null,
        livingSpace: config.living_space_m2 ?? null,
        runIdStored: config.run?.run_id ?? null,
        createdAt: config.run?.created_at ?? null,
        manifest,
        geocode: null,            // /api/v1/geocode response | null
        sections: emptyState(),   // key -> envelope | {key, status:'loading'} | null
        running: false,
        runId: 0,                 // bumped by reset(); load() drops stale-generation responses
        error: null,
        exporting: false,         // PDF report request in flight
        exportNotice: null,       // {text, cls} toast under the toolbar, auto-cleared
        map: null,
        marker: null,
        wmsLayers: {},

        init() {
            this.initMap();
            if (config.run) { this.showStored(config.run); return; }
            if (config.auto_run && this.address) this.run();
        },

        showStored(run) {
            this.geocode = run.geocode;
            this.sections = { ...emptyState(), ...run.sections };
            this.placePin(run.geocode.latitude, run.geocode.longitude, run.geocode.formatted_address);
            this.$nextTick(() => manifest.forEach(s => { if (this.sections[s.key]?.status === 'ok') this.renderChart(s.key); }));
        },

        initMap() {
            if (this.map) return;
            this.map = window.MapUtils.createMap('result-map', { zoom: 11 });
            this.wmsLayers = window.MapUtils.addWMSLayers(this.map, {});
            setTimeout(() => this.map.invalidateSize(), 100);
        },

        placePin(lat, lon, label) {
            if (!this.map) return;
            this.map.invalidateSize();
            if (this.marker) {
                this.marker.setLatLng([lat, lon]);
            } else {
                this.marker = L.marker([lat, lon]).addTo(this.map);
            }
            if (label) this.marker.bindPopup(label).openPopup();
            this.map.setView([lat, lon], 16);
        },

        get settledCount() {
            return manifest.filter(s => {
                const env = this.sections[s.key];
                return env && env.status !== 'loading';
            }).length;
        },
        get progress() {
            return manifest.length ? Math.round(100 * this.settledCount / manifest.length) : 0;
        },
        get gatedCount() {
            return manifest.filter(s => this.sections[s.key]?.status === 'gated').length;
        },
        get hasResults() {
            return !!this.geocode && manifest.some(s => {
                const env = this.sections[s.key];
                return env && env.status !== 'loading';
            });
        },

        reset() {
            this.runId++;
            this.geocode = null;
            this.error = null;
            window.ChartUtils.destroyChart('btw-chart');
            window.ChartUtils.destroyChart('boris_trend-chart');
            this.sections = emptyState();
        },

        async run() {
            if (this.runIdStored) {
                window.location = '/?' + new URLSearchParams({
                    address: this.address, ...(this.plotSize ? { plot_size_m2: this.plotSize } : {}),
                    ...(this.livingSpace ? { living_space_m2: this.livingSpace } : {}), auto: '1',
                });
                return;
            }
            if (!this.address || this.running) return;
            this.running = true;
            this.reset();
            try {
                const resp = await fetch('/api/v1/geocode?address=' + encodeURIComponent(this.address));
                if (!resp.ok) {
                    const body = await resp.json().catch(() => ({}));
                    this.error = body.detail || ('Geocoding fehlgeschlagen (HTTP ' + resp.status + ')');
                    return;
                }
                this.geocode = await resp.json();
                this.placePin(this.geocode.latitude, this.geocode.longitude, this.geocode.formatted_address);
                await Promise.allSettled(manifest.map(s => this.load(s.key)));
                await this.saveRun();
            } catch (e) {
                this.error = 'Fehler: ' + (e.message || e);
            } finally {
                this.running = false;
            }
        },

        async load(key, { force = false } = {}) {
            const meta = manifest.find(s => s.key === key);
            if (!meta || !this.geocode) return;
            const myRun = this.runId;
            this.sections[key] = { key, status: 'loading' };

            const params = new URLSearchParams({ lat: this.geocode.latitude, lon: this.geocode.longitude });
            if (this.geocode.precision) params.set('precision', this.geocode.precision);
            if (this.plotSize) params.set('plot_size_m2', this.plotSize);
            if (force) params.set('force', '1');

            const ctrl = new AbortController();
            const timer = setTimeout(() => ctrl.abort(), (meta.timeout_s + 5) * 1000);
            let envelope;
            try {
                const resp = await fetch('/api/v1/section/' + key + '?' + params.toString(), { signal: ctrl.signal });
                if (this.runId !== myRun) return; // a newer run() started while this fetch was in flight
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                envelope = await resp.json();
                if (this.runId !== myRun) return;
            } catch (e) {
                if (this.runId !== myRun) return;
                envelope = {
                    key, tier: meta.tier, status: 'error', data: null,
                    message: e.name === 'AbortError' ? 'Zeitüberschreitung (' + (meta.timeout_s + 5) + 's)' : (e.message || String(e)),
                    source: null, took_ms: null,
                };
            } finally {
                clearTimeout(timer);
            }
            this.sections[key] = envelope;
            if (envelope.status === 'ok') this.$nextTick(() => this.renderChart(key));
        },

        loadGated() {
            manifest.forEach(s => {
                if (this.sections[s.key]?.status === 'gated') this.load(s.key, { force: true });
            });
        },

        // Persist the envelopes on screen; the URL becomes the permalink.
        async saveRun() {
            if (!this.hasResults) return;
            try {
                const resp = await fetch('/api/v1/runs', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(this.payload()),
                });
                if (!resp.ok) return;
                const { run_id } = await resp.json();
                this.runIdStored = run_id;
                this.createdAt = new Date().toISOString();
                history.replaceState(null, '', '/a/' + run_id);
            } catch (e) { /* the analysis is still on screen; only the permalink is missing */ }
        },
        payload() {
            const sections = {};
            manifest.forEach(s => {
                const env = this.sections[s.key];
                if (env && env.status !== 'loading') sections[s.key] = env;
            });
            return { address: this.address, geocode: this.geocode, plot_size_m2: this.plotSize || null,
                     living_space_m2: this.livingSpace || null, sections };
        },

        notice(text, cls) {
            this.exportNotice = { text, cls };
            setTimeout(() => { if (this.exportNotice?.text === text) this.exportNotice = null; }, 6000);
        },

        // POST the envelopes the browser already holds — the server renders them to PDF, no re-fetch.
        async exportPdf() {
            if (this.runIdStored && config.run) {
                window.location = '/api/v1/run/' + this.runIdStored + '/report.pdf';
                return;
            }
            if (!this.hasResults || this.running || this.exporting) return;
            this.exporting = true;
            this.exportNotice = null;
            const body = this.payload();
            try {
                const resp = await fetch('/api/v1/report', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    this.notice('PDF-Export fehlgeschlagen: ' + (err.detail || ('HTTP ' + resp.status)), 'bg-red-100 text-red-800');
                    return;
                }
                const cd = resp.headers.get('Content-Disposition') || '';
                const m = /filename="([^"]+)"/.exec(cd);
                const filename = m ? m[1] : 'Standortanalyse.pdf';
                const blob = await resp.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url; a.download = filename;
                document.body.appendChild(a); a.click(); a.remove();
                setTimeout(() => URL.revokeObjectURL(url), 10000);
            } catch (e) {
                this.notice('PDF-Export fehlgeschlagen: ' + (e.message || e), 'bg-red-100 text-red-800');
            } finally {
                this.exporting = false;
            }
        },

        renderChart(key) {
            const data = this.sections[key]?.data;
            if (!data) return;
            if (key === 'btw' && data.parties?.length) {
                window.ChartUtils.destroyChart('btw-chart');
                window.ChartUtils.renderBTWChart('btw-chart', data.parties);
            }
            if (key === 'boris_trend' && data.history?.length) {
                window.ChartUtils.destroyChart('boris_trend-chart');
                window.ChartUtils.renderBorisChart('boris_trend-chart', data.history);
            }
        },

        precisionBadge() {
            const p = this.geocode?.precision;
            if (p === 'building') return { icon: '🟢', label: 'hausnummerngenau', cls: 'bg-green-100 text-green-800' };
            if (p === 'street') return { icon: '🟡', label: 'straßengenau', cls: 'bg-yellow-100 text-yellow-800' };
            if (p === 'coordinates') return { icon: '📍', label: 'Koordinaten', cls: 'bg-blue-100 text-blue-800' };
            return { icon: '⚪', label: 'ortsgenau', cls: 'bg-gray-100 text-gray-700' };
        },

        tierBadge(tier) {
            return tier === 'parcel'
                ? { icon: '🏠', label: 'Parzelle', cls: 'bg-amber-50 text-amber-800 border-amber-200' }
                : { icon: '🌐', label: 'Umgebung', cls: 'bg-sky-50 text-sky-800 border-sky-200' };
        },
    };
};
