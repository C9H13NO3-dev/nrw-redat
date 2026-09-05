/**
 * House Hunter - Map Utilities
 * Leaflet helpers, WMS layer configuration, marker factory
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

    // Create marker with custom icon based on score
    function createMarker(lat, lon, options = {}) {
        const score = options.score || 0;
        const color = getScoreColor(score);

        const icon = L.divIcon({
            className: 'custom-marker',
            html: `
                <div style="
                    background-color: ${color};
                    color: white;
                    width: ${options.size || 32}px;
                    height: ${options.size || 32}px;
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-weight: bold;
                    font-size: ${options.fontSize || 12}px;
                    border: 2px solid white;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.3);
                ">${score}</div>
            `,
            iconSize: [options.size || 32, options.size || 32],
            iconAnchor: [(options.size || 32) / 2, (options.size || 32) / 2],
        });

        return L.marker([lat, lon], { icon, ...options });
    }

    // Get color for score
    function getScoreColor(score) {
        if (score >= 70) return '#22c55e'; // green-500
        if (score >= 40) return '#eab308'; // yellow-500
        return '#ef4444'; // red-500
    }

    // HTML-escape helper — prevents XSS when inserting user data into innerHTML
    function esc(str) {
        if (str == null) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // Create popup content for a listing
    function createPopupContent(listing) {
        const price = listing.price ? new Intl.NumberFormat('de-DE').format(listing.price) + ' €' : '?';
        const space = listing.living_space_m2 ? listing.living_space_m2 + ' m²' : '?';
        const scoreColor = getScoreColor(listing.score || 0);

        return `
            <div class="text-sm p-1">
                <div class="font-bold mb-1">${esc(listing.title) || 'Untitled'}</div>
                <div class="text-gray-600 mb-2">${esc(listing.district)} ${esc(listing.city)}</div>
                <div class="font-bold text-lg mb-1">${price}</div>
                <div class="text-gray-500 mb-2">${space} • ${esc(String(listing.rooms || '?'))} Zimmer</div>
                <div class="inline-block px-2 py-1 rounded text-white font-bold mb-2" style="background-color: ${esc(scoreColor)}">
                    Score: ${listing.score || 0}
                </div>
                <div>
                    <a href="/listings/${parseInt(listing.id)}" class="text-blue-600 hover:underline font-medium">
                        Details ansehen →
                    </a>
                </div>
            </div>
        `;
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

    // Setup loading events for a WMS layer
    function setupLayerEvents(layer, loadingCallback, loadedCallback, errorCallback) {
        if (loadingCallback) layer.on('loading', loadingCallback);
        if (loadedCallback) layer.on('load', loadedCallback);
        if (errorCallback) layer.on('tileerror', errorCallback);
    }

    // Fit map bounds to listings
    function fitToListings(map, listings, padding = [50, 50]) {
        const validListings = listings.filter(l => l.latitude && l.longitude);
        if (validListings.length > 0) {
            const bounds = validListings.map(l => [l.latitude, l.longitude]);
            map.fitBounds(bounds, { padding });
        }
    }

    // Add multiple markers to map
    // Returns {clusterGroup, markers} when markercluster plugin is loaded,
    // or a plain [{marker, listing}] array as fallback (for analyze.html).
    function addMarkers(map, listings, options = {}) {
        const markers = [];
        const useCluster = typeof L.markerClusterGroup === 'function';
        const clusterGroup = useCluster ? L.markerClusterGroup() : null;

        listings.forEach(listing => {
            if (!listing.latitude || !listing.longitude) return;

            const marker = createMarker(listing.latitude, listing.longitude, {
                score: listing.score || 0,
                ...options.markerOptions
            });

            if (options.popup !== false) {
                marker.bindPopup(createPopupContent(listing));
            }

            if (options.onClick) {
                marker.on('click', () => options.onClick(listing));
            }

            if (useCluster) {
                clusterGroup.addLayer(marker);
            } else {
                marker.addTo(map);
            }
            markers.push({ marker, listing });
        });

        if (useCluster) {
            map.addLayer(clusterGroup);
            return { clusterGroup, markers };
        }

        return markers;
    }

    // Invalidate map size (useful when container was hidden)
    function invalidateSize(map, delay = 100) {
        setTimeout(() => {
            map.invalidateSize();
        }, delay);
    }

    // Get WMS layer configurations
    function getWMSLayerConfigs() {
        return { ...WMS_LAYERS };
    }

    return {
        createMap,
        createMarker,
        addWMSLayers,
        toggleWMSLayer,
        setupLayerEvents,
        fitToListings,
        addMarkers,
        invalidateSize,
        getWMSLayerConfigs,
        getScoreColor
    };
})();

// Export for global use
window.MapUtils = MapUtils;
