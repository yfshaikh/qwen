/** Wrap a model-generated SVG/HTML fragment in a locked-down iframe document.
 *
 *  Ported from Marfini's Whiteboard.tsx. The panel runs in an opaque-origin
 *  sandbox (allow-scripts, NO allow-same-origin), governed by a strict CSP whose
 *  only permitted script is a nonce-gated bridge that postMessages each
 *  [data-clicky] element's rect to the parent. The bridge is read-only outbound;
 *  it can't touch the parent DOM, cookies, or storage.
 */

/** Random per-render CSP nonce so a panel's stored HTML can't carry a
 *  predictable nonce and smuggle in its own script. */
function makeNonce(): string {
  const b = new Uint8Array(16)
  crypto.getRandomValues(b)
  return Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
}

/** The ONLY script allowed to run in a panel (nonce-gated). Reports each
 *  [data-clicky] element's rect to the parent so clicky can point at sub-parts
 *  of the panel. Read-only outbound: it postMessages coordinates and takes no
 *  input. */
function bridgeScript(nonce: string, panelId: string): string {
  return (
    `<script nonce="${nonce}">(function(){` +
    `function report(){var els=document.querySelectorAll('[data-clicky]'),o=[];` +
    `for(var i=0;i<els.length;i++){var r=els[i].getBoundingClientRect();` +
    `o.push({anchor:els[i].getAttribute('data-clicky'),x:r.x,y:r.y,w:r.width,h:r.height});}` +
    `parent.postMessage({type:'clicky-rects',panelId:${JSON.stringify(panelId)},rects:o},'*');}` +
    `addEventListener('load',report);addEventListener('resize',report);` +
    `if(window.ResizeObserver){new ResizeObserver(report).observe(document.documentElement);}` +
    `})();</script>`
  )
}

export function withCsp(html: string, panelId = ''): string {
  const nonce = makeNonce()
  const csp =
    "default-src 'none'; img-src data:; style-src 'unsafe-inline'; " +
    `script-src 'nonce-${nonce}'; font-src data:; base-uri 'none'; form-action 'none'`
  const meta = `<meta http-equiv="Content-Security-Policy" content="${csp}">`
  const bridge = bridgeScript(nonce, panelId)

  // A light-background wrapper so bare-SVG fragments read as a whiteboard and
  // center themselves. The CSP meta is the first thing in <head> so it governs
  // everything after it — any <script> the model emitted lands after the meta
  // and, lacking the nonce, is refused by the browser.
  const shell =
    `<!doctype html><html><head>${meta}` +
    `<style>html,body{margin:0;height:100%;background:#ffffff}` +
    `body{display:flex;align-items:center;justify-content:center;padding:12px;box-sizing:border-box}` +
    `svg{max-width:100%;max-height:100%;height:auto}</style></head>` +
    `<body>${html}${bridge}</body></html>`

  let doc = /<head[^>]*>/i.test(html)
    ? html.replace(/<head[^>]*>/i, (m) => `${m}${meta}`)
    : shell
  if (/<head[^>]*>/i.test(html)) {
    doc = /<\/body>/i.test(doc) ? doc.replace(/<\/body>/i, `${bridge}</body>`) : doc + bridge
  }
  return doc
}
