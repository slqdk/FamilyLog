import { Component, type ReactNode } from 'react';

/** A crash in a view shows what broke instead of a blank page. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="login-wrap">
          <div className="login-card">
            <h2>Something broke on this page</h2>
            <pre className="crash">{this.state.error.message}</pre>
            <button className="primary-btn" onClick={() => location.reload()}>Reload</button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
