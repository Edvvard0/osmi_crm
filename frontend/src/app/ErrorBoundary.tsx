import { Component, type ReactNode } from "react";

import { reportClientError } from "@/shared/lib/reporter";
import { ErrorPage } from "@/pages/ErrorPage";

interface Props {
  children: ReactNode;
  fallback?: (reset: () => void) => ReactNode;
  /** При смене значения (например, адреса) экран ошибки сбрасывается — меню остаётся рабочим. */
  resetKey?: string;
}
interface State { failed: boolean; code?: string }

/** Ловит ошибки рендера. Пользователю — нейтральный экран C-06, детали (без персональных данных) уходят в лог сервера. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error) {
    this.setState({ code: reportClientError("render", error) });
  }

  componentDidUpdate(prev: Props) {
    if (this.state.failed && prev.resetKey !== this.props.resetKey) this.reset();
  }

  reset = () => this.setState({ failed: false, code: undefined });

  render() {
    if (!this.state.failed) return this.props.children;
    return this.props.fallback ? this.props.fallback(this.reset) : <ErrorPage code={this.state.code} />;
  }
}
