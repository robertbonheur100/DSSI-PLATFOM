// EDC Platform — main.js

// Auto-dismiss flash messages after 5s
document.querySelectorAll('.flash').forEach(el => {
    setTimeout(() => el.remove(), 5000);
});

// Sidebar overlay close for mobile
document.addEventListener('click', function(e) {
    const sidebar = document.getElementById('sidebar');
    const toggle = document.querySelector('.menu-toggle');
    if (sidebar && toggle && sidebar.classList.contains('open')) {
        if (!sidebar.contains(e.target) && !toggle.contains(e.target)) {
            sidebar.classList.remove('open');
        }
    }
});

// Format numbers nicely
function formatCurrency(n) {
    return '$' + Number(n).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

// Copy to clipboard helper
function copyToClipboard(text) {
    return navigator.clipboard.writeText(text);
}
