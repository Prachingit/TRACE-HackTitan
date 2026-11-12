/**
 * Single fetch wrapper for TRACE API.
 * Reads base URL from VITE_API_URL, defaulting to http://localhost:8000.
 * Automatically attaches X-Demo-User header from active session state.
 */

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const DEMO_USER_STORAGE_KEY = 'trace_demo_user';
const DEFAULT_DEMO_USER = 'usr-meera'; // Admin default

export function getActiveDemoUser() {
  if (typeof window !== 'undefined') {
    return localStorage.getItem(DEMO_USER_STORAGE_KEY) || DEFAULT_DEMO_USER;
  }
  return DEFAULT_DEMO_USER;
}

export function setActiveDemoUser(userId) {
  if (typeof window !== 'undefined') {
    localStorage.setItem(DEMO_USER_STORAGE_KEY, userId);
    window.dispatchEvent(new CustomEvent('trace-role-change', { detail: userId }));
  }
}

async function request(endpoint, options = {}) {
  const url = `${BASE_URL}${endpoint}`;
  const currentUser = getActiveDemoUser();

  const headers = {
    'Content-Type': 'application/json',
    'X-Demo-User': currentUser,
    ...options.headers,
  };

  const config = {
    ...options,
    headers,
  };

  const response = await fetch(url, config);

  if (!response.ok) {
    let errorDetail = `HTTP ${response.status}: ${response.statusText}`;
    try {
      const errorJson = await response.json();
      if (errorJson.detail) {
        errorDetail = errorJson.detail;
      }
    } catch (_) {
      // Fallback to generic message
    }
    const error = new Error(errorDetail);
    error.status = response.status;
    throw error;
  }

  return response.json();
}

export const api = {
  get: (endpoint) => request(endpoint, { method: 'GET' }),
  post: (endpoint, body) =>
    request(endpoint, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    }),

  // Domain API helpers
  getHealth: () => api.get('/api/health'),
  loadDemo: () => api.post('/api/demo/load'),
  getMe: () => api.get('/api/me'),
  getProjects: () => api.get('/api/projects'),
  getProject: (id) => api.get(`/api/projects/${id}`),
  getProjectMembers: (id) => api.get(`/api/projects/${id}/members`),
  getProjectSources: (id) => api.get(`/api/projects/${id}/sources`),
  getProjectSummary: (id) => api.get(`/api/projects/${id}/summary`),
};

export default api;
