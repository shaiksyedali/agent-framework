'use client';

import { useState } from 'react';
import type { WorkflowStep } from '../../lib/types';

interface Props {
  steps: WorkflowStep[];
  onChange: (steps: WorkflowStep[]) => void;
}

const baseSteps: Array<Omit<WorkflowStep, 'id'>> = [
  {
    title: 'Planner: propose workflow',
    description: 'Clarify intent, confirm data sources, emit step graph with approvals.',
    agent: 'planner'
  },
  {
    title: 'SQL agent: generate and run query',
    description: 'Hybrid RAG few-shot prompting with retries and approval for risky SQL.',
    agent: 'sql',
    requiresApproval: true
  },
  {
    title: 'RAG agent: retrieve docs',
    description: 'Semantic retrieval with cited snippets and metadata.',
    agent: 'rag'
  },
  {
    title: 'Reasoning agent: fuse evidence',
    description: 'Blend SQL rows + docs, call calculators for math, structure findings.',
    agent: 'reasoning'
  },
  {
    title: 'Responder: final output',
    description: 'Generate final response with citations, charts, and follow-up suggestions.',
    agent: 'responder'
  }
];

export default function StepList({ steps, onChange }: Props) {
  const [title, setTitle] = useState('Custom agent step');
  const [description, setDescription] = useState('');

  const remove = (id: string) => onChange(steps.filter(step => step.id !== id));

  const addBase = () => {
    if (steps.length === 0) {
      onChange(
        baseSteps.map(step => ({
          ...step,
          id: `${step.agent}-${Math.random().toString(36).slice(2, 6)}`
        }))
      );
    }
  };

  const addCustom = () => {
    if (!title.trim()) return;
    const newStep: WorkflowStep = {
      id: `custom-${Math.random().toString(36).slice(2, 6)}`,
      title,
      description,
      agent: 'custom'
    };
    onChange([...steps, newStep]);
    setTitle('Custom agent step');
    setDescription('');
  };

  return (
    <div style={{ marginTop: '1rem' }}>
      <div className="flex-row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <label className="section-title">Workflow steps</label>
        <div className="flex-row">
          <button className="button secondary" onClick={addBase}>
            Load recommended steps
          </button>
        </div>
      </div>
      <div className="timeline" style={{ marginTop: '0.75rem' }}>
        {steps.map(step => (
          <div key={step.id} className="timeline-step">
            <div className="flex-row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <strong>{step.title}</strong>
                <div style={{ color: 'var(--muted)', fontSize: '0.95rem', marginTop: '0.2rem' }}>
                  {step.description}
                </div>
                <div className="tag" style={{ marginTop: '0.35rem' }}>
                  {step.agent.toUpperCase()} {step.requiresApproval ? '• Requires approval' : ''}
                </div>
              </div>
              <button className="button danger" style={{ width: '120px' }} onClick={() => remove(step.id)}>
                Remove
              </button>
            </div>
          </div>
        ))}
        {steps.length === 0 && <div style={{ color: 'var(--muted)' }}>No steps yet. Load defaults or add your own.</div>}
      </div>
      <div className="card" style={{ marginTop: '0.75rem', padding: '0.85rem 1rem' }}>
        <div className="section-title">Add custom step</div>
        <input
          className="input"
          style={{ marginTop: '0.5rem' }}
          value={title}
          onChange={e => setTitle(e.target.value)}
          placeholder="Agent step title"
        />
        <textarea
          className="textarea"
          style={{ marginTop: '0.5rem' }}
          value={description}
          onChange={e => setDescription(e.target.value)}
          placeholder="Describe what this custom agent should do."
        />
        <div style={{ marginTop: '0.5rem' }}>
          <button className="button secondary" onClick={addCustom}>
            Add step
          </button>
        </div>
      </div>
    </div>
  );
}
