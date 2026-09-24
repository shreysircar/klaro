import { Mark } from './icons.jsx';

export default function TopBar({ children }) {
  return (
    <header className="topbar">
      <div className="brand">
        <Mark />
        <span className="brand-name">Klaro</span>
      </div>
      <div className="topbar-right">{children}</div>
    </header>
  );
}
