# Nakatomi CRM website

Astro serves the desktop shell and hydrates its React apps. The Worker serves the site and retains its separate Workers AI endpoint. The desktop layout and dock magnification are adapted from Alana Goyal's macOS Desktop Portfolio template, supplied as a ZIP. Its MIT notice is in [TEMPLATE-LICENSE.md](TEMPLATE-LICENSE.md).

## Develop and deploy

From `website/` with Node.js 22.23.4 or newer:

```sh
npm ci
npm run build
npx wrangler dev
```

Wrangler serves the built site and API. The desktop and simulated chat also run with `npm run dev` for hot reload. Run `npm run deploy` after signing in to Wrangler to publish the site. For Workers Builds, set the root to `website`, build with `npm run build`, and deploy with `npx wrangler deploy`.

## UI setup

This Astro project uses React, TypeScript, Tailwind CSS 4, and a shadcn-compatible `components.json`. Global Tailwind styles and theme tokens live in `src/styles/globals.css`. Desktop-specific styles live in `src/pages/site.css`.

Reusable UI primitives go in `src/components/ui`. The directory matches the `@/components/ui` alias and gives the shadcn CLI a consistent place to install primitives while app-specific components stay in `src/components`. The project already has the integration and dependencies. To add a registry component, run `npx shadcn@latest add <component>` from `website/`.

## Agent Lab

Agent Lab uses IndexedDB to persist companies, contacts, and deals in the current browser. It seeds fictional records on first use. Ask a read question or try `Create company Acme Labs`, `Create contact Sam Rivera`, or `Create deal Pilot for 2500`. Citation chips show the local operation’s actual result. Standard chat commands run in the browser without credentials or network inference. Use the Nakatomi quickstart to run the full FastAPI and PostgreSQL server.

The browser demo implements Nakatomi-style deal stages, contact-to-company relationships, tasks, account context, and a workspace timeline. Try `Move deal Enterprise Deployment to Proposal`, `Link contact John Smith to Acme Corp`, `Show account context for Acme Corp`, `Create task Send proposal`, `Complete task Send proposal`, and `Morning briefing`.

Send runs supported local commands directly. Other requests use one Workers AI call to choose a read tool, ask a clarifying question, or propose a write. Proposed writes require confirmation. Requests include up to 400 characters of prompt, three recent user messages of up to 160 characters each, and the latest clarification when applicable. The model output is capped at 128 tokens. CRM records and tool results stay in the workspace. The Worker applies a 3-request-per-minute edge limit per IP and a shared 100-call UTC daily quota enforced by a Durable Object. Requests reserve quota before inference, including failed calls. Use **Local commands only** to keep chat off the AI endpoint. Run the Wrangler preview for AI help.

## Full local backend preview

From `website/`, run:

```sh
docker compose -p nakatomi-preview -f compose.dev.yml up -d --build
npm run dev:backend
```

Open `http://127.0.0.1:8793`. The app provisions a seeded Nakatomi workspace on first use and identifies it with an HTTP-only session cookie. Each browser profile gets its own workspace. The separate `http://localhost:8792` Wrangler preview uses IndexedDB and serves the optional rate-limited AI route for both previews.

**Reset demo** clears the visible conversation and restores the starter records. In browser mode it replaces local records in one database transaction. In backend mode it switches to a newly seeded workspace on the local server and leaves the old workspace in the dev database. The AI budget stays shared across resets. Chat commands such as “add a task to respond to Steve” run without inference. Follow with “mark that done” in the same chat.

The local backend listens only on loopback. Its credentials and session signing key are for development.

Agent Lab opens on the workspace view. The guided sales follow-up scenario drafts commands in chat, then the pipeline, tasks, and activity views reflect the saved changes. The scenario and workspace views use no AI inference.
