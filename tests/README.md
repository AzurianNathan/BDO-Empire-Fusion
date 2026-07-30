# Router validation

`router_test.mjs` checks the node router (`patches/noderouter.js`, a validating
adapter around a vendored WASM build of Thell/bdo-noderouter, see
`patches/pkg-real/`) against the real game map: every terminal pair must be
connected using only activated nodes, the reported CP must equal the sum over
the returned set, and sharing must beat naive per-pair routing.

Run it after `python build.py` (which fetches the map data):

```
cd tests
cp ../patches/pkg-real/noderouter.js noderouter_real.js
cp ../patches/pkg-real/noderouter_bg.wasm .
cp ../patches/noderouter.js .
cp ../server/static/data/nodes_links.json ../server/static/data/exploration.json ../server/static/data/plantzone.json .
node router_test.mjs
```

Expected: every row reports `connected-OK` and ends with `ALL CHECKS PASS`.
