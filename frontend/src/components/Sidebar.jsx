import React from 'react';
import { NavLink } from 'react-router-dom';

const NAV_GROUPS = [
  {
    title: 'Core Engine',
    items: [
      { name: 'Overview', path: '/' },
      { name: 'Projects', path: '/projects' },
      { name: 'Project Activity', path: '/activity' },
    ],
  },
  {
    title: 'Hero Workflows',
    items: [
      { name: 'Handover Center', path: '/handover', isHero: true },
      { name: 'Handover Reports', path: '/handover-reports' },
      { name: 'Exit Interview', path: '/exit-interview' },
    ],
  },
  {
    title: 'Knowledge & Verification',
    items: [
      { name: 'Knowledge Base', path: '/knowledge-base' },
      { name: 'Contradiction Radar', path: '/contradictions' },
      { name: 'Evidence Ledger', path: '/evidence' },
      { name: 'Dependencies & Ownership', path: '/ownership' },
      { name: 'Knowledge Gaps & Risks', path: '/gaps' },
    ],
  },
  {
    title: 'Organization',
    items: [
      { name: 'Team Members', path: '/team' },
    ],
  },
  {
    title: 'Settings',
    items: [
      { name: 'Integrations', path: '/integrations' },
      { name: 'Settings', path: '/settings' },
    ],
  },
];

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="brand-logo">T</div>
        <div className="brand-text">
          <div className="brand-name">TRACE</div>
          <div className="brand-tag">HackTitan</div>
        </div>
      </div>

      <nav className="sidebar-nav">
        {NAV_GROUPS.map((group, idx) => (
          <div key={idx} className="nav-group">
            <div className="nav-group-title">{group.title}</div>
            <div className="nav-group-items">
              {group.items.map((item) => (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className={({ isActive }) =>
                    `nav-link ${isActive ? 'active' : ''} ${item.isHero ? 'hero-link' : ''}`
                  }
                  end={item.path === '/'}
                >
                  <span className="link-label">{item.name}</span>
                  {item.isHero && <span className="hero-pill">HERO</span>}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="version-label">TRACE v1.0 • Phase 1</div>
      </div>

      <style>{`
        .sidebar {
          width: 260px;
          min-width: 260px;
          background-color: var(--color-bg-sidebar);
          color: var(--color-text-sidebar);
          display: flex;
          flex-direction: column;
          height: 100vh;
          position: sticky;
          top: 0;
          border-right: 1px solid var(--color-border-sidebar);
        }
        .sidebar-brand {
          padding: var(--space-4);
          display: flex;
          align-items: center;
          gap: var(--space-3);
          border-bottom: 1px solid var(--color-border-sidebar);
        }
        .brand-logo {
          width: 32px;
          height: 32px;
          background-color: var(--color-primary);
          color: #ffffff;
          border-radius: var(--radius-md);
          display: flex;
          align-items: center;
          justify-content: center;
          font-weight: var(--font-weight-bold);
          font-size: var(--font-size-base);
        }
        .brand-name {
          font-weight: var(--font-weight-bold);
          font-size: var(--font-size-base);
          color: var(--color-text-sidebar-bright);
          letter-spacing: 0.5px;
        }
        .brand-tag {
          font-size: var(--font-size-xs);
          color: var(--color-text-muted);
        }
        .sidebar-nav {
          flex: 1;
          overflow-y: auto;
          padding: var(--space-3) var(--space-2);
          display: flex;
          flex-direction: column;
          gap: var(--space-4);
        }
        .nav-group-title {
          font-size: 0.6875rem;
          font-weight: var(--font-weight-bold);
          text-transform: uppercase;
          letter-spacing: 0.05em;
          color: var(--color-text-muted);
          padding: 0 var(--space-3) var(--space-1);
        }
        .nav-group-items {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .nav-link {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 7px var(--space-3);
          border-radius: var(--radius-sm);
          font-size: var(--font-size-sm);
          color: var(--color-text-sidebar);
          transition: background-color 0.15s ease, color 0.15s ease;
        }
        .nav-link:hover {
          background-color: var(--color-bg-sidebar-hover);
          color: var(--color-text-sidebar-bright);
        }
        .nav-link.active {
          background-color: var(--color-bg-sidebar-active);
          color: #ffffff;
          font-weight: var(--font-weight-medium);
        }
        .nav-link.hero-link {
          background-color: rgba(37, 99, 235, 0.12);
          border: 1px solid rgba(37, 99, 235, 0.3);
          color: #93c5fd;
        }
        .nav-link.hero-link:hover {
          background-color: rgba(37, 99, 235, 0.22);
          color: #ffffff;
        }
        .nav-link.hero-link.active {
          background-color: var(--color-primary);
          color: #ffffff;
          border-color: var(--color-primary);
        }
        .hero-pill {
          font-size: 9px;
          font-weight: var(--font-weight-bold);
          padding: 1px 5px;
          border-radius: var(--radius-sm);
          background-color: var(--color-primary);
          color: #ffffff;
          letter-spacing: 0.5px;
        }
        .nav-link.hero-link.active .hero-pill {
          background-color: #ffffff;
          color: var(--color-primary);
        }
        .sidebar-footer {
          padding: var(--space-3) var(--space-4);
          border-top: 1px solid var(--color-border-sidebar);
        }
        .version-label {
          font-size: var(--font-size-xs);
          color: var(--color-text-muted);
        }
      `}</style>
    </aside>
  );
}

export default Sidebar;
