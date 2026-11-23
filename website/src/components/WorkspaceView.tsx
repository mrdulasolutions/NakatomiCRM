import { useState } from 'react';
import { ArrowUpRight, Building2, CheckCircle2, Clock3, Columns3, ListTodo, Users } from 'lucide-react';
import { stages } from './workspace-db';
import type { WorkspaceSnapshot } from './workspace-view-data';

const views = [
  { id: 'pipeline', label: 'Pipeline', icon: Columns3 },
  { id: 'directory', label: 'Directory', icon: Users },
  { id: 'tasks', label: 'Tasks', icon: ListTodo },
  { id: 'activity', label: 'Activity', icon: Clock3 },
] as const;

const dealName = 'Enterprise Deployment';
const followUp = 'Send proposal to Steve';

export function WorkspaceView({ snapshot, loading, error, onRefresh, onDraft }: {
  snapshot: WorkspaceSnapshot | undefined;
  loading: boolean;
  error: string;
  onRefresh: () => void;
  onDraft: (prompt: string) => void;
}) {
  const [view, setView] = useState<(typeof views)[number]['id']>('pipeline');

  if (!snapshot) return (
    <section className="workspace-panel" aria-label="CRM workspace">
      <p role="status">{error || 'Loading your workspace…'}</p>
      {error && <button className="crm-button" type="button" onClick={onRefresh}>Try again</button>}
    </section>
  );

  const demoDeal = snapshot.deals.find(deal => deal.name === dealName);
  const task = snapshot.tasks.find(task => task.title === followUp);
  const steps = [
    { text: 'Move the Enterprise Deployment deal to Proposal', done: demoDeal?.stage === 'Proposal', command: `Move deal ${dealName} to Proposal` },
    { text: 'Create a follow-up task for Steve', done: Boolean(task), command: `Create task ${followUp}` },
    { text: 'Complete the follow-up', done: task?.status === 'done', command: `Complete task ${followUp}` },
  ];
  const next = steps.findIndex(step => !step.done);
  const openDeals = snapshot.deals.filter(deal => deal.status === 'open');
  const openTasks = snapshot.tasks.filter(task => ['open', 'in_progress'].includes(task.status));

  return (
    <section className="workspace-panel" aria-label="CRM workspace" aria-busy={loading}>
      <div className="crm-overview">
        <div><strong>{openDeals.length}</strong><span>Open deals</span></div>
        <div><strong>{snapshot.contacts.length}</strong><span>Contacts</span></div>
        <div><strong>{openTasks.length}</strong><span>Open tasks</span></div>
      </div>
      <details className="crm-scenario" open>
        <summary>Guided demo · Sales follow-up</summary>
        <p>Advance a deal, then track the next action. Each step opens the chat with a command you can review and send.</p>
        <ol>
          {steps.map((step, index) => (
            <li key={step.command}>
              {step.done ? <CheckCircle2 size={16} aria-label="Complete" /> : <span className="crm-step-number" aria-hidden="true">{index + 1}</span>}
              <span>{step.text}</span>
              {index === next && <button type="button" className="crm-button" disabled={loading} onClick={() => onDraft(step.command)}>Open in chat <ArrowUpRight size={14} aria-hidden="true" /></button>}
            </li>
          ))}
        </ol>
        {next === -1 && <p role="status">Workflow complete. See the changes in Activity.</p>}
      </details>
      <div className="crm-toolbar">
        <nav aria-label="Workspace views">
          {views.map(({ id, label, icon: Icon }) => (
            <button key={id} type="button" aria-pressed={view === id} onClick={() => setView(id)}><Icon size={16} aria-hidden="true" />{label}</button>
          ))}
        </nav>
        <button type="button" className="crm-button" disabled={loading} onClick={onRefresh}>{loading ? 'Refreshing…' : 'Refresh'}</button>
      </div>
      {error && <p role="status">{error}</p>}
      {view === 'pipeline' && (
        <div className="crm-board" aria-label="Deal pipeline" tabIndex={0}>
          {stages.map(stage => {
            const deals = snapshot.deals.filter(deal => (deal.stage ?? (deal.status === 'won' ? 'Won' : deal.status === 'lost' ? 'Lost' : 'Lead')) === stage);
            return <section key={stage}><h2>{stage} <span>{deals.length}</span></h2>
              {deals.map(deal => <div className="crm-record" key={deal.id}><strong>{deal.name}</strong><span>{deal.amount == null ? 'Amount pending' : new Intl.NumberFormat('en-US', { style: 'currency', currency: deal.currency || 'USD' }).format(deal.amount)}</span></div>)}
              {!deals.length && <p>No deals</p>}
            </section>;
          })}
        </div>
      )}
      {view === 'directory' && (
        <div className="crm-directory">
          <section><h2><Building2 size={16} /> Companies</h2>
            {snapshot.companies.map(company => <div key={company.id} className="crm-record"><strong>{company.name}</strong>
              <span>{snapshot.relationships.filter(link => link.company === company.name).map(link => link.contact).join(', ') || company.domain || 'No linked contacts'}</span>
            </div>)}
          </section>
          <section><h2><Users size={16} /> Contacts</h2>
            {snapshot.contacts.map(contact => <div key={contact.id} className="crm-record"><strong>{contact.first_name} {contact.last_name}</strong><span>{contact.title || 'Contact'}</span></div>)}
          </section>
        </div>
      )}
      {view === 'tasks' && (
        <div className="crm-list">
          {!snapshot.tasks.length && <p>No tasks yet. Add a follow-up from chat to see it here.</p>}
          {snapshot.tasks.map(task => <div key={task.id} className="crm-record"><strong>{task.title}</strong><span>{task.status.replaceAll('_', ' ')}</span></div>)}
        </div>
      )}
      {view === 'activity' && (
        <div className="crm-list">
          {!snapshot.timeline.length && <p>Changes to your workspace will appear here.</p>}
          {snapshot.timeline.map(event => <div key={event.id} className="crm-record"><strong>{event.summary}</strong><span>{event.type} · <time dateTime={event.at}>{new Date(event.at).toLocaleString()}</time></span></div>)}
        </div>
      )}
    </section>
  );
}
