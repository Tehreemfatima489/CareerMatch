document.addEventListener('DOMContentLoaded', () => {
    // 1. Clean up notification badges if they are empty or equal to 0
    const navBadges = document.querySelectorAll('.nav-badge');
    navBadges.forEach(badge => {
        if (badge.textContent.trim() === '0' || badge.textContent.trim() === '') {
            badge.style.display = 'none';
        }
    });

    // 2. Optional: Global fade-in animation context for injected views
    const contentArea = document.querySelector('.main-content');
    if (contentArea) {
        contentArea.style.opacity = '0';
        contentArea.style.transition = 'opacity 0.25s ease-in-out';
        setTimeout(() => {
            contentArea.style.opacity = '1';
        }, 50);
    }
});