import { createRoot } from 'react-dom/client';
import '@fontsource/source-serif-4/400.css';
import '@fontsource/source-serif-4/600.css';
import '@fontsource/ibm-plex-sans/400.css';
import '@fontsource/ibm-plex-sans/500.css';
import '@fontsource/ibm-plex-sans/600.css';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import './tokens.css';
import './styles.css';
import App from './App.jsx';

// A file dropped outside the drop zone must not replace the app.
for (const type of ['dragover', 'drop']) window.addEventListener(type, (e) => e.preventDefault());

createRoot(document.getElementById('root')).render(<App />);
