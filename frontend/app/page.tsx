'use client';

import { useState } from 'react';
import SchemaInput from '@/components/SchemaInput';
import QueryInput from '@/components/QueryInput';
import OutputPanel from '@/components/OutputPanel';
import { query } from './api';
import { QueryResponse, SchemaMetadata } from '@/lib/types';
import { parseSchemaJson } from '@/lib/templates';

export default function Home() {
  const [question, setQuestion] = useState('');
  const [schemaText, setSchemaText] = useState('');
  const [dialect, setDialect] = useState('postgres');
  const [isLoading, setIsLoading] = useState(false);
  const [response, setResponse] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    if (!question.trim()) return;

    setIsLoading(true);
    setError(null);
    setResponse(null);

    try {
      // Parse schema if provided
      let schema: SchemaMetadata | null = null;
      if (schemaText.trim()) {
        schema = parseSchemaJson(schemaText);
        if (!schema) {
          setError('Invalid schema JSON. Please check the format.');
          setIsLoading(false);
          return;
        }
      }

      const result = await query(question, { dialect, schema });
      setResponse(result);
    } catch (e) {
      console.error('Query error:', e);
      if (e instanceof Error) {
        setError(e.message);
      } else {
        setError('An unexpected error occurred. Please try again.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <main className="min-h-screen">
      {/* Header */}
      <header className="border-b border-midnight-800/50 bg-midnight-950/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
              <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
              </svg>
            </div>
            <div>
              <h1 className="text-xl font-bold text-white">text-ql</h1>
              <p className="text-xs text-midnight-400">Natural Language → SQL</p>
            </div>
          </div>

          {/* Dialect selector */}
          <div className="flex items-center gap-2">
            <label className="text-sm text-midnight-400">Dialect:</label>
            <select
              value={dialect}
              onChange={(e) => setDialect(e.target.value)}
              className="px-3 py-1.5 bg-midnight-800 border border-midnight-700 rounded-lg
                       text-sm text-midnight-200 focus:outline-none focus:ring-2 
                       focus:ring-blue-500/50 focus:border-blue-500"
            >
              <option value="postgres">PostgreSQL</option>
              <option value="mysql">MySQL</option>
              <option value="sqlite">SQLite</option>
            </select>
          </div>
        </div>
      </header>

      {/* Main content */}
      <div className="max-w-6xl mx-auto px-4 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Left column - Input */}
          <div className="space-y-6">
            <section>
              <SchemaInput
                value={schemaText}
                onChange={setSchemaText}
                disabled={isLoading}
              />
            </section>

            <section>
              <QueryInput
                value={question}
                onChange={setQuestion}
                onSubmit={handleSubmit}
                isLoading={isLoading}
                schemaText={schemaText}
              />
            </section>
          </div>

          {/* Right column - Output */}
          <div>
            <div className="sticky top-24">
              <h2 className="text-sm font-medium text-midnight-300 mb-3">Generated SQL</h2>
              <OutputPanel response={response} error={error} />
            </div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <footer className="border-t border-midnight-800/50 mt-auto">
        <div className="max-w-6xl mx-auto px-4 py-6">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-midnight-500">
            <p>
              Powered by{' '}
              <a 
                href="https://groq.com" 
                target="_blank" 
                rel="noopener noreferrer"
                className="text-midnight-400 hover:text-midnight-200 transition-colors"
              >
                Groq
              </a>
              {' '}& LLaMA 3.3
            </p>
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                API Connected
              </span>
            </div>
          </div>
        </div>
      </footer>
    </main>
  );
}
