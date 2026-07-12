# `@engram/types`

Generated TypeScript interfaces for Engram's mountable `memory_router` HTTP
surface (plus shared graph/audit schemas). **Do not edit `index.d.ts` by hand.**

## Regenerate

From the qwen repo root:

```bash
python -m engram.export_types
# or: npm run generate --prefix packages/engram-types
```

## Install (git path)

```json
"@engram/types": "github:yfshaikh/qwen#consumer-sdk&path:packages/engram-types"
```

After this lands on `engram-poc`, point the ref at that branch instead.

Local sibling checkout:

```json
"@engram/types": "file:../../qwen/packages/engram-types"
```
