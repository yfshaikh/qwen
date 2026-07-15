# `@engram/types`

Generated TypeScript interfaces for Engram memory HTTP shapes (from Pydantic
via `python tools/export_types.py`). **Do not edit `index.d.ts` by hand.**

## Regenerate (in the qwen repo)

```bash
python tools/export_types.py
# writes packages/engram-types/index.d.ts
```

## Consuming from Marfini (and other apps)

npm **cannot** reliably install a subdirectory of a GitHub monorepo at a
specific branch (`#branch&path:…` is ignored; `#branch::path:…` often still
fails in the fetcher). Until this package is published to the npm registry,
consumers should **vendor** the generated file:

```bash
# from Marfini/frontend
npm run sync:engram-types
# or:
curl -fsSL \
  "https://raw.githubusercontent.com/yfshaikh/qwen/consumer-sdk/packages/engram-types/index.d.ts" \
  -o src/modules/memory/generated/engram-types.ts
```

Local sibling checkout (dev only):

```bash
cp ../../qwen/packages/engram-types/index.d.ts \
  src/modules/memory/generated/engram-types.ts
```
