// The stylesheet sent to the summary iframe: the app's fonts (inlined, since the iframe is another
// origin and cannot load the app's font files), the tokens, and the summary overrides.
import serif400 from '@fontsource/source-serif-4/files/source-serif-4-latin-400-normal.woff2?inline';
import serif600 from '@fontsource/source-serif-4/files/source-serif-4-latin-600-normal.woff2?inline';
import mono400 from '@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-400-normal.woff2?inline';
import mono500 from '@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-500-normal.woff2?inline';
import tokens from './tokens.css?raw';
import frame from './summary-frame.css?raw';

const face = (family, weight, src) =>
  `@font-face{font-family:'${family}';font-weight:${weight};font-style:normal;font-display:block;src:url(${src}) format('woff2');}`;

export const frameCss = [
  face('Source Serif 4', 400, serif400),
  face('Source Serif 4', 600, serif600),
  face('IBM Plex Mono', 400, mono400),
  face('IBM Plex Mono', 500, mono500),
  tokens,
  frame,
].join('\n');
