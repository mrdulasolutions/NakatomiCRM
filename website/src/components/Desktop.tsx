import { useEffect, useRef, useState, type PointerEvent } from 'react';
import { BookOpen, Code2, Maximize2, Minus, Terminal, X } from 'lucide-react';
import { Agent } from './Agent';
import { ProjectGuide } from './ProjectGuide';

const repo = 'https://github.com/mrdulasolutions/NakatomiCRM';
const apps = [
  { id: 'agent', label: 'Agent Lab', icon: Terminal },
  { id: 'guide', label: 'Project Guide', icon: BookOpen },
] as const;
type App = typeof apps[number]['id'];

export function Desktop({ icon }: { icon: string }) {
  const [active, setActive] = useState<App | null>('agent');
  const [expanded, setExpanded] = useState(false);
  const [chatLaunch, setChatLaunch] = useState(0);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const windowRef = useRef<HTMLElement>(null);
  const dock = useRef<HTMLElement>(null);
  const drag = useRef<{ x: number; y: number; left: number; right: number; top: number; bottom: number } | null>(null);

  useEffect(() => {
    function recenter() { setPosition({ x: 0, y: 0 }); }
    window.addEventListener('resize', recenter);
    return () => window.removeEventListener('resize', recenter);
  }, []);

  function open(app: App) {
    setActive(app);
    setPosition({ x: 0, y: 0 });
  }

  function openChat() {
    open('agent');
    setChatLaunch(count => count + 1);
  }

  function hide() {
    setActive(null);
    requestAnimationFrame(() => dock.current?.querySelector<HTMLButtonElement>('button')?.focus());
  }

  function beginDrag(event: PointerEvent<HTMLElement>) {
    if (expanded || event.pointerType !== 'mouse' || event.button !== 0 || (event.target as HTMLElement).closest('button')) return;
    const frame = windowRef.current?.getBoundingClientRect();
    if (!frame) return;
    drag.current = {
      x: event.clientX - position.x, y: event.clientY - position.y,
      left: position.x + 8 - frame.left, right: position.x + innerWidth - frame.right - 8,
      top: position.y + 58 - frame.top, bottom: position.y + innerHeight - frame.top - 125,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function move(event: PointerEvent<HTMLElement>) {
    const start = drag.current;
    if (!start) return;
    setPosition({
      x: Math.max(start.left, Math.min(start.right, event.clientX - start.x)),
      y: Math.max(start.top, Math.min(start.bottom, event.clientY - start.y)),
    });
  }

  function magnify(event: PointerEvent<HTMLElement>) {
    if (event.pointerType !== 'mouse') return;
    // Gaussian magnification adapted from the supplied portfolio template's dock.
    for (const item of event.currentTarget.querySelectorAll<HTMLElement>('.dock-item')) {
      const { left, width } = item.getBoundingClientRect();
      const distance = event.clientX - (left + width / 2);
      const radius = width * 0.88;
      const scale = 1 + 0.35 * Math.exp(-(distance * distance) / (2 * radius * radius));
      item.style.setProperty('--zoom', String(scale));
    }
  }

  return (
    <div className="desktop">
      <header className="menubar">
        <a className="wordmark" href="/"><img src={icon} width="26" height="26" alt="" /> Nakatomi CRM</a>
        <nav aria-label="Project navigation">
          <a href={`${repo}/wiki`}>Docs</a>
          <a href={repo}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true" focusable="false">
              <path d="M8 0a8 8 0 0 0-2.53 15.59c.4.07.55-.17.55-.38l-.01-1.49c-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.65 7.65 0 0 1 4 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48l-.01 2.2c0 .21.15.46.55.38A8 8 0 0 0 8 0Z" />
            </svg>
            GitHub
          </a>
        </nav>
      </header>
      <main className="workspace">
        <div className="desktop-shortcuts">
          {apps.map(({ id, label, icon: Icon }) => <button type="button" key={id} onClick={() => open(id)}><Icon size={24} />{label}</button>)}
        </div>
        {active === null && <div className="desktop-intro"><h1>Nakatomi CRM</h1><p>The open-source CRM for AI agents.</p><button className="primary" onClick={openChat}>Chat with Nakatomi</button></div>}
        <section
          ref={windowRef}
          className={`app-window ${expanded ? 'expanded' : ''}`}
          hidden={active === null}
          aria-label={active === 'guide' ? 'Project Guide window' : 'Agent Lab window'}
          style={{ '--x': `${position.x}px`, '--y': `${position.y}px` } as React.CSSProperties}
        >
          <header className="titlebar" onPointerDown={beginDrag} onPointerMove={move} onLostPointerCapture={() => { drag.current = null; }}>
            <span>{active === 'guide' ? 'Project Guide' : 'Agent Lab'}</span>
            <div className="window-actions">
              <button aria-label="Minimize window" onClick={hide}><Minus size={16} /></button>
              <button aria-label={expanded ? 'Restore window' : 'Maximize window'} onClick={() => setExpanded(!expanded)}><Maximize2 size={14} /></button>
              <button aria-label="Close window" onClick={() => { setExpanded(false); hide(); }}><X size={17} /></button>
            </div>
          </header>
          <div className="window-content">
            <div hidden={active !== 'agent'}><Agent chatLaunch={chatLaunch} /></div>
            {active === 'guide' && <ProjectGuide onOpenChat={openChat} />}
          </div>
        </section>
      </main>
      <nav className="dock" aria-label="App dock" ref={dock} onPointerMove={magnify} onPointerLeave={event => {
        for (const item of event.currentTarget.querySelectorAll<HTMLElement>('.dock-item')) item.style.removeProperty('--zoom');
      }}>
        {apps.map(({ id, label, icon: Icon }) => <button key={id} className="dock-item" aria-label={label} title={label} aria-pressed={active === id} onClick={() => open(id)}><span className={`dock-icon ${id}`}><Icon size={24} /></span></button>)}
        <a className="dock-item source" aria-label="GitHub source" title="GitHub source" href={repo}><span className="dock-icon"><Code2 size={24} /></span></a>
      </nav>
    </div>
  );
}
