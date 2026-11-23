import { BookOpen } from 'lucide-react';

const repo = 'https://github.com/mrdulasolutions/NakatomiCRM';
const docs = `${repo}/blob/main/docs`;
const wiki = `${repo}/wiki`;

export function ProjectGuide({ onOpenChat }: { onOpenChat: () => void }) {
  return (
    <article className="guide">
      <BookOpen size={25} aria-hidden="true" />
      <h1>The CRM for AI agents.</h1>
      <p>Nakatomi gives agents a shared system of record for contacts, companies, deals, tasks, and the relationships between them. You can self-host it with PostgreSQL and review activity in the dashboard.</p>

      <section>
        <h2>See what an agent does</h2>
        <p>Ask about open deals in Agent Lab, then select a citation to inspect the workspace response from <code>GET /deals</code>. Try <code>Create company Acme Labs</code> to save a record, then ask which companies are in the workspace. Each browser profile starts with its own fictional starter records. Reset demo restores that starting point and clears the current chat. Try moving a deal to Proposal, linking a contact to a company, creating and completing a task, or requesting a morning briefing. The timeline records changes made in the demo. The full quickstart shows how an agent can create a company, link a contact and a deal, then verify the result through REST and the deal timeline.</p>
        <div className="guide-actions">
          <button type="button" className="primary" onClick={onOpenChat}>Chat with Nakatomi</button>
          <a href={`${docs}/5-MINUTE-AGENT.md`}>Read the five-minute quickstart</a>
        </div>
      </section>

      <section>
        <h2>What Nakatomi gives your agents</h2>
        <dl>
          <div><dt>CRM records and relationships</dt><dd>Link people, companies, and deals. Track deals through pipeline stages and keep notes, activities, and tasks with the records they belong to.</dd></div>
          <div><dt>Start a session with workspace context</dt><dd>Call <code>load_context</code> for workspace policies and open work. Use <code>describe_schema</code> when the agent needs to discover supported entities, fields, and events before acting.</dd></div>
          <div><dt>Investigate an account or pipeline</dt><dd>Use <code>entity_context</code> to pull an account’s related people, deals, recent activity, and open tasks in one request. Use <code>morning_briefing</code> to review stale deals, open work, and pending approvals across the workspace.</dd></div>
          <div><dt>Act on CRM records</dt><dd>An agent can search for a company, link a contact, move a deal to another stage, log a meeting, or create a follow-up task. Scoped credentials control which operations it can perform.</dd></div>
          <div><dt>Delegate and hand off work</dt><dd>Use A2A tasks to delegate work to another agent. A Nakatomi handoff can include the entity context so the receiving agent can pick up the account from the shared records.</dd></div>
          <div><dt>Review approvals and explain changes</dt><dd>Agents can request human approval for sensitive actions. Use <code>agent_activity</code> to review attributed work and <code>explain_change</code> to inspect a recorded change. Teammates can review activity in the audit dashboard.</dd></div>
          <div><dt>Imports and event delivery</dt><dd>Ingest contact data from CSV, JSON, vCard, or text. Subscribe other systems to CRM events with signed webhooks.</dd></div>
        </dl>
        <p className="guide-links"><a href={`${docs}/AGENT-OS.md`}>Agent operating system</a> · <a href={`${docs}/AGENT-WORKFORCE-KEYS.md`}>Agent access and attribution</a> · <a href={`${wiki}/Ingest`}>Import formats</a> · <a href={`${wiki}/Webhooks`}>Webhook events</a></p>
      </section>

      <section>
        <h2>What you can build</h2>
        <dl>
          <div><dt>Sales pipeline briefing</dt><dd>Review stale deals, summarize recent activity, and create follow-up tasks for opportunities that need attention.</dd></div>
          <div><dt>Account handoff</dt><dd>Give the next agent the company record, key contacts, active deals, and open tasks so it can pick up the work from the shared workspace.</dd></div>
          <div><dt>Lead intake</dt><dd>Import a contact export, check for matching records, and create linked follow-up tasks for the team.</dd></div>
          <div><dt>Approval and audit workflow</dt><dd>Route sensitive actions for human review and use the dashboard or API to trace the resulting record changes.</dd></div>
        </dl>
        <p className="guide-links"><a href={`${wiki}/Agent-Patterns`}>Agent workflow patterns</a> · <a href={`${docs}/demos/WORKFORCE-DEMO.md`}>Workforce demo</a></p>
      </section>

      <section>
        <h2>Choose how to connect</h2>
        <dl>
          <div><dt><a href={`${docs}/MCP.md`}>MCP</a></dt><dd>Connect an agent client to <code>/mcp</code> over Streamable HTTP. Use OAuth or a bearer API key, depending on what the client supports.</dd></div>
          <div><dt><a href={`${wiki}/REST-API`}>REST</a></dt><dd>Read and update CRM records from scripts and integrations. Start with <code>/schema</code> to discover entity fields and events.</dd></div>
          <div><dt><a href={`${wiki}/Protocols-and-Discovery`}>A2A and ACP</a></dt><dd>Discover agent capabilities, delegate tasks, and retrieve machine-readable workspace context.</dd></div>
        </dl>
      </section>

      <section>
        <h2>Run your own instance</h2>
        <ol>
          <li>Clone the repo, copy <code>.env.example</code> to <code>.env</code>, and set <code>SECRET_KEY</code>.</li>
          <li>Run <code>docker compose up -d</code> to start Nakatomi and PostgreSQL. Check <code>http://localhost:8000/health</code>.</li>
          <li>Open the local dashboard, create a workspace, and copy the API key when it’s shown. Give each agent only the scopes it needs.</li>
        </ol>
        <div className="guide-actions">
          <a className="primary guide-deploy" href="https://railway.com/deploy/nakatomicrm">Deploy on Railway</a>
          <a href={`${wiki}/Deployment`}>Deployment options</a>
          <a href={`${wiki}/Authentication`}>Authentication and scopes</a>
        </div>
      </section>

      <section>
        <h2>Review what changed</h2>
        <p>The timeline shows events on a record. The dashboard gives operators a workspace-wide audit view, and approval policies let agents request human review for sensitive actions.</p>
        <p className="guide-links"><a href={`${docs}/DASHBOARD.md`}>Dashboard guide</a> · <a href={`${docs}/ARCHITECTURE.md`}>Architecture</a> · <a href={`${repo}/blob/main/LICENSE`}>MIT license</a></p>
      </section>
    </article>
  );
}
