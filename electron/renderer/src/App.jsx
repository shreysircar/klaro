import { useState } from 'react';
import Setup from './Setup.jsx';
import Home from './Home.jsx';
import Progress from './Progress.jsx';
import Results from './Results.jsx';

export default function App() {
  const [view, setView] = useState({ screen: 'setup' });
  const home = () => setView({ screen: 'home' });

  switch (view.screen) {
    case 'setup':
      return <Setup onReady={home} />;
    case 'progress':
      return <Progress runId={view.runId} onDone={() => setView({ screen: 'results', runId: view.runId })} onBack={home} />;
    case 'results':
      return <Results runId={view.runId} onBack={home} />;
    default:
      return (
        <Home
          onOpen={(run) => setView({ screen: run.status === 'done' ? 'results' : 'progress', runId: run.run_id })}
        />
      );
  }
}
