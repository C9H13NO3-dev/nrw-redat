/**
 * House Hunter - Chart Utilities
 * Chart.js renderers for BORIS trend and BTW politics charts
 */

const ChartUtils = (function() {
    'use strict';

    // Party colors for Bundestagswahl charts
    const PARTY_COLORS = {
        'CDU/CSU': '#333333',
        'SPD': '#E3000F',
        'GRÜNE': '#46962b',
        'FDP': '#FFED00',
        'AfD': '#009EE0',
        'DIE LINKE': '#BE3075',
        'BSW': '#E86E17',
        'Sonstige': '#9CA3AF'
    };

    // Get color for party
    function getPartyColor(party) {
        return PARTY_COLORS[party] || PARTY_COLORS['Sonstige'];
    }

    // Render BORIS trend chart (line chart)
    function renderBorisChart(canvasId, history) {
        if (!history || !history.length) return null;

        const canvas = document.getElementById(canvasId);
        if (!canvas) return null;

        // Sort chronologically
        const sorted = history.slice().sort((a, b) => a.year - b.year);
        const labels = sorted.map(x => x.year);
        const values = sorted.map(x => x.value);

        // Destroy existing chart
        if (canvas.chart) {
            canvas.chart.destroy();
        }

        const chart = new Chart(canvas, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Bodenrichtwert (€/m²)',
                    data: values,
                    borderColor: '#2563eb',
                    backgroundColor: 'rgba(37, 99, 235, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3,
                    pointRadius: 4,
                    pointHoverRadius: 7,
                    pointBackgroundColor: '#2563eb',
                    pointHoverBackgroundColor: '#1d4ed8',
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    intersect: false,
                    mode: 'index',
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(0,0,0,0.8)',
                        titleFont: { size: 14, weight: 'bold' },
                        bodyFont: { size: 13 },
                        padding: 12,
                        displayColors: false,
                        callbacks: {
                            title: (items) => `Jahr ${items[0].label}`,
                            label: (item) => {
                                const val = item.raw;
                                const idx = item.dataIndex;
                                let text = `${val} €/m²`;
                                if (idx > 0) {
                                    const prev = values[idx - 1];
                                    const change = ((val - prev) / prev * 100).toFixed(1);
                                    const sign = change >= 0 ? '+' : '';
                                    text += ` (${sign}${change}% ggü. Vorjahr)`;
                                }
                                return text;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { font: { size: 11 } }
                    },
                    y: {
                        beginAtZero: false,
                        grid: { color: 'rgba(0,0,0,0.05)' },
                        ticks: {
                            font: { size: 11 },
                            callback: (v) => v + ' €'
                        }
                    }
                }
            }
        });

        // Store chart instance on canvas for cleanup
        canvas.chart = chart;
        return chart;
    }

    // Render BTW politics chart (bar chart)
    function renderBTWChart(canvasId, parties) {
        if (!parties || !parties.length) return null;

        const canvas = document.getElementById(canvasId);
        if (!canvas) return null;

        const labels = parties.map(p => p.party);
        const values = parties.map(p => p.percent);
        const colors = parties.map(p => p.color || getPartyColor(p.party));

        // Destroy existing chart
        if (canvas.chart) {
            canvas.chart.destroy();
        }

        const chart = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    data: values,
                    backgroundColor: colors,
                    borderColor: colors,
                    borderWidth: 1,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `${ctx.raw}%`
                        }
                    }
                },
                scales: {
                    x: { grid: { display: false } },
                    y: {
                        beginAtZero: true,
                        ticks: { callback: (v) => v + '%' },
                        grid: { color: 'rgba(0,0,0,0.05)' }
                    }
                }
            }
        });

        // Store chart instance on canvas for cleanup
        canvas.chart = chart;
        return chart;
    }

    // Destroy chart on canvas
    function destroyChart(canvasId) {
        const canvas = document.getElementById(canvasId);
        if (canvas && canvas.chart) {
            canvas.chart.destroy();
            canvas.chart = null;
        }
    }

    // Destroy all charts on page
    function destroyAllCharts() {
        const charts = document.querySelectorAll('canvas.chartjs-render-monitor');
        charts.forEach(canvas => {
            if (canvas.chart) {
                canvas.chart.destroy();
                canvas.chart = null;
            }
        });
    }

    return {
        renderBorisChart,
        renderBTWChart,
        destroyChart,
        destroyAllCharts,
        getPartyColor
    };
})();

window.ChartUtils = ChartUtils;
