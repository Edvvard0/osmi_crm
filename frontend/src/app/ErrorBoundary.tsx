import { Component, type ReactNode } from "react";

import { reportClientError } from "@/shared/lib/reporter";
import { ErrorPage } from "@/pages/ErrorPage";

interface Props { children: ReactNode; fallback?: (reset: () => void) => ReactNode }

/** Ловит ошибки рендера. Пользователю — нейтральный экран C-06, детали уходят в лог сервера. */
export class ErrorBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error) {
    reportClientError("render", error);
  }

  reset = () => this.setState({ failed: false });

  render() {
    if (!this.state.failed) return this.props.children;
    return this.props.fallback ? this.props.fallback(this.reset) : <ErrorPage onRetry={this.reset} />;
  }
}
