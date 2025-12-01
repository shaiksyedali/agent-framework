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

const approvalModes = [
  { value: 'always_require', label: 'Always require approval' },
  { value: 'never_require', label: 'Skip approval (unsafe)' }
];

export default function DataSourcesForm({ knowledge, onChange }: Props) {
  const update = (partial: Partial<KnowledgeSources>) => onChange({ ...knowledge, ...partial });
  const engine = knowledge.database?.engine ?? 'sqlite';
  const dbValue = knowledge.database?.path ?? knowledge.database?.connectionString ?? '';
  const approvalMode = knowledge.database?.approvalMode ?? 'always_require';

  const dbValidation = (() => {
    if (engine === 'postgres') {
      if (!dbValue || !/^postgres(?:ql)?:\/\/.+/.test(dbValue)) {
        return 'Postgres requires a full connection string (postgres://user:pass@host:5432/db)';
      }
      return null;
    }
    if (!dbValue) {
      return 'Provide a file path for SQLite/DuckDB (e.g., /data/metrics.db).';
    }
    return null;
  })();

  const mcpValidation = knowledge.mcpServer && !/^https?:\/\//.test(knowledge.mcpServer)
    ? 'MCP server must be an http(s) URL exposed by the backend.'
    : null;

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
          <textarea
            className="textarea"
            style={{ marginTop: '0.5rem' }}
            placeholder="Optional: paste a representative doc to ingest with the workflow"
            value={knowledge.documentText ?? ''}
            onChange={e => update({ documentText: e.target.value })}
          />
        </div>
        <div className="card" style={{ padding: '0.75rem 1rem' }}>
          <div className="section-title">Structured (SQL)</div>
          <select
            className="select"
            style={{ marginTop: '0.5rem' }}
            value={engine}
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
            value={dbValue}
            onChange={e => {
              const value = e.target.value;
              const isConnection = value.includes('://');
              update({
                database: {
                  engine: knowledge.database?.engine ?? 'sqlite',
                  path: isConnection ? undefined : value,
                  connectionString: isConnection ? value : undefined,
                  approvalMode: knowledge.database?.approvalMode ?? 'always_require',
                  allowWrites: knowledge.database?.allowWrites ?? false
                }
              });
            }}
          />
          <div className="split" style={{ marginTop: '0.35rem' }}>
            <div>
              <label className="section-title">Approval policy</label>
              <select
                className="select"
                style={{ marginTop: '0.25rem' }}
                value={approvalMode}
                onChange={e =>
                  update({
                    database: {
                      ...knowledge.database,
                      engine,
                      approvalMode: e.target.value as 'always_require' | 'never_require'
                    }
                  })
                }
              >
                {approvalModes.map(mode => (
                  <option key={mode.value} value={mode.value}>
                    {mode.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="section-title">Writes</label>
              <div style={{ marginTop: '0.55rem' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: 'var(--muted)' }}>
                  <input
                    type="checkbox"
                    checked={Boolean(knowledge.database?.allowWrites)}
                    onChange={e =>
                      update({
                        database: {
                          ...knowledge.database,
                          engine,
                          allowWrites: e.target.checked,
                          approvalMode
                        }
                      })
                    }
                  />
                  Allow UPDATE/DELETE
                </label>
              </div>
            </div>
          </div>
          {dbValidation && (
            <p className="muted" style={{ marginTop: '0.25rem', color: 'var(--danger)' }}>
              {dbValidation}
            </p>
          )}
        </div>
        <div className="card" style={{ padding: '0.75rem 1rem' }}>
          <div className="section-title">MCP server</div>
          <input
            className="input"
            style={{ marginTop: '0.5rem' }}
            placeholder="http(s) MCP endpoint exposed by backend"
            value={knowledge.mcpServer ?? ''}
            onChange={e => update({ mcpServer: e.target.value })}
          />
          {mcpValidation && (
            <p className="muted" style={{ marginTop: '0.25rem', color: 'var(--danger)' }}>
              {mcpValidation}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
