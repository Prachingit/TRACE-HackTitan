import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from './hooks/useAuth';
import { Layout, ProtectedRoute } from './components/ui';
import { ForgotPassword, Login, Signup } from './pages/Auth';
import { InviteAccept, Onboarding } from './pages/Workspace';
import { CreateProject, ProjectList, ProjectSources, SourceDetail } from './pages/Projects';
import { ActivityPage, KnowledgeBasePage, ReconstructPage } from './pages/Reconstruction';
import { EvidenceLedgerPage } from './pages/Ledger';
import { ContradictionRadarPage } from './pages/Contradictions';
import { ExitInterviewPage } from './pages/Interview';
import { ReviewWorkbenchPage } from './pages/Review';
import { IntegrationsPage, TeamPage } from './pages/Team';
import { Overview } from './pages/Overview';
import { HandoverCenterPage, HandoverReportsPage } from './pages/Handovers';
import { IncomingPortalPage } from './pages/IncomingPortal';
import { ErrorBoundary, NotFoundPage } from './components/ErrorBoundary';

export function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/onboarding" element={<Onboarding />} />
            <Route path="/invite/:token" element={<InviteAccept />} />
            <Route element={<Layout />}>
              <Route index element={<Overview />} />
              <Route path="portal" element={<IncomingPortalPage />} />
              <Route path="handovers" element={<HandoverCenterPage />} />
              <Route path="handover-reports" element={<HandoverReportsPage />} />
              <Route path="projects" element={<ProjectList />} />
              <Route path="projects/new" element={<CreateProject />} />
              <Route path="projects/:id" element={<ProjectSources />} />
              <Route path="projects/:id/sources/:sid" element={<SourceDetail />} />
              <Route path="projects/:id/reconstruct" element={<ReconstructPage />} />
              <Route path="projects/:id/activity" element={<ActivityPage />} />
              <Route path="projects/:id/knowledge" element={<KnowledgeBasePage />} />
              <Route path="projects/:id/ledger" element={<EvidenceLedgerPage />} />
              <Route path="projects/:id/contradictions" element={<ContradictionRadarPage />} />
              <Route path="projects/:id/interview" element={<ExitInterviewPage />} />
              <Route path="projects/:id/review" element={<ReviewWorkbenchPage />} />
              <Route path="projects/:id/handovers" element={<HandoverCenterPage />} />
              <Route path="activity" element={<ActivityPage />} />
              <Route path="knowledge-base" element={<KnowledgeBasePage />} />
              <Route path="evidence" element={<EvidenceLedgerPage />} />
              <Route path="contradictions" element={<ContradictionRadarPage />} />
              <Route path="interview" element={<ExitInterviewPage />} />
              <Route path="review" element={<ReviewWorkbenchPage />} />
              <Route path="team" element={<TeamPage />} />
              <Route path="integrations" element={<IntegrationsPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
    </ErrorBoundary>
  );
}

export default App;
