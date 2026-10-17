import React from 'react';
import ReactDOM from 'react-dom/client';
// Fonts are bundled, not fetched from Google: same-origin, cached, and the
// page paints once in the right font.
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/jetbrains-mono/400.css';
import '@fontsource/jetbrains-mono/500.css';
import '@fontsource/fraunces/400.css';
import '@fontsource/fraunces/500.css';
import { App } from './App';
import { ErrorBoundary } from './core/ErrorBoundary';
import './styles/app.css';
import './styles/steps.css';
import './styles/help.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
