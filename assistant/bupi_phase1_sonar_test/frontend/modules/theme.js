/**
 * Shared Design-Token Reader for HTML5 Canvas & Three.js Viewports.
 * Sources colors exclusively from CSS variables defined in tokens.css.
 */

export function getTacticalPalette() {
  const s = getComputedStyle(document.documentElement);
  const v = (name, fb) => (s.getPropertyValue(name).trim() || fb);
  return {
    bgBase: v('--color-bg-base', '#07090c'),
    mapUnknown: v('--color-map-unknown', '#0b1017'),
    mapFree: v('--color-map-free', '#0d3b46'),
    primary: v('--color-primary', '#00e5ff'),
    red: v('--color-accent-red', '#ff2a54'),
    amber: v('--color-accent-amber', '#ffb703'),
    orange: v('--color-accent-orange', '#ff6d00'),
    green: v('--color-accent-green', '#00e676'),
    magenta: v('--color-accent-magenta', '#e040fb'),
    borderSubtle: v('--color-border-subtle', '#21262d'),
    borderMedium: v('--color-border-medium', '#30363d'),
    textDim: v('--color-text-dim', '#545d68'),
    textMuted: v('--color-text-muted', '#8b949e'),
    textBright: v('--color-text-bright', '#f0f6fc')
  };
}

