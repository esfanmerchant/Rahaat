import { Component, type ComponentChildren } from 'preact';
import { ScreenState } from './ScreenState';

interface Props {
  density?: 'citizen' | 'staff';
  children?: ComponentChildren;
}

interface State {
  failed: boolean;
}

/**
 * Last line of defence: a render error shows the error state with a reload
 * button instead of a blank page. Lazy-route suspension (thrown promises) is
 * handled by preact-iso's Router and never reaches this boundary.
 */
export class ErrorBoundary extends Component<Props, State> {
  override state: State = { failed: false };

  override componentDidCatch(error: unknown): void {
    if (error && typeof (error as { then?: unknown }).then === 'function') return;
    if (import.meta.env.DEV) console.error('Render error', error); // dev only: production keeps the error screen, not the log
    this.setState({ failed: true });
  }

  override render() {
    if (this.state.failed) {
      return (
        <ScreenState
          kind="error"
          density={this.props.density ?? 'citizen'}
          onRetry={() => window.location.reload()}
        />
      );
    }
    return this.props.children;
  }
}
