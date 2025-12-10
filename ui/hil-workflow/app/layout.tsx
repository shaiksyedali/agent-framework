import './globals.css';
import type { ReactNode } from 'react';

export const metadata = {
  title: 'Azure Foundry Workflow Builder',
  description: 'Configure and execute multi-agent workflows using Azure AI Foundry'
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, padding: 0, backgroundColor: '#F9FAFB', minHeight: '100vh' }}>
        {children}
      </body>
    </html>
  );
}
