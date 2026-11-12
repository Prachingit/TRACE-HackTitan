import React, { useState, useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import { getActiveDemoUser, setActiveDemoUser } from '../api/client';

const DEMO_ROLES = [
  { id: 'usr-meera', label: 'Admin (Meera Shah)', clearance: 'Full Access' },
  { id: 'usr-priya', label: 'Incoming (Priya Nair)', clearance: 'Restricted Hidden' },
  { id: 'usr-rahul', label: 'Departing (Rahul Verma)', clearance: 'Restricted Hidden' },
];

export function Layout() {
  const [currentUser, setCurrentUser] = useState(getActiveDemoUser());

  useEffect(() => {
    const handleRoleChange = (e) => {
      setCurrentUser(e.detail);
    };
    window.addEventListener('trace-role-change', handleRoleChange);
    return () => window.removeEventListener('trace-role-change', handleRoleChange);
  }, []);

  const handleSelectRole = (e) => {
    const newUserId = e.target.value;
    setCurrentUser(newUserId);
    setActiveDemoUser(newUserId);
  };

  return (
    <div className="app-layout">
      <Sidebar />
      <div className="main-viewport">
        <header className="top-header">
          <div className="header-tagline">
            <span className="tagline-quote">“When People Leave, Knowledge Shouldn't.”</span>
          </div>

          <div className="header-actions">
            <div className="demo-role-box">
              <span className="demo-badge">DEMO IDENTITY</span>
              <select
                id="role-switcher-select"
                className="role-select"
                value={currentUser}
                onChange={handleSelectRole}
                title="Select role to demonstrate backend clearance filtering"
              >
                {DEMO_ROLES.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.label} — [{r.clearance}]
                  </option>
                ))}
              </select>
            </div>
          </div>
        </header>

        <main className="content-container">
          <Outlet />
        </main>
      </div>

      <style>{`
        .app-layout {
          display: flex;
          min-height: 100vh;
          background-color: var(--color-bg-app);
        }
        .main-viewport {
          flex: 1;
          display: flex;
          flex-direction: column;
          min-width: 0;
        }
        .top-header {
          height: 60px;
          background-color: var(--color-bg-surface);
          border-bottom: 1px solid var(--color-border);
          padding: 0 var(--space-6);
          display: flex;
          align-items: center;
          justify-content: space-between;
          position: sticky;
          top: 0;
          z-index: 10;
        }
        .header-tagline {
          font-size: var(--font-size-sm);
          font-weight: var(--font-weight-medium);
          color: var(--color-text-muted);
          font-style: italic;
        }
        .header-actions {
          display: flex;
          align-items: center;
          gap: var(--space-4);
        }
        .demo-role-box {
          display: flex;
          align-items: center;
          gap: var(--space-2);
          background-color: var(--color-bg-app);
          padding: 4px 10px;
          border-radius: var(--radius-md);
          border: 1px solid var(--color-border);
        }
        .demo-badge {
          font-size: 10px;
          font-weight: var(--font-weight-bold);
          color: var(--color-primary);
          background-color: var(--color-primary-subtle);
          padding: 2px 6px;
          border-radius: var(--radius-sm);
          letter-spacing: 0.5px;
        }
        .role-select {
          font-size: var(--font-size-xs);
          font-weight: var(--font-weight-medium);
          color: var(--color-text-main);
          background: transparent;
          border: none;
          outline: none;
          cursor: pointer;
        }
        .content-container {
          flex: 1;
          padding: var(--space-6);
          max-width: 1400px;
          width: 100%;
        }
      `}</style>
    </div>
  );
}

export default Layout;
