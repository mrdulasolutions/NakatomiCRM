import { openWorkspace } from './workspace-db';

export type WorkspaceSnapshot = Awaited<ReturnType<typeof readWorkspaceSnapshot>>;

export async function readWorkspaceSnapshot() {
  const db = await openWorkspace();
  const tx = db.transaction(['deals', 'companies', 'contacts', 'tasks', 'relationships', 'timeline'], 'readonly');
  const [deals, companies, contacts, tasks, relationships, timeline] = await Promise.all([
    tx.objectStore('deals').getAll(),
    tx.objectStore('companies').getAll(),
    tx.objectStore('contacts').getAll(),
    tx.objectStore('tasks').getAll(),
    tx.objectStore('relationships').getAll(),
    tx.objectStore('timeline').getAll(),
  ]);
  return {
    deals, companies, contacts,
    tasks: tasks.map(task => ({ ...task, status: task.status as string })),
    relationships: relationships.map(({ id, contact, company }) => ({ id, contact, company })),
    timeline: timeline.sort((a, b) => b.at.localeCompare(a.at)).slice(0, 20),
  };
}
