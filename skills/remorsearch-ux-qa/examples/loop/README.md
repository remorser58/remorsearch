# Synthetic contract example, not a product test

Every research item, Figma readback, screenshot, comparison and browser result in
this directory is authored test data. No person, community, real Figma file or
browser was observed. The SVG files explicitly say they are fixtures. The example
route `https://example.test/product` is an identity field, not a reachable tested
website; the HTML is a disposable patch target, not a functioning search product.

The example proves orchestration, integrity links, explicit grants, actual local
text patching and replay gates. It does not prove a real user's UX preference or a
website's quality. A successful example report always has `product_complete:
false`, and all artifacts have `provenance: fixture`.

Run from the repository root:

```sh
python3 skills/remorsearch-ux-qa/scripts/ux_loop.py demo --output .ux-loop/example \
  --grant code_write --actor example-supervisor \
  --reason 'Approve the isolated fixture label patch'
```

Static JSON/SVG/patch files are authored test fixtures, not generated build or
runtime evidence. `uxloop/demo_factory.py` builds the equivalent fixture and
negative variants in temporary directories for the smoke check and the tests. It
never fetches live content or executes a browser.
