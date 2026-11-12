import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from './hooks/useAuth';
import { Layout, ProtectedRoute } from './components/ui';
import { ForgotPassword, Login, Signup } from './pages/Auth';
import { InviteAccept, Onboarding } from './pages/Workspace';
import { CreateProject, ProjectList, ProjectSources, SourceDetail } from './pages/Projects';
import { ActivityPage, KnowledgeBasePage, ReconstructPage } from './pages/Reconstruction';
import { IntegrationsPage, TeamPage } from './pages/Team';
import { Overview } from './pages/Overview';

export function App() {
  return (
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
              <Route path="projects" element={<ProjectList />} />
              <Route path="projects/new" element={<CreateProject />} />
              <Route path="projects/:id" element={<ProjectSources />} />
              <Route path="projects/:id/sources/:sid" element={<SourceDetail />} />
              <Route path="projects/:id/reconstruct" element={<ReconstructPage />} />
              <Route path="projects/:id/activity" element={<ActivityPage />} />
              <Route path="projects/:id/knowledge" element={<KnowledgeBasePage />} />
              <Route path="activity" element={<ActivityPage />} />
              <Route path="knowledge-base" element={<KnowledgeBasePage />} />
              <Route path="team" element={<TeamPage />} />
              <Route path="integrations" element={<IntegrationsPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
