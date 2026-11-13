import React from 'react';

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: '' };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, message: error?.message || 'Unexpected application error.' };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="auth-wrap">
          <div className="card auth-card">
            <h1 style={{ marginTop: 0 }}>Something went wrong</h1>
            <p className="muted">{this.state.message}</p>
            <button
              className="btn primary"
              onClick={() => {
                this.setState({ hasError: false, message: '' });
                window.location.assign('/');
              }}
            >
              Reload application
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export function NotFoundPage() {
  return (
    <div className="panel" style={{ maxWidth: 520, margin: '40px auto' }}>
      <h1 style={{ marginTop: 0 }}>Page not found</h1>
      <p className="muted">The requested route does not exist in TRACE.</p>
      <a className="btn primary" href="/">Return to overview</a>
    </div>
  );
}
