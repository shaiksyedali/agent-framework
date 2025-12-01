'use client';

import type { KnowledgeSources, SqlEngine } from '../../lib/types';

interface Props {
  knowledge: KnowledgeSources;
  onChange: (knowledge: KnowledgeSources) => void;
}

const engines: Array<{ value: SqlEngine; label: string }> = [
  { value: 'sqlite', label: 'SQLite' },
  { value: 'duckdb', label: 'DuckDB' },
  { value: 'postgres', label: 'Postgres' }
];

export default function DataSourcesForm({ knowledge, onChange }: Props) {
  const update = (partial: Partial<KnowledgeSources>) => onChange({ ...knowledge, ...partial });

  return (
    <div style={{ marginTop: '1rem' }}>
      <label className="section-title">Knowledge sources</label>
      <div className="split" style={{ marginTop: '0.5rem' }}>
        <div className="card" style={{ padding: '0.75rem 1rem' }}>
          <div className="section-title">Unstructured (RAG)</div>
          <input
            className="input"
            style={{ marginTop: '0.5rem' }}
            placeholder="Path or bucket to documents"
            value={knowledge.documentsPath ?? ''}
            onChange={e => update({ documentsPath: e.target.value })}
          />
        </div>
        <div className="card" style={{ padding: '0.75rem 1rem' }}>
          <div className="section-title">Structured (SQL)</div>
          <select
            className="select"
            style={{ marginTop: '0.5rem' }}
            value={knowledge.database?.engine ?? 'sqlite'}
            onChange={e => update({ database: { ...knowledge.database, engine: e.target.value as SqlEngine } })}
          >
            {engines.map(engine => (
              <option key={engine.value} value={engine.value}>
                {engine.label}
              </option>
            ))}
          </select>
          <input
            className="input"
            style={{ marginTop: '0.5rem' }}
            placeholder="File path (sqlite/duckdb) or connection string (postgres)"
            value={knowledge.database?.path ?? knowledge.database?.connectionString ?? ''}
            onChange={e => {
              const value = e.target.value;
              const isConnection = value.includes('://');
              update({
                database: {
                  engine: knowledge.database?.engine ?? 'sqlite',
                  path: isConnection ? undefined : value,
                  connectionString: isConnection ? value : undefined
                }
              });
            }}
          />
        </div>
        <div className="card" style={{ padding: '0.75rem 1rem' }}>
          <div className="section-title">MCP server</div>
          <input
            className="input"
            style={{ marginTop: '0.5rem' }}
            placeholder="wss:// or grpc target"
            value={knowledge.mcpServer ?? ''}
            onChange={e => update({ mcpServer: e.target.value })}
          />
        </div>
      </div>
    </div>
  );
}
