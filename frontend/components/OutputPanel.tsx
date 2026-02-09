'use client';

import { useState } from 'react';
import { QueryResponse, STATUS_STYLES } from '@/lib/types';
import { copyToClipboard } from '@/app/api';

interface OutputPanelProps {
  response: QueryResponse | null;
  error: string | null;
}

export default function OutputPanel({ response, error }: OutputPanelProps) {
  const [copied, setCopied] = useState(false);

  if (error) {
    return (
      <div className="p-6 bg-red-500/10 border border-red-500/30 rounded-lg">
        <div className="flex items-start gap-3">
          <svg className="w-5 h-5 text-red-400 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <div>
            <h3 className="font-medium text-red-400">Error</h3>
            <p className="mt-1 text-sm text-red-300/80">{error}</p>
          </div>
        </div>
      </div>
    );
  }

  if (!response) {
    return (
      <div className="p-12 border-2 border-dashed border-midnight-700 rounded-lg text-center">
        <svg className="w-12 h-12 mx-auto text-midnight-600 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
        </svg>
        <p className="text-midnight-500">Your generated SQL will appear here</p>
      </div>
    );
  }

  const statusStyle = STATUS_STYLES[response.status];

  const handleCopy = async () => {
    if (response.sql) {
      const success = await copyToClipboard(response.sql);
      if (success) {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    }
  };

  return (
    <div className="space-y-4">
      {/* Status badge */}
      <div className="flex items-center justify-between">
        <div className={`inline-flex items-center gap-2 px-3 py-1 rounded-full ${statusStyle.bg}`}>
          <span className={`w-2 h-2 rounded-full ${statusStyle.text} bg-current`} />
          <span className={`text-sm font-medium ${statusStyle.text}`}>
            {statusStyle.label}
          </span>
        </div>
        
        {response.sql && (
          <button
            onClick={handleCopy}
            className="flex items-center gap-2 px-3 py-1.5 text-sm text-midnight-300 
                     hover:text-midnight-100 hover:bg-midnight-800 rounded-lg transition-all"
          >
            {copied ? (
              <>
                <svg className="w-4 h-4 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                Copied!
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                Copy SQL
              </>
            )}
          </button>
        )}
      </div>

      {/* SQL output */}
      {response.sql && (
        <div className="relative">
          <pre className="p-4 bg-midnight-950 border border-midnight-800 rounded-lg overflow-x-auto">
            <code className="text-sm font-mono text-blue-300 whitespace-pre-wrap">
              {highlightSql(response.sql)}
            </code>
          </pre>
        </div>
      )}

      {/* Policy errors */}
      {response.policy_errors.length > 0 && (
        <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-lg space-y-2">
          <h4 className="text-sm font-medium text-red-400">Policy Errors</h4>
          <ul className="space-y-1">
            {response.policy_errors.map((error, i) => (
              <li key={i} className="text-sm text-red-300/80 flex items-start gap-2">
                <span className="text-red-400">•</span>
                {error}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Warnings */}
      {response.warnings.length > 0 && (
        <div className="p-4 bg-amber-500/10 border border-amber-500/30 rounded-lg space-y-2">
          <h4 className="text-sm font-medium text-amber-400">Warnings</h4>
          <ul className="space-y-1">
            {response.warnings.map((warning, i) => (
              <li key={i} className="text-sm text-amber-300/80 flex items-start gap-2">
                <span className="text-amber-400">•</span>
                {warning}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Placeholders */}
      {response.placeholders.length > 0 && (
        <div className="p-4 bg-midnight-800/50 border border-midnight-700 rounded-lg space-y-2">
          <h4 className="text-sm font-medium text-midnight-300">Placeholders to Replace</h4>
          <div className="space-y-2">
            {response.placeholders.map((placeholder, i) => (
              <div key={i} className="flex items-start gap-3 text-sm">
                <code className="px-2 py-0.5 bg-midnight-900 text-blue-400 rounded font-mono">
                  {placeholder.token}
                </code>
                <span className="text-midnight-400">{placeholder.meaning}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Clarifying questions */}
      {response.clarifying_questions.length > 0 && (
        <div className="p-4 bg-blue-500/10 border border-blue-500/30 rounded-lg space-y-2">
          <h4 className="text-sm font-medium text-blue-400">Clarifying Questions</h4>
          <ul className="space-y-1">
            {response.clarifying_questions.map((question, i) => (
              <li key={i} className="text-sm text-blue-300/80 flex items-start gap-2">
                <span className="text-blue-400">?</span>
                {question}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Assumptions */}
      {response.assumptions.length > 0 && (
        <div className="p-4 bg-midnight-800/30 border border-midnight-700/50 rounded-lg space-y-2">
          <h4 className="text-sm font-medium text-midnight-400">Assumptions Made</h4>
          <ul className="space-y-1">
            {response.assumptions.map((assumption, i) => (
              <li key={i} className="text-sm text-midnight-500 flex items-start gap-2">
                <span className="text-midnight-600">→</span>
                {assumption}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/**
 * Simple SQL syntax highlighting.
 */
function highlightSql(sql: string): React.ReactNode {
  // Keywords to highlight
  const keywords = [
    'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'NOT', 'IN', 'LIKE', 'BETWEEN',
    'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'FULL', 'CROSS', 'ON',
    'GROUP', 'BY', 'ORDER', 'HAVING', 'LIMIT', 'OFFSET', 'ASC', 'DESC',
    'INSERT', 'INTO', 'VALUES', 'UPDATE', 'SET', 'DELETE', 'DROP', 'CREATE',
    'TABLE', 'INDEX', 'ALTER', 'ADD', 'COLUMN', 'TRUNCATE',
    'AS', 'DISTINCT', 'ALL', 'UNION', 'EXCEPT', 'INTERSECT',
    'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'NULL', 'IS',
    'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'WITH', 'RECURSIVE',
    'GRANT', 'REVOKE', 'TRUE', 'FALSE',
  ];

  // Split by whitespace while preserving it
  const parts = sql.split(/(\s+|[(),;])/);

  return parts.map((part, i) => {
    const upperPart = part.toUpperCase();

    // Placeholder
    if (part.match(/^<[A-Z][A-Z0-9_]*>$/)) {
      return (
        <span key={i} className="text-amber-400 bg-amber-400/10 px-1 rounded">
          {part}
        </span>
      );
    }

    // Keyword
    if (keywords.includes(upperPart)) {
      return (
        <span key={i} className="text-purple-400 font-semibold">
          {part}
        </span>
      );
    }

    // String literal
    if (part.startsWith("'") && part.endsWith("'")) {
      return (
        <span key={i} className="text-emerald-400">
          {part}
        </span>
      );
    }

    // Number
    if (part.match(/^\d+$/)) {
      return (
        <span key={i} className="text-orange-400">
          {part}
        </span>
      );
    }

    // Punctuation
    if (part.match(/^[(),;]$/)) {
      return (
        <span key={i} className="text-midnight-400">
          {part}
        </span>
      );
    }

    // Default
    return <span key={i}>{part}</span>;
  });
}
