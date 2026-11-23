export const collections = ['deals', 'companies', 'contacts', 'tasks', 'relationships', 'timeline'];
const stages = ['Lead', 'Qualified', 'Proposal', 'Negotiation', 'Won', 'Lost'];
const text = { type: 'string' };

function tool(name, description, properties = {}) {
  return { name, description, parameters: { type: 'object', properties, required: Object.keys(properties), additionalProperties: false } };
}

export const tools = [
  ...collections.map(name => tool(`list_${name}`, `List CRM ${name}.`)),
  tool('show_account_context', 'Look up a company and its related records by exact name.', { company: text }),
  tool('create_task', 'Create a CRM task from an explicit request to track an action or set a reminder. Use the requested action as the title. This does not send notifications.', { title: text }),
  tool('complete_task', 'Complete a CRM task when its exact title is known.', { title: text }),
  tool('create_company', 'Create a company by name.', { name: text }),
  tool('create_contact', 'Create a contact using their full name.', { name: text }),
  tool('create_deal', 'Create a deal with a name and USD amount.', { name: text, amount: { type: 'number' } }),
  tool('move_deal_stage', 'Move a named deal to a pipeline stage.', { name: text, stage: { type: 'string', enum: stages } }),
  tool('link_contact', 'Link a contact and company by their exact names.', { contact: text, company: text }),
  tool('ask_clarifying_question', 'Ask one short question when a required name, title, amount, or target is missing or ambiguous.', { question: text }),
];

function cleanText(value) {
  return typeof value === 'string' && value.trim().length > 0 && value.trim().length <= 140 &&
    !/[\p{Cc}\u2028\u2029]/u.test(value) ? value.trim() : '';
}

function decode(call) {
  const name = call?.name ?? call?.function?.name;
  let args = call?.arguments ?? call?.function?.arguments;
  if (typeof args === 'string') {
    try { args = JSON.parse(args); } catch { return null; }
  }
  const toolDef = tools.find(tool => tool.name === name);
  if (!toolDef) return null;
  const required = toolDef.parameters.required;
  if (!required.length) return args == null || (typeof args === 'object' && !Array.isArray(args) && !Object.keys(args).length) ? { name, args: {} } : null;
  if (!args || Array.isArray(args) || typeof args !== 'object' || Object.keys(args).length !== required.length) return null;
  const values = {};
  for (const key of required) {
    if (!Object.hasOwn(args, key)) return null;
    if (key === 'amount') {
      const number = args.amount;
      if (typeof number !== 'number' || !Number.isFinite(number) || number < 0 || number > 1_000_000_000) return null;
      values.amount = Number(number.toFixed(2));
    } else {
      values[key] = cleanText(args[key]);
      if (!values[key]) return null;
    }
  }
  return { name, args: values };
}

export function interpretPlan(response) {
  const calls = Array.isArray(response?.tool_calls) ? response.tool_calls : [];
  const actions = calls.slice(0, 8).map(decode);
  const fallback = { message: 'What would you like me to do in the CRM? I can work with deals, companies, contacts, and tasks.' };
  if (calls.length > 8 || actions.some(action => !action)) return fallback;
  const clarification = actions.find(action => action.name === 'ask_clarifying_question');
  if (clarification) {
    return /\?$/.test(clarification.args.question) ? { message: clarification.args.question, clarification: true } : fallback;
  }
  const reads = collections.filter(name => actions.some(action => action.name === `list_${name}`));
  if (actions.length && actions.every(action => action.name.startsWith('list_'))) return { tools: reads };
  if (actions.length > 1) return { message: 'Which CRM action should I do first?', clarification: true };
  if (!actions.length) {
    const message = typeof response?.response === 'string' ? response.response.trim().slice(0, 350) : '';
    return message && !/^[\[{]/.test(message) ? { message } : fallback;
  }

  const [{ name, args }] = actions;
  switch (name) {
    case 'show_account_context': return { readCommand: `Show account context for ${args.company}` };
    case 'create_task': return { writeCommand: `Create task ${args.title}` };
    case 'complete_task': return { writeCommand: `Complete task ${args.title}` };
    case 'create_company': return { writeCommand: `Create company ${args.name}` };
    case 'create_contact': return { writeCommand: `Create contact ${args.name}` };
    case 'create_deal': return { writeCommand: `Create deal ${args.name} for ${args.amount.toFixed(2)}` };
    case 'move_deal_stage': {
      const stage = stages.find(stage => stage.toLowerCase() === args.stage.toLowerCase());
      return stage ? { writeCommand: `Move deal ${args.name} to ${stage}` } : fallback;
    }
    case 'link_contact': {
      if (/\sto\s/i.test(args.company)) return fallback;
      return { writeCommand: `Link contact ${args.contact} to company ${args.company}` };
    }
    default: return fallback;
  }
}
