import './globals.css';
import type { ReactNode } from 'react';

export const metadata = {
  title: 'HIL Agentic Workflow Builder',
  description: 'Configure and monitor human-in-the-loop agentic workflows'
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="main-shell">
          <header style={{ marginBottom: '1.5rem' }}>
            <div className="flex-row" style={{ alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <div className="section-title">Agentic Workflow Studio</div>
                <h1 style={{ margin: '0.2rem 0 0', letterSpacing: '0.02em' }}>
                  Human-in-the-loop Orchestration
                </h1>
              </div>
              <div className="tag">
                <span className="badge-success">Live approvals</span>
                <span className="badge-warning">Streaming</span>
                <span>Multi-engine SQL</span>
              </div>
            </div>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
