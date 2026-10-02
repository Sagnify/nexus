import React, { useState } from 'react';
import { AlertCircle, Send } from 'lucide-react';

export interface ParameterDefinition {
  name: string;
  type: 'string' | 'email' | 'date' | 'number' | 'filepath';
  description: string;
  required: boolean;
  default_value?: string;
}

export interface ParameterCollectionProps {
  skillName: string;
  missingParameters: ParameterDefinition[];
  resolvedParameters: Record<string, string>;
  onSubmit: (parameters: Record<string, string>) => void;
  onCancel: () => void;
}

export const ParameterCollection: React.FC<ParameterCollectionProps> = ({
  skillName,
  missingParameters,
  resolvedParameters,
  onSubmit,
  onCancel,
}) => {
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  const handleInputChange = (paramName: string, value: string) => {
    setFormValues(prev => ({ ...prev, [paramName]: value }));
    if (errors[paramName]) {
      setErrors(prev => {
        const newErrors = { ...prev };
        delete newErrors[paramName];
        return newErrors;
      });
    }
  };

  const validateForm = (): boolean => {
    const newErrors: Record<string, string> = {};

    for (const param of missingParameters) {
      const value = formValues[param.name]?.trim();
      if (!value) {
        newErrors[param.name] = `${param.description} is required`;
        continue;
      }

      if (param.type === 'email') {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(value)) {
          newErrors[param.name] = 'Please enter a valid email address';
        }
      } else if (param.type === 'number') {
        if (isNaN(Number(value))) {
          newErrors[param.name] = 'Please enter a valid number';
        }
      } else if (param.type === 'date') {
        const dateRegex = /^\d{4}-\d{2}-\d{2}$|^\d{1,2}\/\d{1,2}\/\d{4}$/;
        if (!dateRegex.test(value)) {
          newErrors[param.name] = 'Please enter a valid date (YYYY-MM-DD or MM/DD/YYYY)';
        }
      }
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (validateForm()) {
      const allParameters = { ...resolvedParameters, ...formValues };
      onSubmit(allParameters);
    }
  };

  const getInputType = (paramType: string): string => {
    switch (paramType) {
      case 'email':
        return 'email';
      case 'number':
        return 'number';
      case 'date':
        return 'date';
      default:
        return 'text';
    }
  };

  const getPlaceholder = (param: ParameterDefinition): string => {
    if (param.default_value) {
      return `e.g., ${param.default_value}`;
    }
    switch (param.type) {
      case 'email':
        return 'user@example.com';
      case 'date':
        return 'YYYY-MM-DD';
      case 'number':
        return '0';
      default:
        return param.description;
    }
  };

  return (
    <div className="w-full max-w-md mx-auto p-4 rounded-xl bg-slate-900 border border-slate-700 shadow-lg">
      {/* Header */}
      <div className="mb-4">
        <h3 className="text-sm font-semibold text-white mb-1">
          {skillName}
        </h3>
        <p className="text-xs text-slate-400">
          Please provide the missing information to continue
        </p>
      </div>

      {/* Already resolved parameters info */}
      {Object.keys(resolvedParameters).length > 0 && (
        <div className="mb-4 p-2 bg-emerald-500/10 border border-emerald-500/20 rounded-lg">
          <p className="text-xs text-emerald-300">
            Extracted from your request:
          </p>
          <div className="mt-1 space-y-1">
            {Object.entries(resolvedParameters).map(([key, value]) => (
              <div key={key} className="text-xs text-emerald-200">
                <span className="font-mono text-emerald-400">{key}</span>: {value}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-3">
        {missingParameters.map(param => (
          <div key={param.name}>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              {param.description}
              {param.required && <span className="text-red-400 ml-1">*</span>}
            </label>
            <input
              type={getInputType(param.type)}
              value={formValues[param.name] || ''}
              onChange={e => handleInputChange(param.name, e.target.value)}
              placeholder={getPlaceholder(param)}
              className={`w-full px-3 py-2 rounded-lg bg-slate-800 border text-sm text-white placeholder-slate-500 outline-none transition-colors ${
                errors[param.name]
                  ? 'border-red-500 focus:border-red-400'
                  : 'border-slate-600 focus:border-blue-500'
              }`}
            />
            {errors[param.name] && (
              <div className="mt-1 flex items-center gap-1 text-xs text-red-400">
                <AlertCircle className="w-3 h-3" />
                {errors[param.name]}
              </div>
            )}
          </div>
        ))}

        {/* Actions */}
        <div className="flex gap-2 pt-2">
          <button
            type="button"
            onClick={onCancel}
            className="flex-1 px-3 py-2 rounded-lg text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 border border-slate-600 transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            className="flex-1 px-3 py-2 rounded-lg text-xs font-medium text-white bg-blue-600 hover:bg-blue-500 border border-blue-500 flex items-center justify-center gap-1 transition-colors"
          >
            <Send className="w-3 h-3" />
            Continue
          </button>
        </div>
      </form>
    </div>
  );
};

export default ParameterCollection;
