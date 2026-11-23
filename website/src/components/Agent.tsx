import { useEffect, useRef, useState } from 'react';
import { Terminal } from 'lucide-react';
import { CitedAnswerChatInput, type CitedSentence, type CitedSource, type CitedStatus } from '@/components/ui/cited-answer-chat-input';
import { exampleQuestions, isWritePrompt, runWorkspace } from './agent-data';
import { resetWorkspace } from './workspace-db';
import { cleanTitle, isLocalCommand, isNewRequest, normalizeTaskPrompt, parseTaskRequest } from './task-commands';
import { WorkspaceView } from './WorkspaceView';
import { readWorkspaceSnapshot, type WorkspaceSnapshot } from './workspace-view-data';

type AgentPlan =
  | { tools: string[] }
  | { readCommand: string }
  | { writeCommand: string }
  | { message: string; clarification?: boolean };
type WorkspaceResult = Awaited<ReturnType<typeof runWorkspace>>;
type Turn = {
  status: CitedStatus;
  prompt: string;
  sources: CitedSource[];
  answer: CitedSentence[];
};

const backend = import.meta.env.DEV && import.meta.env.PUBLIC_NAKATOMI_DEV === 'true';

async function backendRequest(body: object, signal?: AbortSignal) {
  const response = await fetch('/api/dev-workspace', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body), signal,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Local Nakatomi is unavailable.');
  return data;
}

const idle: Turn = { status: 'idle', prompt: '', sources: [], answer: [] };

