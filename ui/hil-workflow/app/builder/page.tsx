'use client';

import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  listAgents,
  createWorkflow,
  getWorkflow,
  executeWorkflow,
  getJobStatus,
  resumeJob,
  createPlan
} from '../../lib/apiClient';
import type {
  AgentConfig,
  WorkflowConfig,
  JobStatus,
  DataSourceConfig,
  WorkflowStep
} from '../../lib/types';
import { FileExplorer } from '@/components/file-explorer';

type TabType = 'agents' | 'teams' | 'data_sources' | 'steps';

export default function WorkflowBuilder() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const workflowId = searchParams.get('id');
  const autoExecute = searchParams.get('execute') === 'true';

  // Basic Info
  const [workflowName, setWorkflowName] = useState('');
  const [workflowDescription, setWorkflowDescription] = useState('');
  const [userIntent, setUserIntent] = useState('');
  const [savedWorkflowId, setSavedWorkflowId] = useState<string | null>(workflowId);

  // Tabs
  const [activeTab, setActiveTab] = useState<TabType>('data_sources');

  // Agents
  const [availableAgents, setAvailableAgents] = useState<AgentConfig[]>([]);
  const [selectedAgents, setSelectedAgents] = useState<AgentConfig[]>([]);

  // Teams
  const [teams, setTeams] = useState<any[]>([]);

  // Data Sources
  const [dataSources, setDataSources] = useState<DataSourceConfig[]>([]);
  const [currentDataSource, setCurrentDataSource] = useState<Partial<DataSourceConfig>>({
    name: '',
    type: 'database',
    path: '',
    connection_string: '',
    url: ''
  });
  const [showFileExplorer, setShowFileExplorer] = useState(false);

  // Steps
  const [steps, setSteps] = useState<WorkflowStep[]>([]);

  // Execution
  const [currentJob, setCurrentJob] = useState<JobStatus | null>(null);
  const [executing, setExecuting] = useState(false);

  // Auto-Plan
  const [showAutoPlanModal, setShowAutoPlanModal] = useState(false);
  const [autoPlanLoading, setAutoPlanLoading] = useState(false);
  const [plannedWorkflow, setPlannedWorkflow] = useState<WorkflowConfig | null>(null);
  const [showPlanReview, setShowPlanReview] = useState(false);

  // Errors
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Load available agents on mount
  useEffect(() => {
    loadAgents();

    // Load existing workflow if editing
    if (workflowId) {
      loadWorkflow(workflowId);
    }
  }, []);

  // Auto-execute if needed
  useEffect(() => {
    if (autoExecute && savedWorkflowId && !executing && !currentJob) {
      handleExecute();
    }
  }, [autoExecute, savedWorkflowId]);

  // Poll job status
  useEffect(() => {
    if (currentJob && (currentJob.status === 'running' || currentJob.status === 'waiting_for_user')) {
      const interval = setInterval(async () => {
        try {
          const job = await getJobStatus(currentJob.id);
          setCurrentJob(job);
          if (job.status === 'completed' || job.status === 'failed') {
            clearInterval(interval);
            setExecuting(false);
          }
        } catch (err) {
          console.error('Error polling job:', err);
        }
      }, 1000);
      return () => clearInterval(interval);
    }
  }, [currentJob]);

  const loadAgents = async () => {
    try {
      const agents = await listAgents();
      setAvailableAgents(agents);
    } catch (err) {
      setError('Failed to load agents');
      console.error(err);
    }
  };

  const loadWorkflow = async (id: string) => {
    try {
      const workflow = await getWorkflow(id);
      setWorkflowName(workflow.name);
      setWorkflowDescription(workflow.description);
      setUserIntent(workflow.user_intent || '');
      setSelectedAgents(workflow.agents);
      setDataSources(workflow.data_sources || []);
      setSteps(workflow.steps || []);
    } catch (err) {
      setError('Failed to load workflow');
      console.error(err);
    }
  };

  // Data Source Management
  const addDataSource = () => {
    if (!currentDataSource.name || !currentDataSource.type) {
      setError('Please provide name and type for data source');
      return;
    }

    const newDataSource: DataSourceConfig = {
      id: `ds-${Date.now()}`,
      name: currentDataSource.name,
      type: currentDataSource.type as 'file' | 'database' | 'mcp_server',
      path: currentDataSource.path,
      connection_string: currentDataSource.connection_string,
      url: currentDataSource.url
    };

    setDataSources([...dataSources, newDataSource]);

    // Reset form
    setCurrentDataSource({
      name: '',
      type: 'database',
      path: '',
      connection_string: '',
      url: ''
    });

    setError(null);
  };

  const removeDataSource = (index: number) => {
    setDataSources(dataSources.filter((_, i) => i !== index));
  };

  const handleBrowseFile = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.db,.duckdb';
    input.onchange = (e: any) => {
      const file = e.target.files[0];
      if (file) {
        setCurrentDataSource({
          ...currentDataSource,
          path: file.name
        });
      }
    };
    input.click();
  };

  // Auto-Plan with AI
  const handleAutoPlan = async () => {
    if (!userIntent.trim()) {
      setError('Please provide a user intent/prompt for AI planning');
      return;
    }

    setAutoPlanLoading(true);
    setError(null);

    try {
      const plan = await createPlan({
        user_request: userIntent,
        data_sources: dataSources
      });

      // Show plan for review instead of auto-applying
      setPlannedWorkflow(plan);
      setShowPlanReview(true);
      setShowAutoPlanModal(false);
    } catch (err: any) {
      setError(`Auto-plan failed: ${err.message}`);
      console.error(err);
    } finally {
      setAutoPlanLoading(false);
    }
  };

  // Apply Planned Workflow
  const applyPlannedWorkflow = () => {
    if (!plannedWorkflow) return;

    setWorkflowName(plannedWorkflow.name);
    setWorkflowDescription(plannedWorkflow.description);
    setSelectedAgents(plannedWorkflow.agents);
    setDataSources(plannedWorkflow.data_sources || dataSources);
    setSteps(plannedWorkflow.steps || []);

    setShowPlanReview(false);
    setPlannedWorkflow(null);
    setSuccess(`✅ Plan applied! Review and save the workflow.`);
  };

  // Save Workflow
  const handleSaveWorkflow = async () => {
    if (!workflowName.trim()) {
      setError('Please provide a workflow name');
      return;
    }

    if (selectedAgents.length === 0) {
      setError('Please select at least one agent or use Auto-Plan');
      return;
    }

    try {
      const workflow: WorkflowConfig = {
        id: savedWorkflowId || undefined,
        name: workflowName,
        description: workflowDescription || 'Azure Foundry Workflow',
        user_intent: userIntent,
        agents: selectedAgents,
        data_sources: dataSources,
        steps: steps,
        is_azure_workflow: true
      };

      const saved = await createWorkflow(workflow);
      setSavedWorkflowId(saved.id!);
      setSuccess(`✅ Workflow "${saved.name}" saved successfully!`);
      setError(null);

      // Update URL without full reload
      window.history.replaceState({}, '', `/builder?id=${saved.id}`);
    } catch (err: any) {
      setError(`Save failed: ${err.message}`);
      console.error(err);
    }
  };

  // Execute Workflow
  const handleExecute = async () => {
    if (!savedWorkflowId) {
      setError('Please save the workflow first before executing');
      return;
    }

    if (!userIntent.trim()) {
      setError('Please provide user intent');
      return;
    }

    setExecuting(true);
    setError(null);

    try {
      const job = await executeWorkflow({
        workflow_id: savedWorkflowId,
        input_data: { input: userIntent }
      });

      setCurrentJob(job);
    } catch (err: any) {
      setError(`Execution failed: ${err.message}`);
      console.error(err);
      setExecuting(false);
    }
  };

  // Resume Job (Human-in-the-Loop)
  const handleResume = async (approved: boolean, feedback: string = '') => {
    if (!currentJob) return;

    try {
      const job = await resumeJob({
        job_id: currentJob.id,
        user_input: feedback,
        approved
      });
      setCurrentJob(job);
    } catch (err: any) {
      setError(`Resume failed: ${err.message}`);
      console.error(err);
    }
  };

  // Toggle agent selection
  const toggleAgent = (agent: AgentConfig) => {
    const isSelected = selectedAgents.some(a => a.id === agent.id);
    if (isSelected) {
      setSelectedAgents(selectedAgents.filter(a => a.id !== agent.id));
    } else {
      setSelectedAgents([...selectedAgents, agent]);
    }
  };

  return (
    <main style={{
      padding: '2rem',
      maxWidth: '1200px',
      margin: '0 auto',
      fontFamily: 'system-ui, -apple-system, sans-serif',
      backgroundColor: '#F9FAFB',
      minHeight: '100vh'
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '2rem'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <button
            onClick={() => router.push('/')}
            style={{
              padding: '0.5rem 1rem',
              backgroundColor: 'white',
              border: '1px solid #E5E7EB',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '0.95rem'
            }}
          >
            ← Back
          </button>
          <h1 style={{ margin: 0, fontSize: '2rem', fontWeight: 600, color: '#111827' }}>
            Workflow Builder
          </h1>
        </div>
        <button
          onClick={() => setShowAutoPlanModal(true)}
          disabled={autoPlanLoading}
          style={{
            padding: '0.75rem 1.5rem',
            backgroundColor: '#8B5CF6',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            fontSize: '0.95rem',
            fontWeight: 600
          }}
        >
          {autoPlanLoading ? 'Planning...' : 'Auto-Plan with AI'}
        </button>
      </div>

      {/* Error Display */}
      {error && (
        <div style={{
          padding: '1rem',
          backgroundColor: '#FEE2E2',
          border: '1px solid #EF4444',
          borderRadius: '6px',
          marginBottom: '1.5rem',
          color: '#991B1B'
        }}>
          {error}
        </div>
      )}

      {/* Success Display */}
      {success && (
        <div style={{
          padding: '1rem',
          backgroundColor: '#D1FAE5',
          border: '1px solid #10B981',
          borderRadius: '6px',
          marginBottom: '1.5rem',
          color: '#065F46'
        }}>
          {success}
        </div>
      )}

      {/* Basic Info */}
      <div style={{
        backgroundColor: 'white',
        border: '1px solid #E5E7EB',
        borderRadius: '8px',
        padding: '1.5rem',
        marginBottom: '1.5rem'
      }}>
        <h2 style={{ margin: '0 0 1.5rem 0', fontSize: '1.1rem', fontWeight: 600, color: '#374151' }}>
          Basic Info
        </h2>

        <div style={{ marginBottom: '1rem' }}>
          <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500, fontSize: '0.9rem', color: '#374151' }}>
            Name
          </label>
          <input
            type="text"
            value={workflowName}
            onChange={e => setWorkflowName(e.target.value)}
            style={{
              width: '100%',
              padding: '0.6rem',
              border: '1px solid #D1D5DB',
              borderRadius: '4px',
              fontSize: '0.95rem',
              color: '#111827'
            }}
          />
        </div>

        <div style={{ marginBottom: '1rem' }}>
          <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500, fontSize: '0.9rem', color: '#374151' }}>
            Description
          </label>
          <textarea
            value={workflowDescription}
            onChange={e => setWorkflowDescription(e.target.value)}
            rows={3}
            style={{
              width: '100%',
              padding: '0.6rem',
              border: '1px solid #D1D5DB',
              borderRadius: '4px',
              fontSize: '0.95rem',
              resize: 'vertical',
              color: '#111827'
            }}
          />
        </div>

        <div>
          <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500, fontSize: '0.9rem', color: '#374151' }}>
            User Intent (Prompt)
          </label>
          <textarea
            value={userIntent}
            onChange={e => setUserIntent(e.target.value)}
            placeholder="Describe what you want to do..."
            rows={3}
            style={{
              width: '100%',
              padding: '0.6rem',
              border: '1px solid #D1D5DB',
              borderRadius: '4px',
              fontSize: '0.95rem',
              resize: 'vertical',
              color: '#111827'
            }}
          />
        </div>
      </div>

      {/* Tabs */}
      <div style={{
        backgroundColor: 'white',
        border: '1px solid #E5E7EB',
        borderRadius: '8px',
        padding: '1.5rem',
        marginBottom: '1.5rem'
      }}>
        {/* Tab Headers */}
        <div style={{
          display: 'flex',
          borderBottom: '2px solid #E5E7EB',
          marginBottom: '1.5rem'
        }}>
          {[
            { key: 'agents', label: 'Agents', count: selectedAgents.length },
            { key: 'teams', label: 'Teams', count: teams.length },
            { key: 'data_sources', label: 'Data Sources', count: dataSources.length },
            { key: 'steps', label: 'Steps', count: steps.length }
          ].map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key as TabType)}
              style={{
                padding: '0.75rem 1.5rem',
                border: 'none',
                background: 'none',
                borderBottom: activeTab === tab.key ? '2px solid #3B82F6' : '2px solid transparent',
                marginBottom: '-2px',
                cursor: 'pointer',
                fontSize: '0.95rem',
                fontWeight: activeTab === tab.key ? 600 : 400,
                color: activeTab === tab.key ? '#3B82F6' : '#6B7280'
              }}
            >
              {tab.label} ({tab.count})
            </button>
          ))}
        </div>

        {/* Tab Content */}

        {/* Agents Tab */}
        {activeTab === 'agents' && (
          <div>
            <h3 style={{ margin: '0 0 1rem 0', fontSize: '1rem', fontWeight: 600, color: '#374151' }}>
              Available Azure Agents
            </h3>
            <div style={{ display: 'grid', gap: '0.75rem' }}>
              {availableAgents.map(agent => (
                <div
                  key={agent.id}
                  onClick={() => toggleAgent(agent)}
                  style={{
                    padding: '1rem',
                    border: selectedAgents.some(a => a.id === agent.id)
                      ? '2px solid #3B82F6'
                      : '1px solid #E5E7EB',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    backgroundColor: selectedAgents.some(a => a.id === agent.id)
                      ? '#EFF6FF'
                      : 'white'
                  }}
                >
                  <div style={{ fontWeight: 600, marginBottom: '0.25rem', color: '#111827' }}>
                    {agent.name}
                  </div>
                  <div style={{ fontSize: '0.85rem', color: '#6B7280' }}>{agent.role}</div>
                </div>
              ))}
            </div>
            {selectedAgents.length > 0 && (
              <div style={{ marginTop: '1rem', padding: '1rem', backgroundColor: '#F3F4F6', borderRadius: '6px' }}>
                <strong style={{ color: '#374151' }}>Selected Agents:</strong>{' '}
                <span style={{ color: '#6B7280' }}>{selectedAgents.map(a => a.name).join(', ')}</span>
              </div>
            )}
          </div>
        )}

        {/* Teams Tab */}
        {activeTab === 'teams' && (
          <div>
            <p style={{ color: '#6B7280' }}>Teams feature coming soon...</p>
          </div>
        )}

        {/* Data Sources Tab */}
        {activeTab === 'data_sources' && (
          <div>
            {/* Existing Data Sources */}
            {dataSources.length > 0 && (
              <div style={{ marginBottom: '1.5rem' }}>
                <h3 style={{ margin: '0 0 1rem 0', fontSize: '1rem', fontWeight: 600, color: '#374151' }}>
                  Configured Data Sources
                </h3>
                {dataSources.map((ds, index) => (
                  <div
                    key={index}
                    style={{
                      padding: '1rem',
                      border: '1px solid #E5E7EB',
                      borderRadius: '6px',
                      marginBottom: '0.75rem',
                      backgroundColor: '#F9FAFB'
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
                      <div>
                        <div style={{ fontWeight: 600, marginBottom: '0.25rem', color: '#111827' }}>
                          {ds.name}
                        </div>
                        <div style={{ fontSize: '0.85rem', color: '#6B7280', marginBottom: '0.25rem' }}>
                          Type: {ds.type}
                        </div>
                        {ds.path && (
                          <div style={{ fontSize: '0.85rem', color: '#6B7280' }}>Path: {ds.path}</div>
                        )}
                        {ds.connection_string && (
                          <div style={{ fontSize: '0.85rem', color: '#6B7280' }}>
                            Connection: {ds.connection_string}
                          </div>
                        )}
                        {ds.url && <div style={{ fontSize: '0.85rem', color: '#6B7280' }}>URL: {ds.url}</div>}
                      </div>
                      <button
                        onClick={() => removeDataSource(index)}
                        style={{
                          padding: '0.4rem 0.8rem',
                          backgroundColor: '#EF4444',
                          color: 'white',
                          border: 'none',
                          borderRadius: '4px',
                          cursor: 'pointer',
                          fontSize: '0.85rem'
                        }}
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Add New Data Source Form */}
            <h3 style={{ margin: '0 0 1rem 0', fontSize: '1rem', fontWeight: 600, color: '#374151' }}>
              Add New Data Source
            </h3>

            <div style={{ display: 'grid', gap: '1rem' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                <div>
                  <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500, fontSize: '0.9rem', color: '#374151' }}>
                    Name
                  </label>
                  <input
                    type="text"
                    value={currentDataSource.name}
                    onChange={e => setCurrentDataSource({ ...currentDataSource, name: e.target.value })}
                    placeholder="New Data"
                    style={{
                      width: '100%',
                      padding: '0.6rem',
                      border: '1px solid #D1D5DB',
                      borderRadius: '4px',
                      fontSize: '0.95rem',
                      color: '#111827'
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500, fontSize: '0.9rem', color: '#374151' }}>
                    Type
                  </label>
                  <select
                    value={currentDataSource.type}
                    onChange={e => setCurrentDataSource({ ...currentDataSource, type: e.target.value as 'file' | 'database' | 'mcp_server' })}
                    style={{
                      width: '100%',
                      padding: '0.6rem',
                      border: '1px solid #D1D5DB',
                      borderRadius: '4px',
                      fontSize: '0.95rem',
                      backgroundColor: 'white',
                      color: '#111827'
                    }}
                  >
                    <option value="file">File</option>
                    <option value="database">Database</option>
                    <option value="mcp_server">MCP Server</option>
                  </select>
                </div>
              </div>

              {/* Type-specific fields */}
              {currentDataSource.type === 'file' && (
                <div>
                  <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500, fontSize: '0.9rem', color: '#374151' }}>
                    File Path
                  </label>
                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <input
                      type="text"
                      value={currentDataSource.path}
                      onChange={e => setCurrentDataSource({ ...currentDataSource, path: e.target.value })}
                      placeholder="/path/to/file.pdf"
                      style={{
                        flex: 1,
                        padding: '0.6rem',
                        border: '1px solid #D1D5DB',
                        borderRadius: '4px',
                        fontSize: '0.95rem',
                        color: '#111827'
                      }}
                    />
                    <button
                      onClick={() => setShowFileExplorer(true)}
                      style={{
                        padding: '0.6rem 1rem',
                        backgroundColor: '#F3F4F6',
                        border: '1px solid #D1D5DB',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        fontSize: '0.9rem',
                        color: '#374151'
                      }}
                    >
                      📁 Browse
                    </button>
                  </div>
                </div>
              )}

              {currentDataSource.type === 'database' && (
                <>
                  <div>
                    <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500, fontSize: '0.9rem', color: '#374151' }}>
                      Connection String (DB)
                    </label>
                    <input
                      type="text"
                      value={currentDataSource.connection_string}
                      onChange={e => setCurrentDataSource({ ...currentDataSource, connection_string: e.target.value })}
                      placeholder="postgresql://user:pass@localhost:5432/db"
                      style={{
                        width: '100%',
                        padding: '0.6rem',
                        border: '1px solid #D1D5DB',
                        borderRadius: '4px',
                        fontSize: '0.95rem',
                        color: '#111827'
                      }}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500, fontSize: '0.9rem', color: '#374151' }}>
                      Local Database File (SQLite/DuckDB)
                    </label>
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                      <input
                        type="text"
                        value={currentDataSource.path}
                        onChange={e => setCurrentDataSource({ ...currentDataSource, path: e.target.value })}
                        placeholder="/path/to/local.db"
                        style={{
                          flex: 1,
                          padding: '0.6rem',
                          border: '1px solid #D1D5DB',
                          borderRadius: '4px',
                          fontSize: '0.95rem',
                          color: '#111827'
                        }}
                      />
                      <button
                        onClick={handleBrowseFile}
                        style={{
                          padding: '0.6rem 1rem',
                          backgroundColor: '#F3F4F6',
                          border: '1px solid #D1D5DB',
                          borderRadius: '4px',
                          cursor: 'pointer',
                          fontSize: '0.9rem',
                          color: '#374151'
                        }}
                      >
                        📁 Browse
                      </button>
                    </div>
                  </div>
                </>
              )}

              {currentDataSource.type === 'mcp_server' && (
                <div>
                  <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500, fontSize: '0.9rem', color: '#374151' }}>
                    MCP Server URL
                  </label>
                  <input
                    type="text"
                    value={currentDataSource.url}
                    onChange={e => setCurrentDataSource({ ...currentDataSource, url: e.target.value })}
                    placeholder="http://localhost:3000"
                    style={{
                      width: '100%',
                      padding: '0.6rem',
                      border: '1px solid #D1D5DB',
                      borderRadius: '4px',
                      fontSize: '0.95rem',
                      color: '#111827'
                    }}
                  />
                </div>
              )}

              <button
                onClick={addDataSource}
                style={{
                  padding: '0.75rem 1.5rem',
                  backgroundColor: 'white',
                  border: '1px solid #D1D5DB',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.95rem',
                  fontWeight: 500,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  width: 'fit-content',
                  color: '#374151'
                }}
              >
                <span style={{ fontSize: '1.2rem' }}>+</span> Add Data Source
              </button>
            </div>
          </div>
        )}

        {/* Steps Tab */}
        {activeTab === 'steps' && (
          <div>
            {steps.length === 0 ? (
              <p style={{ color: '#6B7280' }}>
                Steps will be automatically determined by Azure Foundry agents during execution.
              </p>
            ) : (
              <div>
                {steps.map((step, index) => (
                  <div
                    key={index}
                    style={{
                      padding: '1rem',
                      border: '1px solid #E5E7EB',
                      borderRadius: '6px',
                      marginBottom: '0.75rem',
                      backgroundColor: 'white'
                    }}
                  >
                    <div style={{ fontWeight: 600, color: '#111827' }}>
                      Step {index + 1}: {step.name}
                    </div>
                    <div style={{ fontSize: '0.85rem', color: '#6B7280' }}>Type: {step.type}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Action Buttons */}
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.5rem' }}>
        <button
          onClick={handleSaveWorkflow}
          style={{
            flex: 1,
            padding: '1rem 2rem',
            backgroundColor: '#10B981',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            fontSize: '1rem',
            fontWeight: 600
          }}
        >
          💾 Save Workflow
        </button>

        <button
          onClick={handleExecute}
          disabled={executing || !savedWorkflowId}
          style={{
            flex: 1,
            padding: '1rem 2rem',
            backgroundColor: executing || !savedWorkflowId ? '#9CA3AF' : '#3B82F6',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: executing || !savedWorkflowId ? 'not-allowed' : 'pointer',
            fontSize: '1rem',
            fontWeight: 600
          }}
        >
          {executing ? '▶️ Executing...' : '▶️ Execute Workflow'}
        </button>
      </div>

      {/* Execution Status */}
      {currentJob && (
        <div style={{
          backgroundColor: 'white',
          border: '1px solid #E5E7EB',
          borderRadius: '8px',
          padding: '1.5rem'
        }}>
          <h2 style={{ margin: '0 0 1rem 0', fontSize: '1.1rem', fontWeight: 600, color: '#374151' }}>
            Execution Status
          </h2>

          <div style={{
            padding: '1rem',
            backgroundColor:
              currentJob.status === 'completed' ? '#D1FAE5' :
                currentJob.status === 'failed' ? '#FEE2E2' :
                  currentJob.status === 'waiting_for_user' ? '#FEF3C7' :
                    '#DBEAFE',
            borderRadius: '6px',
            marginBottom: '1rem',
            color: '#111827',
            fontWeight: 600
          }}>
            Status: {currentJob.status.toUpperCase()}
          </div>

          {/* Human-in-the-Loop */}
          {currentJob.status === 'waiting_for_user' && (
            <div style={{
              padding: '1rem',
              border: '2px solid #F59E0B',
              borderRadius: '6px',
              backgroundColor: '#FFFBEB',
              marginBottom: '1rem'
            }}>
              <h3 style={{ margin: '0 0 1rem 0', fontSize: '1rem', color: '#92400E' }}>
                ⏸️ Waiting for User Input
              </h3>
              <p style={{ margin: '0 0 1rem 0', color: '#92400E' }}>
                {currentJob.pending_tool_call?.message || 'The workflow is paused and waiting for your approval.'}
              </p>
              <div style={{ display: 'flex', gap: '1rem' }}>
                <button
                  onClick={() => handleResume(true)}
                  style={{
                    padding: '0.75rem 1.5rem',
                    backgroundColor: '#10B981',
                    color: 'white',
                    border: 'none',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontWeight: 600
                  }}
                >
                  ✅ Approve
                </button>
                <button
                  onClick={() => handleResume(false, 'Rejected by user')}
                  style={{
                    padding: '0.75rem 1.5rem',
                    backgroundColor: '#EF4444',
                    color: 'white',
                    border: 'none',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontWeight: 600
                  }}
                >
                  ❌ Reject
                </button>
              </div>
            </div>
          )}

          {/* Logs */}
          <div>
            <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '1rem', fontWeight: 600, color: '#374151' }}>
              Execution Logs
            </h3>
            <div style={{
              maxHeight: '300px',
              overflowY: 'auto',
              backgroundColor: '#1F2937',
              color: '#F9FAFB',
              padding: '1rem',
              borderRadius: '6px',
              fontSize: '0.85rem',
              fontFamily: 'monospace'
            }}>
              {currentJob.logs.length > 0 ? (
                currentJob.logs.map((log, i) => (
                  <div key={i} style={{ marginBottom: '0.25rem' }}>{log}</div>
                ))
              ) : (
                <div style={{ color: '#9CA3AF' }}>No logs yet...</div>
              )}
            </div>
          </div>

          {/* Results */}
          {currentJob.status === 'completed' && currentJob.context && (
            <div style={{ marginTop: '1rem' }}>
              <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '1rem', fontWeight: 600, color: '#374151' }}>
                Results
              </h3>
              <div style={{
                padding: '1rem',
                backgroundColor: '#F9FAFB',
                border: '1px solid #E5E7EB',
                borderRadius: '6px',
                fontSize: '0.9rem'
              }}>
                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordWrap: 'break-word', color: '#111827' }}>
                  {JSON.stringify(currentJob.context, null, 2)}
                </pre>
              </div>
            </div>
          )}

          {/* Error */}
          {currentJob.error && (
            <div style={{
              marginTop: '1rem',
              padding: '1rem',
              backgroundColor: '#FEE2E2',
              border: '1px solid #EF4444',
              borderRadius: '6px',
              color: '#991B1B'
            }}>
              <strong>Error:</strong> {currentJob.error}
            </div>
          )}
        </div>
      )}

      {/* Auto-Plan Modal */}
      {showAutoPlanModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.5)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000
        }}>
          <div style={{
            backgroundColor: 'white',
            borderRadius: '8px',
            padding: '2rem',
            maxWidth: '600px',
            width: '90%',
            maxHeight: '80vh',
            overflowY: 'auto'
          }}>
            <h2 style={{ margin: '0 0 1rem 0', fontSize: '1.3rem', fontWeight: 600, color: '#111827' }}>
              🤖 Auto-Plan with AI
            </h2>

            <p style={{ marginBottom: '1.5rem', color: '#6B7280' }}>
              AI will analyze your User Intent and Data Sources to automatically select appropriate Azure agents and plan the workflow execution.
            </p>

            <div style={{
              padding: '1rem',
              backgroundColor: '#EFF6FF',
              border: '1px solid #3B82F6',
              borderRadius: '6px',
              marginBottom: '1.5rem'
            }}>
              <div style={{ fontWeight: 600, marginBottom: '0.5rem', color: '#1E40AF' }}>
                Current Configuration:
              </div>
              <div style={{ fontSize: '0.9rem', color: '#1F2937' }}>
                <div>• User Intent: {userIntent ? '✅ Provided' : '❌ Missing'}</div>
                <div>• Data Sources: {dataSources.length} configured</div>
              </div>
            </div>

            {!userIntent && (
              <div style={{
                padding: '1rem',
                backgroundColor: '#FEF3C7',
                border: '1px solid #F59E0B',
                borderRadius: '6px',
                marginBottom: '1.5rem',
                color: '#92400E'
              }}>
                ⚠️ Please provide User Intent in the Basic Info section before using Auto-Plan.
              </div>
            )}

            <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
              <button
                onClick={() => setShowAutoPlanModal(false)}
                style={{
                  padding: '0.75rem 1.5rem',
                  backgroundColor: '#F3F4F6',
                  border: '1px solid #D1D5DB',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.95rem',
                  fontWeight: 500,
                  color: '#374151'
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleAutoPlan}
                disabled={!userIntent || autoPlanLoading}
                style={{
                  padding: '0.75rem 1.5rem',
                  backgroundColor: !userIntent || autoPlanLoading ? '#9CA3AF' : '#8B5CF6',
                  color: 'white',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: !userIntent || autoPlanLoading ? 'not-allowed' : 'pointer',
                  fontSize: '0.95rem',
                  fontWeight: 600
                }}
              >
                {autoPlanLoading ? '🤖 Planning...' : '✨ Generate Plan'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Plan Review Modal */}
      {showPlanReview && plannedWorkflow && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.6)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000
        }}>
          <div style={{
            backgroundColor: 'white',
            borderRadius: '8px',
            padding: '2rem',
            maxWidth: '900px', // Wider for editing
            width: '95%',
            maxHeight: '90vh',
            overflowY: 'auto'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <h2 style={{ margin: 0, fontSize: '1.4rem', fontWeight: 600, color: '#111827' }}>
                ✨ Review & Edit Plan
              </h2>
              <button
                onClick={() => {
                  setShowPlanReview(false);
                  setPlannedWorkflow(null);
                }}
                style={{ background: 'none', border: 'none', fontSize: '1.5rem', cursor: 'pointer', color: '#6B7280' }}
              >
                ✕
              </button>
            </div>

            <p style={{ marginBottom: '1.5rem', color: '#6B7280' }}>
              Review the AI-generated plan. You can <strong>edit the instructions</strong> for each step to guide the agents precisely.
            </p>

            {/* Plan Details */}
            <div style={{
              padding: '1.5rem',
              backgroundColor: '#F9FAFB',
              border: '1px solid #E5E7EB',
              borderRadius: '6px',
              marginBottom: '1.5rem'
            }}>
              <div style={{ marginBottom: '1rem' }}>
                <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#6B7280', marginBottom: '0.25rem' }}>
                  WORKFLOW NAME
                </div>
                <input
                  type="text"
                  value={plannedWorkflow.name}
                  onChange={(e) => setPlannedWorkflow({ ...plannedWorkflow, name: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '0.5rem',
                    border: '1px solid #D1D5DB',
                    borderRadius: '4px',
                    fontSize: '1rem',
                    fontWeight: 600
                  }}
                />
              </div>

              <div style={{ marginBottom: '1rem' }}>
                <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#6B7280', marginBottom: '0.25rem' }}>
                  DESCRIPTION
                </div>
                <textarea
                  value={plannedWorkflow.description}
                  onChange={(e) => setPlannedWorkflow({ ...plannedWorkflow, description: e.target.value })}
                  rows={2}
                  style={{
                    width: '100%',
                    padding: '0.5rem',
                    border: '1px solid #D1D5DB',
                    borderRadius: '4px',
                    fontSize: '0.95rem'
                  }}
                />
              </div>

              <div style={{ marginBottom: '1rem' }}>
                <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#6B7280', marginBottom: '0.25rem' }}>
                  SELECTED AGENTS ({plannedWorkflow.agents.length})
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                  {plannedWorkflow.agents.map(agent => (
                    <div
                      key={agent.id}
                      style={{
                        padding: '0.4rem 0.8rem',
                        backgroundColor: '#EFF6FF',
                        border: '1px solid #3B82F6',
                        borderRadius: '4px',
                        fontSize: '0.85rem',
                        color: '#1E40AF',
                        fontWeight: 500
                      }}
                    >
                      {agent.name}
                    </div>
                  ))}
                </div>
              </div>

              {/* Editable Steps */}
              {plannedWorkflow.steps && plannedWorkflow.steps.length > 0 && (
                <div>
                  <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#6B7280', marginBottom: '0.5rem' }}>
                    PLANNED STEPS ({plannedWorkflow.steps.length})
                  </div>
                  {plannedWorkflow.steps.map((step, i) => (
                    <div
                      key={i}
                      style={{
                        padding: '1rem',
                        backgroundColor: 'white',
                        border: '1px solid #E5E7EB',
                        borderRadius: '6px',
                        marginBottom: '1rem',
                        position: 'relative'
                      }}
                    >
                      <div style={{ position: 'absolute', top: '1rem', right: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <label style={{ fontSize: '0.85rem', color: '#4B5563', display: 'flex', alignItems: 'center', gap: '0.3rem', cursor: 'pointer' }}>
                          <input
                            type="checkbox"
                            checked={step.requires_approval}
                            onChange={(e) => {
                              const newSteps = [...(plannedWorkflow.steps || [])];
                              newSteps[i] = { ...newSteps[i], requires_approval: e.target.checked };
                              setPlannedWorkflow({ ...plannedWorkflow, steps: newSteps });
                            }}
                          />
                          Require Approval (HIL)
                        </label>
                      </div>

                      <div style={{ marginBottom: '0.5rem' }}>
                        <label style={{ fontSize: '0.8rem', fontWeight: 600, color: '#6B7280' }}>STEP {i + 1} NAME</label>
                        <input
                          type="text"
                          value={step.name}
                          onChange={(e) => {
                            const newSteps = [...(plannedWorkflow.steps || [])];
                            newSteps[i] = { ...newSteps[i], name: e.target.value };
                            setPlannedWorkflow({ ...plannedWorkflow, steps: newSteps });
                          }}
                          style={{
                            display: 'block',
                            width: '100%',
                            padding: '0.5rem',
                            border: '1px solid #D1D5DB',
                            borderRadius: '4px',
                            fontSize: '0.95rem',
                            fontWeight: 600,
                            marginTop: '0.2rem'
                          }}
                        />
                      </div>

                      <div style={{ marginBottom: '0.5rem' }}>
                        <label style={{ fontSize: '0.8rem', fontWeight: 600, color: '#6B7280' }}>AGENT</label>
                        <div style={{ fontSize: '0.9rem', color: '#111827', padding: '0.2rem 0' }}>
                          {step.agent_id}
                        </div>
                      </div>

                      <div style={{ marginBottom: '0.5rem' }}>
                        <label style={{ fontSize: '0.8rem', fontWeight: 600, color: '#6B7280' }}>INSTRUCTIONS (PROMPT)</label>
                        <textarea
                          value={step.input_template}
                          onChange={(e) => {
                            const newSteps = [...(plannedWorkflow.steps || [])];
                            newSteps[i] = { ...newSteps[i], input_template: e.target.value };
                            setPlannedWorkflow({ ...plannedWorkflow, steps: newSteps });
                          }}
                          rows={4}
                          style={{
                            display: 'block',
                            width: '100%',
                            padding: '0.5rem',
                            border: '1px solid #D1D5DB',
                            borderRadius: '4px',
                            fontSize: '0.9rem',
                            marginTop: '0.2rem',
                            fontFamily: 'monospace'
                          }}
                        />
                        <div style={{ fontSize: '0.75rem', color: '#9CA3AF', marginTop: '0.2rem' }}>
                          This is the exact prompt that will be sent to the agent. Customize it for better results.
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Action Buttons */}
            <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
              <button
                onClick={() => {
                  setShowPlanReview(false);
                  setPlannedWorkflow(null);
                }}
                style={{
                  padding: '0.75rem 1.5rem',
                  backgroundColor: '#F3F4F6',
                  border: '1px solid #D1D5DB',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.95rem',
                  fontWeight: 500,
                  color: '#374151'
                }}
              >
                Cancel
              </button>
              <button
                onClick={applyPlannedWorkflow}
                style={{
                  padding: '0.75rem 1.5rem',
                  backgroundColor: '#10B981',
                  color: 'white',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.95rem',
                  fontWeight: 600
                }}
              >
                ✅ Approve & Apply Plan
              </button>
            </div>
          </div>
        </div>
      )}
      {/* File Explorer Dialog */}
      <FileExplorer
        open={showFileExplorer}
        onOpenChange={setShowFileExplorer}
        accept={currentDataSource.type === 'database' ? ".db,.sqlite,.duckdb" : undefined}
        onSelect={(path) => {
          setCurrentDataSource({
            ...currentDataSource,
            path: path,
            connection_string: path
          });
        }}
      />
    </main>
  );
}
