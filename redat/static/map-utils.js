/**
 * NRW-REDAT - Map Utilities
 * Leaflet helpers, WMS layer configuration (no listing/marker concerns — see CLAUDE.md non-goals)
 */

const MapUtils = (function() {
    'use strict';

    // WMS layer configurations (Land NRW Open Data)
    const WMS_LAYERS = {
        // Noise layers
        lden: {
            url: 'https://www.wms.nrw.de/umwelt/laerm',
            layers: 'STR_DEN,SCB_DEN,SCS_DEN,IND_DEN,FLG_DEN',
            name: 'Lärm Tag',
            icon: '🔊',
            opacity: 0.6,
            default: true
        },
        lnight: {
            url: 'https://www.wms.nrw.de/umwelt/laerm',
            layers: 'STR_NGT,SCB_NGT,SCS_NGT,IND_NGT,FLG_NGT',
            name: 'Lärm Nacht',
            icon: '🔇',
            opacity: 0.6,
            default: false
        },
        // Flood layers
        hq100: {
            url: 'https://www.wms.nrw.de/umwelt/wasser/HW_Gefahrenkarte',
            layers: 'Grenze_der_ueberfluteten_Gebiete_mw,Tiefen_Ueberflutungsgebiet_mw',
            name: 'HQ100',
            icon: '🌊',
            opacity: 0.55,
            default: false
        },
        hqhaeufig: {
            url: 'https://www.wms.nrw.de/umwelt/wasser/HW_Gefahrenkarte',
            layers: 'Grenze_der_ueberfluteten_Gebiete_hw,Tiefen_Ueberflutungsgebiet_hw',
            name: 'HQ häufig',
            icon: '🌊',
            opacity: 0.55,
            default: false
        },
        hqextrem: {
            url: 'https://www.wms.nrw.de/umwelt/wasser/HW_Gefahrenkarte',
            layers: 'Grenze_der_ueberfluteten_Gebiete_nw,Tiefen_Ueberflutungsgebiet_nw',
            name: 'HQ extrem',
            icon: '🌊',
            opacity: 0.55,
            default: false
        },
        // Nature protection
        nsg: {
            url: 'https://www.wms.nrw.de/umwelt/linfos',
            layers: 'Naturschutzgebiete',
            name: 'Naturschutz',
            icon: '🌲',
            opacity: 0.5,
            default: false
        },
        lsg: {
            url: 'https://www.wms.nrw.de/umwelt/linfos',
            layers: 'Landschaftsschutzgebiet',
            name: 'Landschaft',
            icon: '🏞️',
            opacity: 0.4,
            default: false
        },
        // Solar potential
        solar: {
            url: 'https://www.wms.nrw.de/umwelt/energieatlas',
            layers: 'sk_potentiale_photovoltaik_dachflaechen',
            name: 'Solar',
            icon: '☀️',
            opacity: 0.7,
            default: false
        }
    };

    // Base tile layer options
    const BASE_TILE_LAYER = {
        url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        attribution: '© OpenStreetMap contributors'
    };

    // Create a Leaflet map instance
    function createMap(containerId, options = {}) {
        const defaultOptions = {
            zoom: 14,
            center: [51.45, 7.1] // Ruhrgebiet center
        };

        const map = L.map(containerId, { ...defaultOptions, ...options });

        // Add base tile layer
        L.tileLayer(BASE_TILE_LAYER.url, {
            attribution: BASE_TILE_LAYER.attribution
        }).addTo(map);

        return map;
    }

    // Add WMS layers to map
    function addWMSLayers(map, enabledLayers = {}) {
        const wmsLayers = {};

        for (const [key, config] of Object.entries(WMS_LAYERS)) {
            const layer = L.tileLayer.wms(config.url, {
                format: 'image/png',
                transparent: true,
                layers: config.layers,
                opacity: config.opacity
            });

            wmsLayers[key] = {
                layer,
                config,
                enabled: enabledLayers[key] ?? config.default
            };

            // Add to map if enabled by default or specified
            if (wmsLayers[key].enabled) {
                layer.addTo(map);
            }
        }

        return wmsLayers;
    }

    // Toggle WMS layer
    function toggleWMSLayer(map, wmsLayers, key, enabled) {
        if (!wmsLayers[key]) return;

        if (enabled) {
            wmsLayers[key].layer.addTo(map);
            wmsLayers[key].enabled = true;
        } else {
            map.removeLayer(wmsLayers[key].layer);
            wmsLayers[key].enabled = false;
        }
    }

    // Get WMS layer configurations
    function getWMSLayerConfigs() {
        return { ...WMS_LAYERS };
    }

    return {
        createMap,
        addWMSLayers,
        toggleWMSLayer,
        getWMSLayerConfigs
    };
})();

// Export for global use
window.MapUtils = MapUtils;
