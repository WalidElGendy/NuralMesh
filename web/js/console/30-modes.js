/* ==========================================================================
   Answer modes — client-side metadata only.

   The prompts themselves live server-side in mesh_prompts.py. Two reasons:
   they cannot drift from the backend, and they are not shipped to the browser
   where anyone can read them.

   This replaces the beta's per-"agent" personas, which were the direct cause
   of the weak answers observed in the stored messages:

     · resolve_persona() substring-matched the CONVERSATION TITLE to choose a
       system prompt, and list_agents() auto-seeded seven threads named
       "Design Agent", "Sales Agent" and so on — so the thread's name silently
       decided how every answer in it was written. An economics question in a
       design-titled thread came back as "بصفتي مصمم وليس خبيرًا اقتصاديًا".
     · The prompt was an indented template literal, so every reply began with
       six literal spaces.
     · "Content Agent" demanded audience, goal and tone before answering
       anything, which reads as a broken product.

   Behaviour is now chosen deliberately on the composer, not inferred.
   ========================================================================== */

export const MODES = {
  ask: {
    label: 'Ask',
    icon: 'chat',
    hint: 'Direct answer. One model call.',
    steps: ['route', 'recall', 'draft'],
  },
  analyze: {
    label: 'Analyze',
    icon: 'chart',
    hint: 'Decompose → quantify → chart → stress-test.',
    steps: ['route', 'recall', 'plan', 'draft', 'verify'],
  },
  research: {
    label: 'Research',
    icon: 'globe',
    hint: 'Search the web, read, cite, reconcile conflicts.',
    steps: ['route', 'recall', 'ground', 'draft', 'verify'],
  },
};

export const DEFAULT_MODE = 'ask';
