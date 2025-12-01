'use client';

interface Props {
  persona: string;
  goals: string;
  onChange: (persona: string, goals: string) => void;
}

export default function PersonaForm({ persona, goals, onChange }: Props) {
  return (
    <div style={{ marginTop: '1rem' }}>
      <label className="section-title">Persona & goals</label>
      <div className="split" style={{ marginTop: '0.5rem' }}>
        <div>
          <div style={{ marginBottom: '0.35rem', color: 'var(--muted)' }}>System persona</div>
          <textarea
            className="textarea"
            value={persona}
            onChange={e => onChange(e.target.value, goals)}
            placeholder="e.g., Precise fleet ops analyst that surfaces anomalies and recommends actions."
          />
        </div>
        <div>
          <div style={{ marginBottom: '0.35rem', color: 'var(--muted)' }}>Goals / instructions</div>
          <textarea
            className="textarea"
            value={goals}
            onChange={e => onChange(persona, e.target.value)}
            placeholder="Outline objectives, constraints, reporting formats, visualization needs."
          />
        </div>
      </div>
    </div>
  );
}
