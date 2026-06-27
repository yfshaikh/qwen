export interface ExampleFlow {
  id: string
  title: string
  blurb: string
  accent: string // tailwind bg-* class for the marker dot
  prompts: string[]
}

// Curated multi-turn flows to drive the demo. Each prompt is sent on click;
// run a few turns, then Consolidate to watch the graph form.
export const EXAMPLE_FLOWS: ExampleFlow[] = [
  {
    id: 'calculus',
    title: 'Calculus: limits → continuity',
    blurb: 'Teach a concept, link a second, then quiz — two connected nodes form.',
    accent: 'bg-indigo-500',
    prompts: [
      'What is a limit in calculus? Keep it to two sentences.',
      'How does that connect to continuity?',
      'Quiz me: is a function with a hole in its graph continuous at the hole?',
    ],
  },
  {
    id: 'spanish',
    title: 'Spanish basics',
    blurb: 'A few beginner phrases, then a check that the tutor remembers them.',
    accent: 'bg-emerald-500',
    prompts: [
      'Teach me how to greet someone in Spanish.',
      "How do I say 'I would like a coffee, please'?",
      'Quiz me on the greetings you just taught me.',
    ],
  },
  {
    id: 'preferences',
    title: 'Learning preferences',
    blurb: 'State a preference, then see it recalled and shaping later answers.',
    accent: 'bg-amber-500',
    prompts: [
      'I learn best with real-world examples and analogies, not formal definitions.',
      'Explain recursion to me in that style.',
      'What do you remember about how I like to learn?',
    ],
  },
]

export type DemoStep =
  | { kind: 'say'; text: string }
  | { kind: 'consolidate'; note: string }

// A longer, guided "demo path": each message is prefilled so you just hit Send,
// with Consolidate prompts at the right moments to watch the graph form.
export const DEMO_PATH: DemoStep[] = [
  { kind: 'say', text: 'What is a limit in calculus? Keep it to two sentences.' },
  { kind: 'say', text: 'How does a limit relate to continuity?' },
  { kind: 'say', text: 'I learn best with concrete examples and analogies.' },
  { kind: 'say', text: 'Give me an example of a limit in that style.' },
  { kind: 'consolidate', note: 'Now Consolidate — watch "Limits" and "Continuity" become linked nodes.' },
  { kind: 'say', text: 'What is a derivative, and how does it build on limits?' },
  { kind: 'say', text: 'Quiz me with one short question about limits.' },
  { kind: 'say', text: 'My answer: the function approaches 2 as x nears the point.' },
  { kind: 'say', text: 'My goal is to pass my calculus final next month.' },
  { kind: 'consolidate', note: 'Consolidate again — derivatives, the quiz, and your goal join the graph.' },
  { kind: 'say', text: 'Given what you know about me, what should I review next?' },
]
