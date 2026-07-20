/** The small menu the clicky pointer morphs into when the user selects text.
 *  Ported from Marfini, rewritten without framer-motion/lucide — a CSS
 *  scale/opacity transition anchored at the pointer tip does the morph. It
 *  lives inside the cursor overlay (pointer-events-none), so it re-enables
 *  pointer events on itself while open. */

interface Props {
  text: string
  open: boolean
  onAsk: () => void
}

export function SelectionMenu({ text, open, onAsk }: Props) {
  return (
    <div
      data-selection-tooltip
      data-testid="clicky-menu"
      data-open={open}
      aria-hidden={!open}
      className="absolute left-0 top-0"
      style={{
        transformOrigin: 'top left',
        transform: open ? 'scale(1)' : 'scale(0.18)',
        opacity: open ? 1 : 0,
        pointerEvents: open ? 'auto' : 'none',
        transition: 'transform 160ms cubic-bezier(0.34,1.56,0.64,1), opacity 140ms ease',
      }}
    >
      {/* The pointer's tip, kept on the menu's corner — the menu IS the pointer,
          grown. */}
      <svg
        width="15"
        height="15"
        viewBox="0 0 22 22"
        className="pointer-events-none absolute -left-[2px] -top-[2px] z-10 text-indigo-600 drop-shadow-[0_1px_3px_rgba(0,0,0,0.35)]"
      >
        <polygon points="2,2 20,9 11,12 8,21" fill="currentColor" stroke="white" strokeWidth="1.6" />
      </svg>

      <div className="min-w-[9.5rem] max-w-[14rem] overflow-hidden rounded-xl rounded-tl-sm border border-zinc-200 bg-white p-1 text-zinc-800 shadow-xl shadow-black/20">
        <div className="truncate border-b border-zinc-100 px-2.5 pb-1.5 pl-4 pt-1 text-[10px] italic text-zinc-500">
          “{text}”
        </div>
        <button
          type="button"
          // onMouseDown (not onClick): preventDefault keeps the browser from
          // collapsing the selection; stopPropagation keeps the document
          // handler from clearing it before onAsk runs.
          onMouseDown={(e) => {
            e.preventDefault()
            e.stopPropagation()
            onAsk()
          }}
          className="mt-1 flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs font-medium text-zinc-700 transition-colors hover:bg-indigo-50 hover:text-indigo-700"
        >
          <span aria-hidden className="text-indigo-600">✦</span>
          Ask about this
        </button>
      </div>
    </div>
  )
}
