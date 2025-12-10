'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { listWorkflows, deleteWorkflow } from '../lib/apiClient';
import type { WorkflowConfig } from '../lib/types';

export default function WorkflowsListPage() {
  const router = useRouter();
  const [workflows, setWorkflows] = useState<WorkflowConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadWorkflows();
  }, []);

  const loadWorkflows = async () => {
    try {
      setLoading(true);
      const data = await listWorkflows();
      setWorkflows(data);
      setError(null);
    } catch (err) {
      setError('Failed to load workflows');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (workflowId: string, workflowName: string) => {
    if (!confirm(`Are you sure you want to delete "${workflowName}"?`)) {
      return;
    }

    try {
      await deleteWorkflow(workflowId);
      await loadWorkflows();
    } catch (err) {
      setError('Failed to delete workflow');
      console.error(err);
    }
  };

  const handleEdit = (workflowId: string) => {
    router.push(`/builder?id=${workflowId}`);
  };

  const handleRun = (workflowId: string) => {
    router.push(`/execute?id=${workflowId}`);
  };

  const handleCreateNew = () => {
    router.push('/builder');
  };

  return (
    <div style={{
      minHeight: '100vh',
      backgroundColor: '#F9FAFB',
      padding: '2rem'
    }}>
      {/* Header */}
      <div style={{
        maxWidth: '1400px',
        margin: '0 auto',
        marginBottom: '2rem',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <div>
          <h1 style={{
            fontSize: '2rem',
            fontWeight: 700,
            color: '#111827',
            margin: '0 0 0.5rem 0'
          }}>
            Agentic Workflows
          </h1>
          <p style={{
            fontSize: '1rem',
            color: '#6B7280',
            margin: 0
          }}>
            Manage your workflows.
          </p>
        </div>

        <button
          onClick={handleCreateNew}
          style={{
            padding: '0.75rem 1.5rem',
            backgroundColor: '#111827',
            color: 'white',
            border: 'none',
            borderRadius: '8px',
            cursor: 'pointer',
            fontSize: '1rem',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem'
          }}
        >
          <span>+</span> Create Workflow
        </button>
      </div>

      {/* Error Message */}
      {error && (
        <div style={{
          maxWidth: '1400px',
          margin: '0 auto 1.5rem auto',
          padding: '1rem',
          backgroundColor: '#FEE2E2',
          border: '1px solid #EF4444',
          borderRadius: '8px',
          color: '#991B1B'
        }}>
          {error}
        </div>
      )}

      {/* Loading State */}
      {loading && (
        <div style={{
          maxWidth: '1400px',
          margin: '0 auto',
          textAlign: 'center',
          padding: '3rem',
          color: '#6B7280'
        }}>
          Loading workflows...
        </div>
      )}

      {/* Workflows Grid */}
      {!loading && (
        <div style={{
          maxWidth: '1400px',
          margin: '0 auto',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(450px, 1fr))',
          gap: '1.5rem'
        }}>
          {workflows.length === 0 ? (
            <div style={{
              gridColumn: '1 / -1',
              textAlign: 'center',
              padding: '4rem 2rem',
              backgroundColor: 'white',
              borderRadius: '12px',
              border: '2px dashed #E5E7EB'
            }}>
              <p style={{
                fontSize: '1.25rem',
                color: '#6B7280',
                marginBottom: '1rem'
              }}>
                No workflows yet
              </p>
              <p style={{
                fontSize: '1rem',
                color: '#9CA3AF',
                marginBottom: '1.5rem'
              }}>
                Create your first workflow to get started
              </p>
              <button
                onClick={handleCreateNew}
                style={{
                  padding: '0.75rem 1.5rem',
                  backgroundColor: '#3B82F6',
                  color: 'white',
                  border: 'none',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  fontSize: '1rem',
                  fontWeight: 600
                }}
              >
                + Create Workflow
              </button>
            </div>
          ) : (
            workflows.map((workflow) => (
              <div
                key={workflow.id}
                style={{
                  backgroundColor: 'white',
                  borderRadius: '12px',
                  padding: '1.5rem',
                  border: '1px solid #E5E7EB',
                  boxShadow: '0 1px 3px rgba(0, 0, 0, 0.1)'
                }}
              >
                {/* Workflow Header */}
                <h2 style={{
                  fontSize: '1.25rem',
                  fontWeight: 600,
                  color: '#111827',
                  margin: '0 0 0.5rem 0'
                }}>
                  {workflow.name}
                </h2>

                {/* Workflow Description */}
                <p style={{
                  fontSize: '0.95rem',
                  color: '#6B7280',
                  margin: '0 0 1rem 0',
                  lineHeight: '1.5'
                }}>
                  {workflow.description}
                </p>

                {/* Agents Count */}
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  fontSize: '0.9rem',
                  color: '#6B7280',
                  marginBottom: '1.5rem'
                }}>
                  <span>📋</span>
                  <span>{workflow.agents.length} Agent{workflow.agents.length !== 1 ? 's' : ''}</span>
                </div>

                {/* Action Buttons */}
                <div style={{
                  display: 'flex',
                  gap: '0.75rem'
                }}>
                  <button
                    onClick={() => handleEdit(workflow.id!)}
                    style={{
                      flex: 1,
                      padding: '0.65rem 1rem',
                      backgroundColor: 'white',
                      color: '#374151',
                      border: '1px solid #D1D5DB',
                      borderRadius: '6px',
                      cursor: 'pointer',
                      fontSize: '0.9rem',
                      fontWeight: 500
                    }}
                  >
                    Edit
                  </button>

                  <button
                    onClick={() => handleDelete(workflow.id!, workflow.name)}
                    style={{
                      padding: '0.65rem 1rem',
                      backgroundColor: '#FEE2E2',
                      color: '#DC2626',
                      border: '1px solid #FCA5A5',
                      borderRadius: '6px',
                      cursor: 'pointer',
                      fontSize: '0.9rem',
                      fontWeight: 500
                    }}
                  >
                    🗑️
                  </button>

                  <button
                    onClick={() => handleRun(workflow.id!)}
                    style={{
                      flex: 1,
                      padding: '0.65rem 1rem',
                      backgroundColor: '#111827',
                      color: 'white',
                      border: 'none',
                      borderRadius: '6px',
                      cursor: 'pointer',
                      fontSize: '0.9rem',
                      fontWeight: 600
                    }}
                  >
                    ▶️ Run
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
