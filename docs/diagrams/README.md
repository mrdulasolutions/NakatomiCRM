# Diagrams

All diagrams in this repo are authored as **Mermaid** with the `handDrawn`
look. They render inline on GitHub (in MD files and the wiki) and can be
edited in two ways.

## Inline editing (the fast path)

Find the diagram you want to change in its MD file. It looks like:

    ```mermaid
    %%{init: {"look": "handDrawn", "theme": "neutral"}}%%
    flowchart LR
      A --> B
    ```

Edit the Mermaid source directly. Preview via:

- GitHub's built-in renderer (just push and view the file on GitHub)
- VS Code's *Markdown Preview* with a Mermaid extension
- https://mermaid.live (paste, iterate, copy back)

## Excalidraw editing (the whiteboard path)

Excalidraw natively imports Mermaid. If you want to drag boxes around, add
hand-drawn annotations, or re-theme, use:

1. Open https://excalidraw.com
2. *Command palette → "Mermaid to Excalidraw"* (or click the Mermaid icon
   in the toolbar)
3. Paste the Mermaid source from the MD file
4. Edit on the whiteboard
5. *Command palette → "Copy as Mermaid"* (exports back to Mermaid)
6. Paste into the MD file, commit, push

If Excalidraw loses fidelity on export (it sometimes does for complex
layouts), keep the Mermaid source as canonical and manually reconcile.

## What to pin down in a diagram

- **Nodes = nouns.** A node is a thing (a service, a table, an agent), not
  an action.
- **Edges = verbs or data flow.** Label them. Unlabeled edges age poorly.
- **Direction = causality.** Left-to-right for pipelines, top-to-bottom for
  layered stacks, sequence diagrams for temporal flows across actors.
- **No more than ~12 nodes per diagram.** If you need more, split it.
- **handDrawn look, neutral theme** — keep it consistent across the repo.
  Theme overrides live in the `%%{init: ...}%%` directive at the top of
  each fence.

## Adding a new diagram

1. Draft it in Mermaid (inline or at https://mermaid.live).
2. Paste it into the MD file that documents the concept — not into a
   standalone image file. Inline Mermaid is diffable; PNGs aren't.
3. If the diagram is reused across three or more docs, promote it to a
   short `.md` snippet in this directory and link to it via an anchor.
