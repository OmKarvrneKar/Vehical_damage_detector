/**
 * Common utilities for AI Vehicle Damage Detection UI
 */

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[c]));

const inr = n => {
  if (n === null || n === undefined || isNaN(n)) return '₹0';
  return '₹' + Number(n).toLocaleString('en-IN');
};

function toast(message, type = 'info') {
  let container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    document.body.appendChild(container);
  }

  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  if (type === 'error') el.style.borderLeft = '4px solid var(--accent-red)';
  else if (type === 'success') el.style.borderLeft = '4px solid var(--accent-green)';
  else el.style.borderLeft = '4px solid var(--primary)';

  el.textContent = message;
  container.appendChild(el);

  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(10px)';
    el.style.transition = 'all 0.3s ease';
    setTimeout(() => el.remove(), 300);
  }, 4000);
}

function severityBadge(sev) {
  const s = String(sev || 'None').toLowerCase();
  let cls = 'badge-none';
  if (s === 'minor') cls = 'badge-minor';
  else if (s === 'moderate') cls = 'badge-moderate';
  else if (s === 'severe') cls = 'badge-severe';
  return `<span class="badge ${cls}">${esc(sev || 'None')}</span>`;
}

function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta && meta.getAttribute('content')) {
    return meta.getAttribute('content');
  }
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : '';
}

// Automatically attach X-CSRF-Token to state-changing fetch requests
const _fetch = window.fetch;
window.fetch = function(url, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
    const token = getCsrfToken();
    if (token) {
      if (options.headers instanceof Headers) {
        if (!options.headers.has('X-CSRF-Token')) {
          options.headers.set('X-CSRF-Token', token);
        }
      } else if (Array.isArray(options.headers)) {
        options.headers.push(['X-CSRF-Token', token]);
      } else {
        options.headers = options.headers || {};
        if (!options.headers['X-CSRF-Token'] && !options.headers['x-csrf-token']) {
          options.headers['X-CSRF-Token'] = token;
        }
      }
    }
  }
  return _fetch(url, options);
};
