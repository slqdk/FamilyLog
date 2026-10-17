import React from 'react';
import ReactDOM from 'react-dom/client';
// Bundled like the app's fonts: same-origin, cached, no Google round trip.
// Nunito, a rounded sans, for Alf's Atlas (2.45.0) - word mark and text.
import '@fontsource/nunito/400.css';
import '@fontsource/nunito/600.css';
import '@fontsource/nunito/700.css';
import '@fontsource/nunito/800.css';
import { FamilyMapApp } from './FamilyMapApp';
import './fm.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <FamilyMapApp />
  </React.StrictMode>,
);
