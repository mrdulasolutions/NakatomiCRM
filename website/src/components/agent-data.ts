import { openWorkspace } from './workspace-db';
import { runAction, workspaceEvent } from './workspace-actions';

export const exampleQuestions = [
  'What deals are open?',
  'Which companies are in this workspace?',
  'Who are the contacts?',
  'List open tasks',
  'Show the timeline',
];

const matches = {
  deals: /\b(deals?|pipeline|opportunit(?:y|ies)|revenue)\b/i,
  companies: /\b(compan(?:y|ies)|organizations?|accounts?)\b/i,
  contacts: /\b(contacts?|people|person)\b/i,
  tasks: /\b(tasks?|follow-ups?)\b/i,
  relationships: /\b(links?|relationships?)\b/i,
  timeline: /\b(timeline|history|audit)\b/i,
};

type Collection = keyof typeof matches;
const collections = Object.keys(matches) as Collection[];
const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
const hint = 'Try “Create company Acme Labs”, “Create contact Sam Rivera”, or “Create deal Pilot for 2500”.';

type Call = { id: string; title: string; domain: string; records: object[] };
type WorkspaceResult = { collections: Collection[]; calls: Call[]; answer: { text: string; cite?: string[] }[] };

function result(calls: Call[], answer: WorkspaceResult['answer']): WorkspaceResult {
  return { collections: collections.filter(name => calls.some(call => call.id === name)), calls, answer };
}

export function isWritePrompt(prompt: string) {
  return /^(create|add|move|link|complete)\b/i.test(prompt);
}

async function createRecord(question: string, signal: AbortSignal): Promise<WorkspaceResult> {
  const command = question.match(/^(?:create|add)\s+(?:a\s+)?(company|contact|deal)\s+(?:named\s+)?(.+)$/i);
  if (!command) return result([], [{ text: hint }]);

  const [, kind, input] = command;
  const name = input.trim();
  const db = await openWorkspace();
  signal.throwIfAborted();
  const id = crypto.randomUUID();
  let call: Call;
  let text: string;

  switch (kind.toLowerCase()) {
    case 'company': {
      const record = { id, name };
      const tx = db.transaction(['companies', 'timeline'], 'readwrite');
      await Promise.all([
        tx.objectStore('companies').add(record),
        tx.objectStore('timeline').add(workspaceEvent('company.created', `Created ${name}`)),
        tx.done,
      ]);
      call = { id: 'companies', title: 'POST /companies', domain: 'Browser workspace · 1 record saved', records: [record] };
      text = `Created ${name} in this browser workspace.`;
      break;
    }
    case 'contact': {
      const [first_name, ...rest] = name.split(/\s+/);
      if (!rest.length) return result([], [{ text: 'Use a first and last name, for example “Create contact Sam Rivera”.' }]);
      const record = { id, first_name, last_name: rest.join(' ') };
      const tx = db.transaction(['contacts', 'timeline'], 'readwrite');
      await Promise.all([
        tx.objectStore('contacts').add(record),
        tx.objectStore('timeline').add(workspaceEvent('contact.created', `Created ${name}`)),
        tx.done,
      ]);
      call = { id: 'contacts', title: 'POST /contacts', domain: 'Browser workspace · 1 record saved', records: [record] };
      text = `Created the contact ${name}.`;
      break;
    }
    default: {
      const deal = name.match(/^(.+?)\s+for\s+\$?(\d+(?:,\d{3})*(?:\.\d{1,2})?)$/i);
      const amount = Number(deal?.[2].replaceAll(',', ''));
      if (!deal || !Number.isFinite(amount)) return result([], [{ text: 'Enter a deal name and a USD amount, for example “Create deal Pilot for 2500”.' }]);
      const record = { id, name: deal[1], amount, currency: 'USD', status: 'open', stage: 'Lead' } as const;
      const tx = db.transaction(['deals', 'timeline'], 'readwrite');
      await Promise.all([
        tx.objectStore('deals').add(record),
        tx.objectStore('timeline').add(workspaceEvent('deal.created', `Created ${record.name}`)),
        tx.done,
      ]);
      call = { id: 'deals', title: 'POST /deals', domain: 'Browser workspace · 1 record saved', records: [record] };
      text = `Created the open deal ${record.name} for ${money.format(amount)}.`;
    }
  }
  return result([call], [{ text, cite: [call.id] }]);
}

