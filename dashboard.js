(function renderDemandChart() {
    const canvas = document.getElementById("demandChart");
    const dataTag = document.getElementById("chart-data");
    if (!canvas || !dataTag || typeof Chart === "undefined") {
        return;
    }

    let payload = null;
    try {
        payload = JSON.parse(dataTag.textContent || "{}");
    } catch (err) {
        return;
    }

    if (!payload || !Array.isArray(payload.labels)) {
        return;
    }

    const ctx = canvas.getContext("2d");
    new Chart(ctx, {
        type: "line",
        data: {
            labels: payload.labels,
            datasets: [
                {
                    label: "Historical Demand",
                    data: payload.historical_values,
                    borderColor: "#0b5fff",
                    backgroundColor: "rgba(11, 95, 255, 0.15)",
                    borderWidth: 2,
                    tension: 0.3,
                    spanGaps: true,
                },
                {
                    label: "Forecast Demand",
                    data: payload.forecast_values,
                    borderColor: "#f0771f",
                    backgroundColor: "rgba(240, 119, 31, 0.2)",
                    borderDash: [6, 6],
                    borderWidth: 2,
                    tension: 0.3,
                    spanGaps: true,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: "top",
                },
            },
            scales: {
                y: {
                    beginAtZero: true,
                },
                x: {
                    ticks: {
                        maxTicksLimit: 12,
                    },
                },
            },
        },
    });
})();
