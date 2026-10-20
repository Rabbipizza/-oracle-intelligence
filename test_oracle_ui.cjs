/* Execute the actual inline UI with a minimal DOM; no network or dependencies. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];
const input = JSON.parse(fs.readFileSync('data/cockpit.json', 'utf8'));
function render(now, patch = {}) {
  const nodes = new Map();
  for (const [, id] of html.matchAll(/\bid="([^"]+)"/g)) {
    nodes.set(id, {innerHTML: '', textContent: '', appendChild(child) { this.textContent += child.textContent; }});
  }
  class Clock extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return Date.parse(now); }
  }
  const context = {Date: Clock, Intl, console,
    document: {getElementById(id) {assert(nodes.has(id), 'missing DOM element '+id); return nodes.get(id);}, createElement() {return {textContent: ''};}},
    localStorage: {getItem() {return null;}},
    fetch() {return new Promise(() => {});},
    INPUT: {...structuredClone(input), ...patch}};
  context.window = context;
  vm.createContext(context);
  vm.runInContext(script, context);
  vm.runInContext('renderData(INPUT)', context);
  return nodes;
}
const asOf = input.data_as_of;
let nodes = render(asOf+'T12:00:00Z');
assert.match(nodes.get('portfolioRows').innerHTML, /AAON/);
assert.doesNotMatch(nodes.get('portfolioRows').innerHTML, /GEV|QQQ/);
assert.match(nodes.get('portfolioCompare').innerHTML, /960/);
assert.match(nodes.get('portfolioCompare').innerHTML, /TARGET/);
assert.match(nodes.get('simulatedRows').innerHTML, /GEV/);
assert.match(nodes.get('dataWarnings').textContent, /TMRC.*DATA_UNAVAILABLE/);
assert.match(nodes.get('actions').innerHTML, /INVESTISSABLE/);
assert.match(nodes.get('actions').innerHTML, /Invalidations/);
nodes = render(new Date(Date.parse(asOf+'T12:00:00Z')+8*86400000).toISOString());
assert.match(nodes.get('actions').innerHTML, /aucune entrée admissible/);
assert.doesNotMatch(nodes.get('actions').innerHTML, /INVESTISSABLE/);
for (const data_as_of of [null, 'bad date', '2099-01-01']) {
  nodes = render(asOf+'T12:00:00Z', {data_as_of});
  assert.match(nodes.get('actions').innerHTML, /aucune entrée admissible/);
}
console.log('ORACLE UI regression checks: PASS (separate ledgers, warnings, invalidations and stale-data exclusion)');
