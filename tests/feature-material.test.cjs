const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const css=fs.readFileSync('webroot/features.css','utf8');
test('feature visual rules never restyle the approved homepage',()=>{
 for(const match of css.matchAll(/([^{}]+)\{/g)){
  const rule=match[1].replace(/\/\*[\s\S]*?\*\//g,'').trim();
  if(rule.startsWith('@media'))continue;
  for(const selector of rule.split(','))assert.ok(selector.trim().startsWith('body:not([data-view="overview"])'),selector);
 }
});
test('feature stylesheet is bundled and shared dock retains safe-area and blur',()=>{
 assert.match(fs.readFileSync('webroot/index.html','utf8'),/href="features.css"/);
 assert.match(fs.readFileSync('tools/ui-smoke.cjs','utf8'),/'\/features.css':\['features.css','text\/css'\]/);
 assert.match(css,/env\(safe-area-inset-bottom\)/);
 assert.match(css,/-webkit-backdrop-filter:blur\(28px\) saturate\(125%\)/);
});
