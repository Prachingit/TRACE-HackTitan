import React from 'react';
import EmptyState from '../components/EmptyState';

export function ProjectsPage() {
  return (
    <EmptyState
      title="Projects & Workspaces Ledger"
      phase="Phase 2"
      description="Multi-project navigation and workspace management. Phase 1 provides the underlying Project and Workspace relational schema."
    />
  );
}

export function ActivityPage() {
  return (
    <EmptyState
      title="Project Activity Streams"
      phase="Phase 2 Ingestion"
      description="Real-time ingestion view of commit streams, PR events, and issue card updates parsed into atomic activity chunks."
    />
  );
}

export function HandoverCenterPage() {
  return (
    <EmptyState
      title="Handover Center — Hero Feature"
      phase="Phase 5 & 6"
      description="The centerpiece of TRACE: Synthesizes evidence-backed claims, flags contradictions, and coordinates review events between departing and incoming engineers into an approved handover dossier."
    />
  );
}

export function HandoverReportsPage() {
  return (
    <EmptyState
      title="Handover Reports & Export"
      phase="Phase 6"
      description="PDF export, audit trails, and executive summary generation for stakeholders and compliance officers."
    />
  );
}

export function ExitInterviewPage() {
  return (
    <EmptyState
      title="Exit Interview Agent"
      phase="Phase 6"
      description="Autonomous inquiry engine that detects missing rationale and poses targeted questions to outgoing team members."
    />
  );
}

export function KnowledgeBasePage() {
  return (
    <EmptyState
      title="Evidence-Backed Knowledge Base"
      phase="Phase 3 & 4"
      description="Structured claims graph categorized by module, verification status, and cited source excerpts."
    />
  );
}

export function ContradictionRadarPage() {
  return (
    <EmptyState
      title="Contradiction Radar"
      phase="Phase 4"
      description="Rule-based and semantic engine that pinpoints conflicting ownership, documentation gaps, and stale tasks."
    />
  );
}

export function EvidenceLedgerPage() {
  return (
    <EmptyState
      title="Evidence Ledger"
      phase="Phase 3"
      description="Tamper-evident audit ledger linking every extracted claim to verbatim source quotes, commit SHAs, and locators."
    />
  );
}

export function OwnershipPage() {
  return (
    <EmptyState
      title="Dependencies & Ownership Matrix"
      phase="Phase 4"
      description="Visualizes orphaned tasks, unassigned modules, and cross-functional dependency bottlenecks."
    />
  );
}

export function GapsPage() {
  return (
    <EmptyState
      title="Knowledge Gaps & Risk Analysis"
      phase="Phase 4"
      description="Flags undocumented architectural decisions, missing rationale, and unfulfilled commitments."
    />
  );
}

export function TeamPage() {
  return (
    <EmptyState
      title="Team Members & Role Clearances"
      phase="Phase 2"
      description="Detailed membership matrix, role assignments (Admin, Team Member, Incoming, Departing), and clearance settings."
    />
  );
}

export function IntegrationsPage() {
  return (
    <EmptyState
      title="Stream Integrations"
      phase="Phase 2"
      description="Connect GitHub repositories, Slack/Discord exports, Jira/Linear task boards, and Google Docs."
    />
  );
}

export function SettingsPage() {
  return (
    <EmptyState
      title="Workspace Settings"
      phase="Phase 2"
      description="Configure workspace tokens, LLM API keys, database retention rules, and clearance policies."
    />
  );
}
