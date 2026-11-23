import { DurableObject } from 'cloudflare:workers';

const model = '@cf/meta/llama-3.3-70b-instruct-fp8-fast';
import { interpretPlan, tools } from './agent-plan.js';
const dailyLimit = 100;
const json = (body, status = 200) => Response.json(body, { status, headers: { 'Cache-Control': 'no-store' } });

export class DemoBudget extends DurableObject {
  reserve() {
    const day = new Date().toISOString().slice(0, 10);
    return this.ctx.storage.transaction(async tx => {
      const current = await tx.get('daily-inference');
      const used = current?.day === day ? current.used : 0;
      if (used >= dailyLimit) return false;
      await tx.put('daily-inference', { day, used: used + 1 });
      return true;
    });
  }
}

async function readInput(request) {
  const reader = request.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let size = 0;
  let raw = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > 4096) {
      await reader.cancel();
      return;
    }
    raw += decoder.decode(value, { stream: true });
  }
  const { prompt, context, question } = JSON.parse(raw + decoder.decode()) ?? {};
  if (typeof prompt !== 'string' || !prompt.trim() || prompt.length > 400) return;
  return {
    prompt: prompt.trim(),
    context: Array.isArray(context) ? context.filter(value => typeof value === 'string').slice(-3).map(value => value.slice(0, 160)) : [],
    question: typeof question === 'string' ? question.slice(0, 160) : '',
  };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== '/api/agent') return env.ASSETS.fetch(request);
    if (request.method !== 'POST') return json({ error: 'Use POST.' }, 405);
    if (request.headers.get('Origin') !== url.origin) return json({ error: 'Origin denied.' }, 403);
    const input = await readInput(request).catch(() => undefined);
    if (!input) return json({ error: 'Enter a question of up to 400 characters.' }, 400);

    try {
      const client = request.headers.get('CF-Connecting-IP') || 'local';
      if (!(await env.AGENT_LIMIT.limit({ key: client })).success) {
        return json({ error: 'AI limit reached. Try again in a minute or use a local command.' }, 429);
      }
      if (!(await env.DEMO_BUDGET.getByName('agent-lab').reserve())) {
        return json({ error: 'The demo has used its AI allowance for today. Local commands are still available.' }, 429);
      }
      const response = await env.AI.run(model, {
        messages: [
          { role: 'system', content: 'You are Nakatomi Agent Lab, a conversational CRM assistant. Use one appropriate tool for the latest user request. A create or update tool only proposes a change. Ask one question if the request lacks required information. Never invent a name, amount, title, or operation result. You can create CRM tasks, including recording a reminder as a task, but cannot send reminders or messages. Previous user prompts are context only. An earlier assistant question may clarify the latest answer. For general CRM questions, answer briefly without claiming access to any records.' },
          ...input.context.map(content => ({ role: 'user', content })),
          ...(input.question ? [{ role: 'assistant', content: input.question }] : []),
          { role: 'user', content: input.prompt },
        ],
        tools,
        max_tokens: 128,
        temperature: 0.1,
      });
      return json(interpretPlan(response));
    } catch (error) {
      console.error('Demo inference failed', error?.message);
      return json({ error: 'AI help is temporarily unavailable. Local commands still work.' }, 502);
    }
  },
};