export function Agent({ chatLaunch }: { chatLaunch: number }) {
  const [turn, setTurn] = useState(idle);
  const [view, setView] = useState<'chat' | 'workspace'>('workspace');
  const [snapshot, setSnapshot] = useState<WorkspaceSnapshot>();
  const [snapshotError, setSnapshotError] = useState('');
  const [loadingWorkspace, setLoadingWorkspace] = useState(false);
  const [draft, setDraft] = useState('');
  const [history, setHistory] = useState<{ prompt: string; answer: string }[]>([]);
  const [awaitingTaskTitle, setAwaitingTaskTitle] = useState(false);
  const [pendingWrite, setPendingWrite] = useState<string>();
  const [localOnly, setLocalOnly] = useState(false);
  const clarification = useRef('');

  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetMessage, setResetMessage] = useState('');
  const lastTask = useRef<string | null>(null);
  const [detail, setDetail] = useState<WorkspaceResult['calls'][number]>();
  const timers = useRef<number[]>([]);
  const previous = useRef<WorkspaceResult['collections']>([]);
  const calls = useRef<WorkspaceResult['calls']>([]);
  const running = useRef<AbortController | null>(null);
  const writeInProgress = useRef(false);

  function clearTimers() {
    timers.current.forEach(timer => window.clearTimeout(timer));
    timers.current = [];
    running.current?.abort();
    running.current = null;
    writeInProgress.current = false;
  }

  useEffect(() => clearTimers, []);
  useEffect(() => {
    if (chatLaunch > 0) setView('chat');
  }, [chatLaunch]);
  useEffect(() => {
    if (view === 'workspace') void refreshWorkspace();
  }, [view]);

  async function submit(prompt: string, confirmedCommand?: string) {
    if (running.current || resetting || loadingWorkspace || !prompt.trim()) return;
    prompt = prompt.trim();
    if (!confirmedCommand && pendingWrite && /^(?:confirm|yes|go ahead)[.!]?$/i.test(prompt)) {
      return submit(`Confirm: ${pendingWrite}`, pendingWrite);
    }
    if (pendingWrite) setPendingWrite(undefined);
    if (turn.status === 'done') {
      setHistory(items => [...items.slice(-19), { prompt: turn.prompt, answer: turn.answer.map(sentence => sentence.text).join(' ') }]);
    }
    setDetail(undefined);
    setDraft('');
    setResetMessage('');

    let normalized = normalizeTaskPrompt(prompt);
    const task = parseTaskRequest(prompt);
    const respond = (text: string) => setTurn({ ...idle, status: 'done', prompt, answer: [{ text }] });

    if (!confirmedCommand && awaitingTaskTitle && /^(?:cancel|never mind|nevermind)[.!]?$/i.test(prompt)) {
      setAwaitingTaskTitle(false);
      respond('Canceled. No task was created.');
      return;
    }
    if (!confirmedCommand && task && !task.title) {
      setAwaitingTaskTitle(true);
      respond('What should I call the task?');
      return;
    }
    if (!confirmedCommand && awaitingTaskTitle && !task && !isNewRequest(prompt)) {
      const title = cleanTitle(prompt);
      if (!title) {
        respond('Enter a title for the task, or say “cancel”.');
        return;
      }
      normalized = `Create task ${title}`;
    }
    setAwaitingTaskTitle(false);

    if (!confirmedCommand && /^(?:hi|hello|hey|help|what can you do)[.!?]*$/i.test(prompt)) {
      respond('I can list CRM records, create and complete tasks, move deals, and look up account context. To get started, say “create a new task.”');
      return;
    }

    const followUp = /^(?:(?:mark|set) (?:that|it) (?:as )?(?:done|complete)|complete (?:it|that))[.!]?$/i.test(prompt);
    if (!confirmedCommand && followUp && !lastTask.current && !backend && !clarification.current) {
      respond('Which task should I complete? Say “complete task” followed by its title.');
      return;
    }
    let command = confirmedCommand ?? (followUp && backend ? 'Mark that done' : followUp && lastTask.current ? `Complete task ${lastTask.current}` : normalized);
    const known = Boolean(confirmedCommand || isLocalCommand(command) || (followUp && (lastTask.current || backend)));
    const useAI = !known && !localOnly;
    const priorQuestion = clarification.current;
    clarification.current = '';
    if (pendingWrite && !confirmedCommand && /^(?:cancel|no|never mind|nevermind)[.!]?$/i.test(prompt)) {
      respond('Canceled. The workspace was not changed.');
      return;
    }

    const controller = new AbortController();
    running.current = controller;
    writeInProgress.current = !useAI && (isWritePrompt(command) || followUp);
    setTurn({ ...idle, status: 'reading', prompt });

    let operation: WorkspaceResult;
    try {
      let tools: string[] | undefined;
      if (useAI) {
        if (prompt.length > 400) {
          respond('Shorten your message to 400 characters for AI help.');
          clearTimers();
          return;
        }
        const context = [...history.map(item => item.prompt), ...(turn.status === 'done' ? [turn.prompt] : [])]
          .slice(-3).map(item => item.slice(0, 160));
        const response = await fetch('/api/agent', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt, context, ...(priorQuestion ? { question: priorQuestion } : {}) }),
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]),
        });
        const payload = await response.json() as AgentPlan & { error?: string };
        if (!response.ok) throw new Error(payload.error || 'AI help is unavailable.');
        if (controller.signal.aborted) return;

        if ('writeCommand' in payload) {
          setPendingWrite(payload.writeCommand);
          respond('I can make this change. Review the proposed action below.');
          clearTimers();
          return;
        }
        if ('message' in payload) {
          clarification.current = payload.clarification || payload.message.endsWith('?') ? payload.message : '';
          respond(payload.message);
          clearTimers();
          return;
        }
        if ('readCommand' in payload) command = payload.readCommand;
        else tools = payload.tools;
      }

      operation = backend
        ? await backendRequest({ prompt: command, tools }, controller.signal)
        : await runWorkspace(command, previous.current, controller.signal, tools);
    } catch (error) {
      if (controller.signal.aborted) return;
      setTurn({ ...idle, status: 'done', prompt, answer: [{ text: useAI || backend ? (error instanceof Error ? error.message : 'The service is unavailable.') : 'Could not access the browser workspace. Check that your browser allows local storage and try again.' }] });
      clearTimers();
      return;
    }
    if (controller.signal.aborted) return;
    calls.current = operation.calls;
    if (/^create task /i.test(command) && operation.calls.length) lastTask.current = command.slice(12);
    if (isWritePrompt(command) || followUp) {
      if (operation.collections.length) previous.current = operation.collections;
      setTurn({ status: 'done', prompt, sources: operation.calls, answer: operation.answer });
      clearTimers();
      return;
    }


    const later = (delay: number, callback: () => void) => {
      timers.current.push(window.setTimeout(callback, delay));
    };

    operation.calls.forEach(({ id, title, domain }, index) => {
      const start = 170 + index * 330;
      later(start, () => setTurn(turn => ({
        ...turn,
        sources: [...turn.sources, { id, title, domain, progress: 0.15 }],
      })));
      later(start + 260, () => setTurn(turn => ({
        ...turn,
        sources: turn.sources.map(source => source.id === id ? { ...source, progress: 1 } : source),
      })));
    });

    const answerAt = 300 + operation.calls.length * 330;
    later(answerAt, () => setTurn(turn => ({ ...turn, status: 'answering' })));
    operation.answer.forEach((_, index) => {
      later(answerAt + 220 + index * 340, () => {
        setTurn(turn => ({ ...turn, answer: operation.answer.slice(0, index + 1) }));
      });
    });
    later(answerAt + 300 + (operation.answer.length - 1) * 340, () => {
      if (operation.collections.length) previous.current = operation.collections;
      setTurn(turn => ({ ...turn, status: 'done' }));
      clearTimers();
    });
  }

  async function refreshWorkspace() {
    if (loadingWorkspace || resetting || running.current) return;
    setLoadingWorkspace(true);
    setSnapshotError('');
    try {
      setSnapshot(backend ? await backendRequest({ snapshot: true }) : await readWorkspaceSnapshot());
    } catch (error) {
      setSnapshotError(error instanceof Error ? error.message : 'Could not load the workspace.');
    } finally {
      setLoadingWorkspace(false);
    }
  }

  function stop() {
    clearTimers();
    setDraft(turn.prompt);
    setDetail(undefined);
    setTurn(idle);
  }

  async function reset() {
    if (running.current || resetting || loadingWorkspace) return;
    setResetting(true);
    try {
      if (backend) await backendRequest({ reset: true });
      else await resetWorkspace();
      clearTimers();
      calls.current = [];
      previous.current = [];
      lastTask.current = null;
      setHistory([]);
      setAwaitingTaskTitle(false);
      setPendingWrite(undefined);
      clarification.current = '';
      setDraft('');
      setDetail(undefined);
      setTurn(idle);
      setConfirmReset(false);
      setSnapshot(undefined);
      setSnapshotError('');
      setView('chat');
      setResetMessage('Workspace reset to starter records.');
    } catch {
      setResetMessage('Could not reset the workspace. Try again.');
    } finally {
      setResetting(false);
    }
  }

  const busy = resetting || loadingWorkspace || turn.status === 'reading' || turn.status === 'answering';

  return (
    <div className="agent">
      <div className="agent-top">
        <div className="agent-icon"><Terminal size={24} aria-hidden="true" /></div>
        <div><h1>Agent Lab</h1><p>{backend ? 'Private workspace on the local Nakatomi server.' : 'Read and create CRM records in a workspace stored in this browser.'}</p></div>
      </div>
      <nav className="agent-views" aria-label="Agent Lab views">
        <button type="button" aria-pressed={view === 'chat'} disabled={busy} onClick={() => setView('chat')}>Chat</button>
        <button type="button" aria-pressed={view === 'workspace'} disabled={busy} onClick={() => setView('workspace')}>Workspace</button>
      </nav>
      {view === 'workspace' && <WorkspaceView
        snapshot={snapshot}
        loading={loadingWorkspace}
        error={snapshotError}
        onRefresh={() => void refreshWorkspace()}
        onDraft={prompt => { setAwaitingTaskTitle(false); setDraft(prompt); setView('chat'); }}
      />}
      <div hidden={view !== 'chat'}>
      <div className="suggestions" aria-label="Example questions">
        {exampleQuestions.map(question => (
          <button key={question} type="button" disabled={busy} onClick={() => submit(question)}>
            {question}
          </button>
        ))}
      </div>
      <details className="workspace-hint">
        <summary>Try a CRM workflow</summary>
        <div className="suggestions">
          {['Move deal Enterprise Deployment to Proposal', 'Link contact John Smith to Acme Corp', 'Create task Send proposal', 'Complete task Send proposal', 'Show account context for Acme Corp', 'Morning briefing'].map(command => (
            <button key={command} type="button" disabled={busy} onClick={() => setDraft(command)}>{command}</button>
          ))}
        </div>
      </details>
      <div className="chat-stage">
        <CitedAnswerChatInput
          {...turn}
          history={history}
          className="max-w-none"
          value={draft}
          onValueChange={setDraft}
          onSubmit={prompt => void submit(prompt)}
          disabled={resetting}
          onStop={writeInProgress.current ? undefined : stop}
          onSourceClick={source => {
            const result = calls.current.find(call => call.id === source.id);
            if (result) setDetail(current => current?.id === result.id ? undefined : result);
          }}
          placeholder="Ask about the workspace…"
          followUpPlaceholder={awaitingTaskTitle ? 'Enter a task title…' : 'Ask a follow-up…'}
          answerNote={backend ? "Private Nakatomi workspace · local dev" : "Browser workspace · seeded with example records"}
        />
      </div>
      {pendingWrite && (
        <section className="tool-detail" aria-label="Proposed CRM change">
          <p>{pendingWrite}</p>
          <div className="agent-ai">
            <button type="button" disabled={busy} onClick={() => void submit(`Confirm: ${pendingWrite}`, pendingWrite)}>Confirm change</button>
            <button type="button" disabled={busy} onClick={() => void submit('Cancel')}>Cancel</button>
          </div>
        </section>
      )}
      <div className="agent-ai">
        <label><input type="checkbox" checked={localOnly} disabled={busy} onChange={event => setLocalOnly(event.target.checked)} /> Local commands only</label>
        <p>AI help may send your message and brief chat context to Workers AI.</p>
      </div>
      </div>
      <div className="agent-ai">
        {confirmReset ? <>
          <p>Clear this workspace’s changes and chat?</p>
          <button type="button" disabled={busy} onClick={() => void reset()}>Reset workspace</button>
          <button type="button" disabled={resetting} onClick={() => setConfirmReset(false)}>Cancel</button>
        </> : <button type="button" disabled={busy} onClick={() => setConfirmReset(true)}>Reset demo</button>}
        <p role="status">{resetMessage}</p>
      </div>
      {view === 'chat' && detail && (
        <section className="tool-detail" aria-label="Workspace tool output">
          <div><strong>{detail.title}</strong><button type="button" onClick={() => setDetail(undefined)}>Close output</button></div>
          <pre tabIndex={0}>{JSON.stringify(detail.records, null, 2)}</pre>
        </section>
      )}
    </div>
  );
}
