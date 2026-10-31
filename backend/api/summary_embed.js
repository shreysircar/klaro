// Runs inside the app's summary iframe only (served with ?embed=1; the file on disk stays script-free).
// Turns "Pages 7, 8" tags into one chip per page and makes each bullet clickable; both ask the parent to open
// the PDF there (klaro:cite, with the bullet's evidence id). Also swaps the standalone styling for the app stylesheet the parent sends.
(() => {
  const root = document.documentElement;
  root.style.visibility = 'hidden'; // no flash of the standalone blue styling
  const reveal = () => { root.style.visibility = ''; };
  setTimeout(reveal, 1500); // if the app never answers, the standalone look beats a blank frame

  window.addEventListener('message', (e) => {
    if (e.source !== window.parent || e.data?.type !== 'klaro:style' || typeof e.data.css !== 'string') return;
    const style = document.createElement('style');
    style.textContent = e.data.css;
    document.head.appendChild(style);
    reveal();
  });

  // Section order is the order render_summary.py writes them in (locales/*.json). Ids match evidence.json.
  const KEYS = ['overview', 'issuing_organization', 'scope', 'key_requirements', 'eligibility', 'important_dates',
    'commercial_requirements', 'project_duration', 'important_conditions'];
  const cite = (el, id, page, chip) => {
    for (const c of document.querySelectorAll('.page-chip[aria-pressed]')) c.removeAttribute('aria-pressed');
    for (const c of document.querySelectorAll('.cited')) c.classList.remove('cited');
    el.classList.add('cited');
    window.parent.postMessage({ type: 'klaro:cite', id, page, chip }, '*');
  };

  document.querySelectorAll('.summary-section').forEach((section, s) => {
    const key = KEYS[s];
    const bullets = key === 'overview' ? [...section.querySelectorAll('p:not(.empty-notice)')].slice(0, 1) : [...section.querySelectorAll('li')];
    bullets.forEach((bullet, i) => {
      const id = key === 'issuing_organization' ? null : `${key}-${i}`;
      const pages = [...bullet.querySelectorAll('.page-tag')].flatMap((t) => (t.textContent.match(/\d+/g) || []).map(Number));
      for (const tag of bullet.querySelectorAll('.page-tag')) {
        const nums = (tag.textContent.match(/\d+/g) || []).map(Number);
        tag.replaceChildren(...nums.map((page) => {
          const chip = document.createElement('button');
          chip.type = 'button';
          chip.className = 'page-chip';
          chip.textContent = `p. ${page}`;
          chip.title = `Open page ${page} of the source PDF`;
          chip.addEventListener('click', (e) => {
            e.stopPropagation();
            cite(bullet, id, page, true);
            chip.setAttribute('aria-pressed', 'true');
          });
          return chip;
        }));
      }
      if (id && pages.length) {
        bullet.classList.add('citable');
        bullet.addEventListener('click', () => cite(bullet, id, pages[0], false));
      }
    });
  });
  window.parent.postMessage({ type: 'klaro:ready' }, '*');
})();
