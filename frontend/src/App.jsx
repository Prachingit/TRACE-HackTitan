import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Overview from './pages/Overview';
import {
  ProjectsPage,
  ActivityPage,
  HandoverCenterPage,
  HandoverReportsPage,
  ExitInterviewPage,
  KnowledgeBasePage,
  ContradictionRadarPage,
  EvidenceLedgerPage,
  OwnershipPage,
  GapsPage,
  TeamPage,
  IntegrationsPage,
  SettingsPage,
} from './pages/PlaceholderPages';

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Overview />} />
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="activity" element={<ActivityPage />} />
          <Route path="handover" element={<HandoverCenterPage />} />
          <Route path="handover-reports" element={<HandoverReportsPage />} />
          <Route path="exit-interview" element={<ExitInterviewPage />} />
          <Route path="knowledge-base" element={<KnowledgeBasePage />} />
          <Route path="contradictions" element={<ContradictionRadarPage />} />
          <Route path="evidence" element={<EvidenceLedgerPage />} />
          <Route path="ownership" element={<OwnershipPage />} />
          <Route path="gaps" element={<GapsPage />} />
          <Route path="team" element={<TeamPage />} />
          <Route path="integrations" element={<IntegrationsPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
