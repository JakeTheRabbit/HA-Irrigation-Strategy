import { StrictMode, Component, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "sonner";
import App from "./App";
import "./styles.css";
import "./workspace.css";

class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (this.state.failed)
      return (
        <main
          style={{
            padding: "3rem",
            maxWidth: 640,
            margin: "auto",
            fontFamily: "system-ui",
          }}
        >
          <h1>The dashboard could not load</h1>
          <p>
            Reload this page to try again. The irrigation controller runs independently of this
            dashboard.
          </p>
          <button onClick={() => location.reload()}>Reload dashboard</button>
        </main>
      );
    return this.props.children;
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <TooltipProvider>
        <App />
        <Toaster richColors position="bottom-right" />
      </TooltipProvider>
    </ErrorBoundary>
  </StrictMode>,
);