export async function runWorkspace(question: string, previousCollections: Collection[], signal: AbortSignal, selectedTools?: string[]): Promise<WorkspaceResult> {
  if (selectedTools === undefined && isWritePrompt(question)) {
    if (/^(?:create|add)\s+(?:a\s+)?(?:company|contact|deal)\b/i.test(question)) return createRecord(question, signal);
    const action = await runAction(question, signal);
    if (!action.title) return result([], [{ text: action.text }]);
    return result([{ id: action.title, title: action.title, domain: 'Browser workspace', records: action.records }], [{ text: action.text, cite: [action.title] }]);
  }
  if (/^(delete|update|remove|change|edit)\b/i.test(question)) {
    return result([], [{ text: `The browser workspace supports creating and listing records. ${hint}` }]);
  }

  const account = selectedTools === undefined && /^show account context for (.+)$/i.exec(question);
  if (account) {
    const db = await openWorkspace();
    signal.throwIfAborted();
    const tx = db.transaction(['companies', 'relationships', 'contacts'], 'readonly');
    const [companies, relationships, contacts] = await Promise.all([
      tx.objectStore('companies').getAll(), tx.objectStore('relationships').getAll(), tx.objectStore('contacts').getAll(),
    ]);
    const matches = companies.filter(company => company.name.toLowerCase() === account[1].trim().toLowerCase());
    if (matches.length !== 1) return result([], [{ text: 'Use the exact name of a single company to load account context.' }]);
    const [company] = matches;
    const ids = new Set(relationships.filter(link => link.company_id === company.id).map(link => link.contact_id));
    const people = contacts.filter(person => ids.has(person.id));
    const text = people.length ? people.map(person => `${person.first_name} ${person.last_name}`).join(', ') : 'No linked contacts yet';
    return result([{ id: 'entity_context', title: 'entity_context', domain: 'Browser workspace · company and linked contacts', records: [{ company, contacts: people }] }], [{ text: `${company.name}: ${text}.`, cite: ['entity_context'] }]);
  }

  const briefing = selectedTools === undefined && /\b(?:morning|pipeline) briefing\b/i.test(question);
  const selected = briefing ? ['deals', 'tasks', 'timeline'] as const : collections.filter(name => selectedTools ? selectedTools.includes(name) : matches[name].test(question));
  const topics = selectedTools || selected.length ? selected : /\b(them|those|how many|total|and|what about)\b/i.test(question) ? previousCollections : [];
  if (!topics.length) return result([], [{ text: `Ask about deals, companies, or contacts. ${hint}` }]);

  const db = await openWorkspace();
  signal.throwIfAborted();
  const calls: Call[] = [];
  const answer: WorkspaceResult['answer'] = [];
  for (const name of topics) {
    let data: object[];
    let summary: string;
    if (name === 'deals') {
      const status = /\bwon\b/i.test(question) ? 'won' : /\blost\b/i.test(question) ? 'lost' : briefing || /\bopen\b/i.test(question) ? 'open' : undefined;
      const deals = (await db.getAll('deals')).filter(deal => !status || deal.status === status);
      const total = money.format(deals.reduce((sum, deal) => sum + deal.amount, 0));
      data = deals;
      summary = deals.length ? `${deals.length} ${status ?? ''} ${deals.length === 1 ? 'deal' : 'deals'} totaling ${total}: ${deals.map(deal => `${deal.name} (${money.format(deal.amount)})`).join(', ')}.`.replace('  ', ' ') : 'No deals match.';
    } else if (name === 'companies') {
      const companies = await db.getAll('companies');
      data = companies;
      summary = `Companies: ${companies.map(company => company.name).join(', ')}.`;
    } else if (name === 'contacts') {
      const contacts = await db.getAll('contacts');
      data = contacts;
      summary = `Contacts: ${contacts.map(contact => `${contact.first_name} ${contact.last_name}`).join(', ')}.`;
    } else if (name === 'tasks') {
      const status = /\b(?:done|completed)\b/i.test(question) ? 'done' : briefing || /\bopen\b/i.test(question) ? 'open' : undefined;
      const tasks = (await db.getAll('tasks')).filter(task => !status || task.status === status);
      data = tasks;
      summary = tasks.length ? tasks.map(task => `${task.title} (${task.status})`).join('; ') + '.' : 'No matching tasks.';
    } else if (name === 'relationships') {
      const links = await db.getAll('relationships');
      data = links;
      summary = links.length ? links.map(link => `${link.contact} → ${link.company}`).join('; ') + '.' : 'No linked contacts and companies yet.';
    } else {
      const events = (await db.getAll('timeline')).sort((a, b) => b.at.localeCompare(a.at)).slice(0, 10);
      data = events;
      summary = events.length ? events.map(event => event.summary).join(' · ') : 'The timeline is empty.';
    }
    signal.throwIfAborted();
    calls.push({ id: name, title: `GET /${name}`, domain: `Browser workspace · ${data.length} ${data.length === 1 ? 'record' : 'records'}`, records: data });
    answer.push({ text: summary, cite: [name] });
  }
  return result(calls, answer);
}
