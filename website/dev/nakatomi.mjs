import { createHmac, randomBytes } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';

const upstream = 'http://127.0.0.1:8788';
const cookieName = 'nakatomi_local_workspace';
const emailFor = id => `demo-${id}@example.org`;
const stages = ['Lead', 'Qualified', 'Proposal', 'Negotiation', 'Won', 'Lost'];
const collections = ['deals', 'companies', 'contacts', 'tasks', 'relationships', 'timeline'];
const same = (a, b) => a.toLowerCase() === b.trim().toLowerCase();
const result = (text, title, records = []) => ({
  collections: [],
  calls: title ? [{ id: title, title, domain: 'Nakatomi API · local workspace', records }] : [],
  answer: [{ text, ...(title ? { cite: [title] } : {}) }],
});

async function api(path, { token, method = 'GET', body } = {}) {
  const response = await fetch(upstream + path, {
    method,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body && JSON.stringify(body),
    signal: AbortSignal.timeout(12000),
  });

  if (!response.ok) {
    const error = new Error(`Nakatomi returned HTTP ${response.status} for ${method} ${path}.`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function localSecret() {
  const directory = new URL('../.nakatomi-dev/', import.meta.url);
  const path = new URL('session-secret', directory);
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  try {
    writeFileSync(path, randomBytes(32), { flag: 'wx', mode: 0o600 });
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
  }
  return readFileSync(path);
}

async function seed(token) {
  const post = (path, body) => api(path, { token, method: 'POST', body });
  const pipeline = await post('/pipelines', {
    name: 'Sales', slug: 'sales', is_default: true,
    stages: stages.map((name, position) => ({ name, slug: name.toLowerCase(), position, is_won: name === 'Won', is_lost: name === 'Lost' })),
  });
  await Promise.all([
    post('/companies', { name: 'Acme Corp', domain: 'acme.example' }),
    post('/companies', { name: 'Northwind Analytics', domain: 'northwind.example' }),
    post('/contacts', { first_name: 'John', last_name: 'Smith', title: 'CTO' }),
    post('/contacts', { first_name: 'Steve', last_name: 'Rivera' }),
    post('/deals', { name: 'Enterprise Deployment', amount: 25000, pipeline_id: pipeline.id, stage_id: pipeline.stages[0].id }),
  ]);
}

async function readCollection(name, query, token) {
  const path = `/${name}?${new URLSearchParams({ limit: '50', ...query })}`;
  const page = await api(path, { token });
  return { path, page };
}

async function findExact(name, field, value, token) {
  const matches = [];
  let cursor;
  do {
    const { page } = await readCollection(name, cursor ? { cursor } : {}, token);
    matches.push(...page.items.filter(record => same(field(record), value)));
    cursor = page.next_cursor;
  } while (cursor && matches.length < 2);
  return matches;
}

const contactName = record => [record.first_name, record.last_name].filter(Boolean).join(' ');

async function snapshot(token) {
  const [pages, pipelines] = await Promise.all([
    Promise.all(collections.map(async name => [name, (await readCollection(name, {}, token)).page.items])),
    api('/pipelines', { token }),
  ]);
  const records = Object.fromEntries(pages);
  const stageNames = new Map(pipelines.flatMap(pipeline => pipeline.stages.map(stage => [stage.id, stage.name])));
  const people = new Map(records.contacts.map(contact => [contact.id, contactName(contact)]));
  const companies = new Map(records.companies.map(company => [company.id, company.name]));
  const deals = new Map(records.deals.map(deal => [deal.id, deal.name]));
  const tasks = new Map(records.tasks.map(task => [task.id, task.title]));

  return {
    deals: records.deals.map(deal => ({ ...deal, stage: stageNames.get(deal.stage_id) })),
    companies: records.companies,
    contacts: records.contacts,
    tasks: records.tasks,
    relationships: records.relationships
      .filter(link => link.source_type === 'contact' && link.target_type === 'company')
      .map(link => ({ id: link.id, contact: people.get(link.source_id), company: companies.get(link.target_id) }))
      .filter(link => link.contact && link.company),
    timeline: records.timeline.slice(0, 20).map(event => {
      const names = { contact: people, company: companies, deal: deals, task: tasks };
      const name = names[event.entity_type]?.get(event.entity_id);
      const stage = stageNames.get(event.payload?.to_stage_id);
      const action = event.event_type.replaceAll('.', ' ').replaceAll('_', ' ');
      return {
        id: String(event.id), type: event.event_type, at: event.occurred_at,
        summary: stage && name ? `${name} moved to ${stage}` : name ? `${name} · ${action}` : action,
      };
    }),
  };
}


async function execute(prompt, token, selectedTools, session) {
  const task = /^create task (.+)$/i.exec(prompt);
  const completion = /^complete task (.+)$/i.exec(prompt);
  const move = /^move deal (.+) to (.+)$/i.exec(prompt);
  const link = /^link contact (.+) to (?:company )?(.+)$/i.exec(prompt);
  const context = /^show account context for (.+)$/i.exec(prompt);
  const recordCreate = /^(?:create|add)\s+(?:a\s+)?(company|contact|deal)\s+(?:named\s+)?(.+)$/i.exec(prompt);
  const followUp = /^(?:(?:mark|set) (?:that|it) (?:as )?(?:done|complete)|complete (?:it|that))\.?$/i.test(prompt);

  if (!selectedTools && task) {
    const record = await api('/tasks', { token, method: 'POST', body: { title: task[1] } });
    session.lastTask = record.id;
    return result(`Created the task ${record.title}.`, 'POST /tasks', [record]);
  }
  if (!selectedTools && (completion || followUp)) {
    if (!completion && !session.lastTask) return result('Which task should I complete? Use “Complete task” followed by its title.');
    const candidates = completion ? await findExact('tasks', task => task.title, completion[1], token) : [{ id: session.lastTask }];
    if (candidates.length !== 1) return result('Use the exact title of a single task.');
    const path = `/tasks/${encodeURIComponent(candidates[0].id)}`;
    const record = await api(path, { token, method: 'PATCH', body: { status: 'done' } });
    return result(`Completed ${record.title}.`, `PATCH ${path}`, [record]);
  }
  if (!selectedTools && recordCreate) {
    const [, rawType, name] = recordCreate;
    const type = rawType.toLowerCase();
    if (type === 'contact') {
      const [first_name, ...last] = name.trim().split(/\s+/);
      if (!last.length) return result('Use a first and last name for the contact.');
      const record = await api('/contacts', { token, method: 'POST', body: { first_name, last_name: last.join(' ') } });
      return result(`Created the contact ${contactName(record)}.`, 'POST /contacts', [record]);
    }
    if (type === 'deal') {
      const deal = /^(.+?)\s+for\s+\$?(\d+(?:,\d{3})*(?:\.\d{1,2})?)$/i.exec(name);
      if (!deal || !Number.isFinite(Number(deal[2].replaceAll(',', '')))) return result('Try “Create deal Pilot for 2500”.');
      const record = await api('/deals', { token, method: 'POST', body: { name: deal[1], amount: Number(deal[2].replaceAll(',', '')) } });
      return result(`Created the deal ${record.name}.`, 'POST /deals', [record]);
    }
    const record = await api('/companies', { token, method: 'POST', body: { name } });
    return result(`Created ${record.name}.`, 'POST /companies', [record]);
  }
  if (!selectedTools && move) {
    const matches = await findExact('deals', deal => deal.name, move[1], token);
    if (matches.length !== 1) return result('Use the exact name of a single deal.');
    const deal = matches[0];
    const pipeline = await api(`/pipelines/${encodeURIComponent(deal.pipeline_id)}`, { token });
    const stage = pipeline.stages.find(candidate => same(candidate.name, move[2]));
    if (!stage) return result(`Choose a pipeline stage: ${pipeline.stages.map(candidate => candidate.name).join(', ')}.`);
    const path = `/deals/${encodeURIComponent(deal.id)}`;
    const record = await api(path, { token, method: 'PATCH', body: { stage_id: stage.id, status: stage.is_won ? 'won' : stage.is_lost ? 'lost' : 'open' } });
    return result(`Moved ${deal.name} to ${stage.name}.`, `PATCH ${path}`, [record]);
  }
  if (!selectedTools && (link || context)) {
    const companies = await findExact('companies', company => company.name, context ? context[1] : link[2], token);
    if (companies.length !== 1) return result('Use the exact name of a single company.');
    const [company] = companies;
    if (context) {
      const path = `/agent/entity-context?${new URLSearchParams({ entity_type: 'company', entity_ref: company.id })}`;
      const record = await api(path, { token });
      return result(`Loaded account context for ${company.name}. Select the citation to inspect the details.`, 'GET /agent/entity-context', [record]);
    }
    const contacts = await findExact('contacts', contactName, link[1], token);
    if (contacts.length !== 1) return result('Use the exact full name of a single contact.');
    const record = await api('/relationships', { token, method: 'POST', body: {
      source_type: 'contact', source_id: contacts[0].id, target_type: 'company', target_id: company.id, relation_type: 'works_at',
    } });
    return result(`Linked ${contactName(contacts[0])} to ${company.name}.`, 'POST /relationships', [record]);
  }

  const briefing = !selectedTools && /\b(?:morning|pipeline) briefing\b/i.test(prompt);
  const topics = selectedTools ?? (briefing ? ['deals', 'tasks', 'timeline'] : collections.filter(name => new RegExp(`\\b${name === 'companies' ? 'compan(?:y|ies)' : name.endsWith('s') ? `${name.slice(0, -1)}s?` : name}`, 'i').test(prompt)));
  if (!topics.length) return result('Try “Add a task to respond to Steve”, “List open tasks”, or “Show the timeline”.');
  const calls = [];
  const answer = [];
  for (const name of topics) {
    const status = name === 'deals' && /\bwon\b/i.test(prompt) ? 'won'
      : name === 'deals' && /\blost\b/i.test(prompt) ? 'lost'
      : name === 'tasks' && /\b(?:completed|done)\b/i.test(prompt) ? 'done'
      : ['deals', 'tasks'].includes(name) && (briefing || /\bopen\b/i.test(prompt)) ? 'open'
      : undefined;
    const { path, page } = await readCollection(name, status ? { status } : {}, token);
    const title = `GET ${path}`;
    const labels = page.items.map(record => name === 'contacts' ? contactName(record) : record.title || record.name || record.event_type || record.relation_type).filter(Boolean);
    const text = labels.length ? `${name}: ${labels.join(', ')}.` : `No ${name} found.`;
    const entry = result(text, title, page.items);
    calls.push(...entry.calls);
    answer.push(...entry.answer);
  }
  return { collections: topics, calls, answer };
}

export function nakatomiDev() {
  return {
    name: 'nakatomi-local-backend',
    configureServer(server) {
      const secret = localSecret();
      const sessions = new Map();
      const hash = (purpose, id) => createHmac('sha256', secret).update(`${purpose}:${id}`).digest('hex');
      const cookie = id => `${id}.${hash('cookie', id)}`;

      async function provision(id) {
        const email = emailFor(id);
        const password = hash('login', id);
        let credentials;
        try {
          credentials = await api('/auth/login', { method: 'POST', body: { email, password } });
        } catch (error) {
          if (error.status !== 401) throw error;
          credentials = await api('/auth/signup', { method: 'POST', body: {
            email, password, workspace_name: 'Nakatomi Demo', workspace_slug: `demo-${id}`,
          } });
          await seed(credentials.access_token);
        }
        return {
          token: credentials.access_token,
          expires: Date.now() + Math.max(1, credentials.expires_in_seconds - 10) * 1000,
        };
      }

      function getSession(id) {
        let session = sessions.get(id);
        if (!session) {
          session = { ready: null, expires: 0, lastTask: undefined };
          sessions.set(id, session);
        }
        if (!session.ready || (session.expires && session.expires < Date.now())) {
          session.expires = 0;
          session.ready = provision(id).then(({ token, expires }) => {
            session.expires = expires;
            return token;
          }).catch(error => {
            session.ready = null;
            throw error;
          });
        }
        return session;
      }

      server.middlewares.use(async (req, res, next) => {
        const path = req.url?.split('?')[0];
        if (!['/api/dev-workspace', '/api/agent'].includes(path)) return next();
        const reply = (status, body) => {
          res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
          res.end(JSON.stringify(body));
        };
        if (req.method !== 'POST') return reply(405, { error: 'Use POST.' });
        if (!/^127\.0\.0\.1:\d+$/.test(req.headers.host || '') || req.headers.origin !== `http://${req.headers.host}`) {
          return reply(403, { error: 'Use the local preview URL.' });
        }

        let input;
        try {
          let bytes = 0;
          const body = [];
          for await (const chunk of req) {
            bytes += chunk.length;
            if (bytes > 4096) return reply(413, { error: 'Request too large.' });
            body.push(chunk);
          }
          input = JSON.parse(Buffer.concat(body).toString('utf8'));
        } catch {
          return reply(400, { error: 'Invalid request.' });
        }
        if (!input || typeof input !== 'object') return reply(400, { error: 'Invalid request.' });

        try {
          if (path === '/api/agent') {
            const preview = 'http://localhost:8792';
            const response = await fetch(`${preview}/api/agent`, {
              method: 'POST', headers: { Origin: preview, 'Content-Type': 'application/json' },
              body: JSON.stringify({ prompt: input.prompt, context: input.context, question: input.question }), signal: AbortSignal.timeout(12000),
            });
            return reply(response.status, await response.json());
          }

          const resetting = input.reset === true;
          const prompt = typeof input.prompt === 'string' ? input.prompt.trim() : '';
          if (!resetting && input.snapshot !== true && (!prompt || prompt.length > 600)) return reply(400, { error: 'Enter a prompt of up to 600 characters.' });
          const raw = req.headers.cookie?.split(';').map(value => value.trim()).find(value => value.startsWith(`${cookieName}=`))?.slice(cookieName.length + 1);
          const id = raw?.split('.')[0];
          const valid = id && /^[a-f0-9]{32}$/.test(id) && raw === cookie(id);
          const workspace = valid && !resetting ? id : randomBytes(16).toString('hex');
          const session = getSession(workspace);
          const token = await session.ready;
          if (workspace !== id) {
            res.setHeader('Set-Cookie', `${cookieName}=${cookie(workspace)}; Path=/api/dev-workspace; HttpOnly; SameSite=Strict; Max-Age=604800`);
            if (resetting && valid) sessions.delete(id);
          }
          if (resetting) return reply(200, { reset: true });
          if (input.snapshot === true) return reply(200, await snapshot(token));
          const tools = Array.isArray(input.tools) ? collections.filter(name => input.tools.includes(name)) : undefined;
          return reply(200, await execute(prompt, token, tools, session));
        } catch (error) {
          const code = [400, 403, 404, 409, 422, 429].includes(error.status) ? error.status : 502;
          return reply(code, { error: error.status ? error.message : 'Local service unavailable. Check the Nakatomi dev stack and try again.' });
        }
      });
    },
  };
}
