'use client';

import { useState, useEffect } from 'react';
import { SCHEMA_TEMPLATES, EXAMPLE_QUESTIONS } from '@/lib/templates';

interface QueryInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  isLoading: boolean;
  schemaText: string;
}

export default function QueryInput({
  value,
  onChange,
  onSubmit,
  isLoading,
  schemaText,
}: QueryInputProps) {
  const [suggestions, setSuggestions] = useState<string[]>([]);

  // Detect which template schema is loaded and show relevant suggestions
  useEffect(() => {
    try {
      const parsed = JSON.parse(schemaText);
      if (parsed?.tables) {
        // Find matching template
        for (const template of SCHEMA_TEMPLATES) {
          const templateTables = template.schema.tables.map(t => t.name).sort();
          const schemaTables = parsed.tables.map((t: { name: string }) => t.name).sort();
          
          if (JSON.stringify(templateTables) === JSON.stringify(schemaTables)) {
            setSuggestions(EXAMPLE_QUESTIONS[template.name] || []);
            return;
          }
        }
      }
    } catch {
      // Not valid JSON, ignore
    }
    setSuggestions([]);
  }, [schemaText]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      onSubmit();
    }
  };

  const handleSuggestionClick = (suggestion: string) => {
    onChange(suggestion);
  };

  return (
    <div className="space-y-3">
      <label className="block text-sm font-medium text-midnight-300">
        Your Question
      </label>

      {/* Example suggestions */}
      {suggestions.length > 0 && (
        <div className="flex flex-wrap gap-2">
          <span className="text-xs text-midnight-500 self-center">Try:</span>
          {suggestions.slice(0, 3).map((suggestion, index) => (
            <button
              key={index}
              type="button"
              onClick={() => handleSuggestionClick(suggestion)}
              disabled={isLoading}
              className="px-3 py-1 text-xs rounded-full bg-midnight-800/50 text-midnight-400
                       hover:bg-midnight-700 hover:text-midnight-200 transition-all
                       border border-midnight-800 hover:border-midnight-600
                       disabled:opacity-50 disabled:cursor-not-allowed
                       max-w-[200px] truncate"
              title={suggestion}
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}

      {/* Question textarea */}
      <div className="relative">
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isLoading}
          placeholder="Ask a question in plain English, e.g., 'Show me all customers from California who spent more than $1000'"
          className="w-full h-24 px-4 py-3 bg-midnight-900 border border-midnight-700 rounded-lg
                   text-midnight-100 text-sm placeholder-midnight-500
                   focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500
                   disabled:opacity-50 disabled:cursor-not-allowed
                   resize-y min-h-[80px]"
        />
        <div className="absolute bottom-3 right-3 text-xs text-midnight-600">
          {navigator.platform.includes('Mac') ? '⌘' : 'Ctrl'}+Enter to submit
        </div>
      </div>

      {/* Submit button */}
      <button
        type="button"
        onClick={onSubmit}
        disabled={isLoading || !value.trim()}
        className="w-full px-6 py-3 bg-blue-600 hover:bg-blue-500 disabled:bg-midnight-700
                 text-white font-medium rounded-lg transition-all
                 disabled:opacity-50 disabled:cursor-not-allowed
                 flex items-center justify-center gap-2"
      >
        {isLoading ? (
          <>
            <LoadingSpinner />
            Generating SQL...
          </>
        ) : (
          <>
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            Generate SQL
          </>
        )}
      </button>
    </div>
  );
}

function LoadingSpinner() {
  return (
    <svg className="animate-spin h-5 w-5" fill="none" viewBox="0 0 24 24">
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}
