import React from 'react';
import ReactDOM from 'react-dom/client';
// The front page shares Alf's Atlas's look: Nunito, sage, cream cards.
import '@fontsource/nunito/400.css';
import '@fontsource/nunito/600.css';
import '@fontsource/nunito/700.css';
import '@fontsource/nunito/800.css';
import '../sections/familymap/phone/fm.css';
import './home.css';
import { HomeApp } from './HomeApp';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <HomeApp />
  </React.StrictMode>,
);
