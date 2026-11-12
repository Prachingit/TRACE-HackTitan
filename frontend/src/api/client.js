/**
 * Single fetch wrapper. Same-origin in production; Vite proxies /api in dev.
 * Auth is an httpOnly cookie, so requests use credentials: 'include'.
 */
const BASE_URL = import.meta.env.VITE_API_URL || '';

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function messageFrom(body, fallback) {
  if (!body) return fallback;
  if (typeof body.detail === 'string') return body.detail;
  if (Array.isArray(body.detail)) {
    return body.detail.map((d) => (d.msg || '').replace(/^Value error, /, '')).join(' ');
  }
  return fallback;
}

async function request(path, { method = 'GET', json, form } = {}) {
  const opts = { method, credentials: 'include', headers: {} };
  if (json !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(json);
  } else if (form) {
    opts.body = form;
  }
  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, opts);
  } catch {
    throw new ApiError('Cannot reach the server. Check your connection and try again.', 0);
  }
  if (res.status === 204) return null;
  let body = null;
  try { body = await res.json(); } catch { /* no body */ }
  if (!res.ok) throw new ApiError(messageFrom(body, `Request failed (${res.status}).`), res.status);
  return body;
}

export const api = {
  signup: (d) => request('/api/auth/signup', { method: 'POST', json: d }),
  login: (d) => request('/api/auth/login', { method: 'POST', json: d }),
  logout: () => request('/api/auth/logout', { method: 'POST' }),
  me: () => request('/api/auth/me'),
  forgot: (email) => request('/api/auth/forgot-password', { method: 'POST', json: { email } }),

  workspaces: () => request('/api/workspaces'),
  createWorkspace: (name) => request('/api/workspaces', { method: 'POST', json: { name } }),
  joinWorkspace: (token) => request('/api/workspaces/join', { method: 'POST', json: { token } }),
  invitePreview: (token) => request(`/api/workspaces/invite-preview/${encodeURIComponent(token)}`),
  members: (ws) => request(`/api/workspaces/${ws}/members`),
  setRole: (ws, uid, role) => request(`/api/workspaces/${ws}/members/${uid}/role`, { method: 'PATCH', json: { role } }),
  removeMember: (ws, uid) => request(`/api/workspaces/${ws}/members/${uid}`, { method: 'DELETE' }),
  invites: (ws) => request(`/api/workspaces/${ws}/invites`),
  createInvite: (ws, role) => request(`/api/workspaces/${ws}/invites`, { method: 'POST', json: { role } }),
  revokeInvite: (ws, id) => request(`/api/workspaces/${ws}/invites/${id}`, { method: 'DELETE' }),

  projects: () => request('/api/projects'),
  project: (id) => request(`/api/projects/${id}`),
  createProject: (d) => request('/api/projects', { method: 'POST', json: d }),
  deleteProject: (id) => request(`/api/projects/${id}`, { method: 'DELETE' }),
  summary: (id) => request(`/api/projects/${id}/summary`),

  sources: (pid) => request(`/api/projects/${pid}/sources`),
  source: (pid, sid) => request(`/api/projects/${pid}/sources/${sid}`),
  chunks: (pid, sid, offset = 0) => request(`/api/projects/${pid}/sources/${sid}/chunks?limit=50&offset=${offset}`),
  upload: (pid, file, clearance) => {
    const form = new FormData();
    form.append('file', file);
    form.append('clearance_level', clearance);
    return request(`/api/projects/${pid}/sources/upload`, { method: 'POST', form });
  },
  importGithub: (pid, d) => request(`/api/projects/${pid}/sources/github`, { method: 'POST', json: d }),
  addManual: (pid, d) => request(`/api/projects/${pid}/sources/manual`, { method: 'POST', json: d }),
  retrySource: (pid, sid) => request(`/api/projects/${pid}/sources/${sid}/retry`, { method: 'POST' }),
  deleteSource: (pid, sid) => request(`/api/projects/${pid}/sources/${sid}`, { method: 'DELETE' }),
  loadSample: (pid) => request(`/api/projects/${pid}/sample`, { method: 'POST' }),
};

export default api;
