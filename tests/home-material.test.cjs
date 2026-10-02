const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const css = fs.readFileSync('webroot/console.css', 'utf8');
const material = css.slice(css.indexOf('/* Home material pass:'));

test('material refinements stay scoped to the homepage', () => {
  assert.ok(material.length > 1000);
  // Each style rule is overview-scoped; media rules only group those selectors.
  const rules = [...material.matchAll(/([^{}]+)\{/g)].map(match => match[1].replace(/\/\*[\s\S]*?\*\//g, '').trim());
  for (const rule of rules) {
    if (rule.startsWith('@media')) continue;
    for (const selector of rule.split(',')) assert.ok(selector.trim().startsWith('body[data-view="overview"]'), selector);
  }
});

test('floating dock has translucent material, blur fallback and safe-area clearance', () => {
  assert.match(material, /-webkit-backdrop-filter: blur\(28px\) saturate\(125%\)/);
  assert.match(material, /bottom:calc\(18px \+ env\(safe-area-inset-bottom\)\)/);
  assert.match(material, /main \{ padding: 45px 0 120px; \}/);
  assert.match(material, /background:linear-gradient\(130deg,#ffffff90/);
});

test('discarded overlapping study cannot rotate the power icon or stack device facts', () => {
  assert.doesNotMatch(css, /Homepage material study/);
  assert.doesNotMatch(material, /rotate\(/);
});
