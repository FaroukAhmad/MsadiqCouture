document.addEventListener('DOMContentLoaded', () => {
  const menuToggle = document.querySelector('.menu-toggle');
  const header = document.querySelector('.site-header');
  if (menuToggle && header) {
    menuToggle.addEventListener('click', () => {
      const isOpen = header.classList.toggle('menu-open');
      menuToggle.setAttribute('aria-expanded', String(isOpen));
      menuToggle.textContent = isOpen ? 'Close' : 'Menu';
    });
  }

  // Toast confirmations (login, logout, profile/style/service updates, etc.):
  // shown for 3 seconds, then fade out and remove themselves.
  document.querySelectorAll('.toast-wrap .toast').forEach((toast) => {
    setTimeout(() => {
      toast.classList.add('toast-hide');
      toast.addEventListener('animationend', () => toast.remove(), { once: true });
    }, 3000);
  });

  // Profile page: view mode by default, "Edit" reveals the form.
  const profileView = document.querySelector('[data-profile-view]');
  const profileForm = document.querySelector('[data-profile-form]');
  const editBtn = document.querySelector('[data-profile-edit]');
  const cancelBtn = document.querySelector('[data-profile-cancel]');
  if (profileView && profileForm && editBtn) {
    editBtn.addEventListener('click', () => {
      profileView.hidden = true;
      profileForm.hidden = false;
    });
    if (cancelBtn) {
      cancelBtn.addEventListener('click', () => {
        profileForm.hidden = true;
        profileView.hidden = false;
      });
    }
  }
});
