const taskRequest = /^(?:(?:could|can|would) you\s+)?(?:please\s+)?(?:create|add|make)\s+(?:(?:me|a|new)\s+)*task(?:\s+(.+))?[.!?]?$/i;

export function parseTaskRequest(prompt: string): { title: string } | undefined {
  const match = taskRequest.exec(prompt.trim());
  if (!match) return;
  return { title: cleanTitle(match[1] ?? '') };
}

export function cleanTitle(value: string) {
  const title = value.trim().replace(/^(?:to|called|named)(?:\s+|$)/i, '').replace(/[.!?]$/, '').trim();
  return title ? title[0].toUpperCase() + title.slice(1) : '';
}

export function normalizeTaskPrompt(prompt: string) {
  const request = parseTaskRequest(prompt);
  return request?.title ? `Create task ${request.title}` : prompt;
}

export function isNewRequest(prompt: string) {
  return /^(?:show|list|find|move|link|complete|delete|update|create|add|mark)\b/i.test(prompt) || /\?$/.test(prompt);
}

export function isLocalCommand(prompt: string) {
  return /^(?:(?:create|add) (?:a )?(?:company|contact|deal|task) .+|complete task .+|move deal .+ to .+|link contact .+ to .+|show account context for .+|(?:morning|pipeline) briefing)[.!?]?$/i.test(prompt) ||
    /^(?:what|which) deals are (?:open|won|lost)\??$/i.test(prompt) ||
    /^(?:which companies are in this workspace|who are the contacts)\??$/i.test(prompt) ||
    /^(?:list|show) (?:the )?(?:(?:open|completed|done) )?(?:deals|companies|contacts|tasks|relationships|timeline)[.!?]?$/i.test(prompt);
}
