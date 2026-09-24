// Runs inside the app's summary iframe only (served with ?embed=1; the file on disk stays script-free).
// Turns "Pages 7, 8" tags into one chip per page that asks the parent to open the PDF there, and
// swaps the standalone styling for the app stylesheet the parent sends.
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

  for (const tag of document.querySelectorAll('.page-tag')) {
    const pages = (tag.textContent.match(/\d+/g) || []).map(Number);
    tag.replaceChildren(...pages.map((page) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'page-chip';
      chip.textContent = `p. ${page}`;
      chip.title = `Open page ${page} of the source PDF`;
      chip.addEventListener('click', () => {
        for (const c of document.querySelectorAll('.page-chip[aria-pressed]')) c.removeAttribute('aria-pressed');
        chip.setAttribute('aria-pressed', 'true');
        window.parent.postMessage({ type: 'klaro:page', page }, '*');
      });
      return chip;
    }));
  }
  window.parent.postMessage({ type: 'klaro:ready' }, '*');
})();
