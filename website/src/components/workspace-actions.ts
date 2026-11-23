import { openWorkspace, stages } from './workspace-db';

const same = (left: string, right: string) => left.toLowerCase() === right.trim().toLowerCase();

export function workspaceEvent(type: string, summary: string) {
  return { id: crypto.randomUUID(), type, summary, at: new Date().toISOString() };
}

export async function runAction(question: string, signal: AbortSignal) {
  const db = await openWorkspace();
  signal.throwIfAborted();

  const move = /^move deal (.+) to (.+)$/i.exec(question);
  if (move) {
    const stage = stages.find(candidate => same(candidate, move[2]));
    if (!stage) return { text: `Choose a pipeline stage: ${stages.join(', ')}.` };
    const tx = db.transaction(['deals', 'timeline'], 'readwrite');
    const deals = await tx.objectStore('deals').getAll();
    const matched = deals.filter(deal => same(deal.name, move[1]));
    if (matched.length !== 1) return { text: 'Use the exact name of a single deal to move it.' };
    const status = stage === 'Won' ? 'won' : stage === 'Lost' ? 'lost' : 'open';
    const record = { ...matched[0], stage, status } as const;
    const text = `Moved ${record.name} to ${stage}.`;
    await Promise.all([
      tx.objectStore('deals').put(record),
      tx.objectStore('timeline').add(workspaceEvent('deal.stage_changed', text)),
      tx.done,
    ]);
    return { title: 'move_deal_stage', text, records: [record] };
  }

  const link = /^link contact (.+) to (?:company )?(.+)$/i.exec(question);
  if (link) {
    const tx = db.transaction(['contacts', 'companies', 'relationships', 'timeline'], 'readwrite');
    const [contacts, companies] = await Promise.all([tx.objectStore('contacts').getAll(), tx.objectStore('companies').getAll()]);
    const matchedContacts = contacts.filter(contact => same(`${contact.first_name} ${contact.last_name}`, link[1]));
    const matchedCompanies = companies.filter(company => same(company.name, link[2]));
    if (matchedContacts.length !== 1 || matchedCompanies.length !== 1) return { text: 'Use the exact names of a single contact and company to link them.' };
    const [contact] = matchedContacts;
    const [company] = matchedCompanies;
    const record = {
      id: `${contact.id}:${company.id}`, contact_id: contact.id, company_id: company.id,
      contact: `${contact.first_name} ${contact.last_name}`, company: company.name,
    };
    const links = tx.objectStore('relationships');
    if (await links.get(record.id)) return { title: 'relate', text: 'Those records are already linked.', records: [record] };
    const text = `Linked ${record.contact} to ${record.company}.`;
    await Promise.all([links.add(record), tx.objectStore('timeline').add(workspaceEvent('relationship.created', text)), tx.done]);
    return { title: 'relate', text, records: [record] };
  }

  const task = /^(create|add|complete) task (.+)$/i.exec(question);
  if (task) {
    const tx = db.transaction(['tasks', 'timeline'], 'readwrite');
    const tasks = tx.objectStore('tasks');
    const complete = task[1].toLowerCase() === 'complete';
    const title = task[2].trim();
    const matches = complete ? (await tasks.getAll()).filter(record => same(record.title, title)) : [];
    if (complete && matches.length !== 1) return { text: 'Use the exact title of a single task to complete it.' };
    if (matches[0]?.status === 'done') return { title: 'complete_task', text: 'That task is already complete.', records: matches };
    const record = complete ? { ...matches[0], status: 'done' as const } : { id: crypto.randomUUID(), title, status: 'open' as const };
    const text = complete ? `Completed ${record.title}.` : `Created the task ${record.title}.`;
    await Promise.all([tasks.put(record), tx.objectStore('timeline').add(workspaceEvent(complete ? 'task.completed' : 'task.created', text)), tx.done]);
    return { title: complete ? 'complete_task' : 'create_task', text, records: [record] };
  }

  return { text: 'Try “Move deal Enterprise Deployment to Proposal”, “Link contact John Smith to Acme Corp”, or “Create task Send proposal”.' };
}
