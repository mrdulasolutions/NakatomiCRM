import { openDB, type DBSchema, type IDBPDatabase } from 'idb';

type Contact = { id: string; first_name: string; last_name: string; title?: string };
type Company = { id: string; name: string; domain?: string };
export const stages = ['Lead', 'Qualified', 'Proposal', 'Negotiation', 'Won', 'Lost'] as const;
export type Stage = typeof stages[number];
type Deal = { id: string; name: string; status: 'open' | 'won' | 'lost'; stage?: Stage; amount: number; currency: 'USD' };
type Task = { id: string; title: string; status: 'open' | 'done' };
type Relationship = { id: string; contact_id: string; company_id: string; contact: string; company: string };
type Event = { id: string; type: string; summary: string; at: string };

interface Workspace extends DBSchema {
  companies: { key: string; value: Company };
  contacts: { key: string; value: Contact };
  deals: { key: string; value: Deal };
  tasks: { key: string; value: Task };
  relationships: { key: string; value: Relationship };
  timeline: { key: string; value: Event };
}

const stores = ['companies', 'contacts', 'deals', 'tasks', 'relationships', 'timeline'] as const;
const companies: Company[] = [
  { id: 'sample-acme', name: 'Acme Corp', domain: 'acme.example' },
  { id: 'sample-northwind', name: 'Northwind Analytics', domain: 'northwind.example' },
  { id: 'sample-brightfield', name: 'Brightfield Health', domain: 'brightfield.example' },
];
const contacts: Contact[] = [
  { id: 'sample-john', first_name: 'John', last_name: 'Smith', title: 'CTO' },
  { id: 'sample-maya', first_name: 'Maya', last_name: 'Chen', title: 'VP of Operations' },
];
const deals: Deal[] = [
  { id: 'sample-enterprise', name: 'Enterprise Deployment', status: 'open', stage: 'Lead', amount: 25000, currency: 'USD' },
  { id: 'sample-expansion', name: 'Northwind Expansion', status: 'open', stage: 'Proposal', amount: 28500, currency: 'USD' },
  { id: 'sample-pilot', name: 'Brightfield Pilot', status: 'won', stage: 'Won', amount: 12000, currency: 'USD' },
];

let connection: Promise<IDBPDatabase<Workspace>> | undefined;

export function openWorkspace() {
  connection ??= openDB<Workspace>('nakatomi-agent-lab', 2, {
    upgrade(db, oldVersion, _version, tx) {
      if (oldVersion === 0) {
        for (const store of stores) db.createObjectStore(store, { keyPath: 'id' });
        for (const record of companies) void tx.objectStore('companies').add(record).catch(() => {});
        for (const record of contacts) void tx.objectStore('contacts').add(record).catch(() => {});
        for (const record of deals) void tx.objectStore('deals').add(record).catch(() => {});
      } else {
        for (const store of ['tasks', 'relationships', 'timeline'] as const) db.createObjectStore(store, { keyPath: 'id' });
      }
    },
    blocking() {
      void connection?.then(db => db.close());
      connection = undefined;
    },
  }).catch(error => {
    connection = undefined;
    throw error;
  });

  return connection;
}

export async function resetWorkspace() {
  const db = await openWorkspace();
  const tx = db.transaction(stores, 'readwrite');
  await Promise.all(stores.map(store => tx.objectStore(store).clear()));
  await Promise.all([
    ...companies.map(record => tx.objectStore('companies').add(record)),
    ...contacts.map(record => tx.objectStore('contacts').add(record)),
    ...deals.map(record => tx.objectStore('deals').add(record)),
    tx.done,
  ]);
}
