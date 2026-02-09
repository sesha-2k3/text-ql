'use client';

import { SCHEMA_TEMPLATES, schemaToJson } from '@/lib/templates';

interface SchemaInputProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

export default function SchemaInput({ value, onChange, disabled }: SchemaInputProps) {
  const handleTemplateClick = (templateName: string) => {
    const template = SCHEMA_TEMPLATES.find(t => t.name === templateName);
    if (template) {
      onChange(schemaToJson(template.schema));
    }
  };

  const handleClear = () => {
    onChange('');
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="block text-sm font-medium text-midnight-300">
          Database Schema
          <span className="ml-2 text-midnight-500 font-normal">(optional)</span>
        </label>
        {value && (
          <button
            type="button"
            onClick={handleClear}
            disabled={disabled}
            className="text-xs text-midnight-400 hover:text-midnight-200 transition-colors disabled:opacity-50"
          >
            Clear
          </button>
        )}
      </div>

      {/* Template buttons */}
      <div className="flex flex-wrap gap-2">
        <span className="text-xs text-midnight-500 self-center">Templates:</span>
        {SCHEMA_TEMPLATES.map((template) => (
          <button
            key={template.name}
            type="button"
            onClick={() => handleTemplateClick(template.name)}
            disabled={disabled}
            className="px-3 py-1 text-xs rounded-full bg-midnight-800 text-midnight-300 
                     hover:bg-midnight-700 hover:text-midnight-100 transition-all
                     border border-midnight-700 hover:border-midnight-500
                     disabled:opacity-50 disabled:cursor-not-allowed"
            title={template.description}
          >
            {template.name}
          </button>
        ))}
      </div>

      {/* Schema textarea */}
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder={`{
  "tables": [
    {
      "name": "users",
      "columns": [
        { "name": "id", "type": "integer", "primary_key": true },
        { "name": "email", "type": "varchar" }
      ]
    }
  ]
}`}
        className="w-full h-48 px-4 py-3 bg-midnight-900 border border-midnight-700 rounded-lg
                 text-midnight-100 text-sm font-mono placeholder-midnight-600
                 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500
                 disabled:opacity-50 disabled:cursor-not-allowed
                 resize-y min-h-[120px]"
        spellCheck={false}
      />

      {/* Validation indicator */}
      {value && (
        <SchemaValidationIndicator value={value} />
      )}
    </div>
  );
}

function SchemaValidationIndicator({ value }: { value: string }) {
  let isValid = false;
  let errorMessage = '';

  try {
    const parsed = JSON.parse(value);
    if (parsed && Array.isArray(parsed.tables)) {
      isValid = true;
    } else {
      errorMessage = 'Schema must have a "tables" array';
    }
  } catch (e) {
    errorMessage = 'Invalid JSON syntax';
  }

  if (isValid) {
    return (
      <div className="flex items-center gap-2 text-xs text-emerald-400">
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
        Valid JSON schema
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 text-xs text-amber-400">
      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
      </svg>
      {errorMessage}
    </div>
  );
}
