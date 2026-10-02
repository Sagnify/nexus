import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { AuthProvider } from './context/AuthContext';
import { SkillsProvider } from './context/SkillsContext';
import { ConnectorsProvider } from './context/ConnectorsContext';
import './styles/index.css';

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <AuthProvider>
      <SkillsProvider>
        <ConnectorsProvider>
          <App />
        </ConnectorsProvider>
      </SkillsProvider>
    </AuthProvider>
  </React.StrictMode>
);
