'use client';

import { useMemo } from 'react';
import type { KnowledgeSources, SqlEngine, WorkflowDefinition, WorkflowStep } from '../lib/types';
import DataSourcesForm from './forms/DataSourcesForm';
import PersonaForm from './forms/PersonaForm';
import StepList from './forms/StepList';

interface Props {
  definition: WorkflowDefinition;
  onChange: (definition: WorkflowDefinition) => void;
  onSubmit: () => void | Promise<void>;
  busy?: boolean;
}

const engines: Array<{ value: SqlEngine; label: string }> = [
  { value: 'sqlite', label: 'SQLite' },
  { value: 'duckdb', label: 'DuckDB' },
  { value: 'postgres', label: 'Postgres' }
];

export default function WorkflowBuilder({ definition, onChange, onSubmit, busy }: Props) {
  const canSubmit = useMemo(
    () => Boolean(definition.name && definition.persona && definition.steps.length > 0),
    [definition]
  );

  const update = (partial: Partial<WorkflowDefinition>) => onChange({ ...definition, ...partial });

  const updateKnowledge = (knowledge: KnowledgeSources) => update({ knowledge });
  const updateSteps = (steps: WorkflowStep[]) => update({ steps });

  return (
    <div className="card">
      <div className="flex-row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>Configure workflow</h2>
        <div className="tag">Multi-agent • HIL approvals</div>
      </div>
      <div className="split">
        <div>
          <label className="section-title">Name</label>
          <input
            className="input"
            value={definition.name}
            onChange={e => update({ name: e.target.value })}
            placeholder="Fleet diagnostics, project planner, ops console..."
          />
        </div>
        <div>
          <label className="section-title">SQL engine</label>
          <select
            className="select"
            value={definition.sqlEngine}
            onChange={e => update({ sqlEngine: e.target.value as SqlEngine })}
          >
            {engines.map(engine => (
              <option key={engine.value} value={engine.value}>
                {engine.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <PersonaForm
        persona={definition.persona}
        goals={definition.goals}
        onChange={(persona, goals) => update({ persona, goals })}
      />
      <DataSourcesForm knowledge={definition.knowledge} onChange={updateKnowledge} />
      <StepList steps={definition.steps} onChange={updateSteps} />
      <div style={{ marginTop: '1rem' }}>
        <button className="button primary" onClick={onSubmit} disabled={!canSubmit || busy}>
          {busy ? 'Starting run...' : 'Start run with approvals'}
        </button>
      </div>
    </div>
  );
}
