import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'text-ql | Natural Language to SQL',
  description: 'Convert natural language questions to SQL queries using AI',
  keywords: ['SQL', 'natural language', 'AI', 'database', 'query generator'],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gradient-mesh min-h-screen antialiased">
        {children}
      </body>
    </html>
  );
}
