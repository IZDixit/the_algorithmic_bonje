import * as vscode from 'vscode';

const MAX_DEPTH = 4;
const MAX_CHILDREN = 60;
const SUPPORTED_DEBUG_TYPES = ['python', 'debugpy'];

type StackFrameInfo = {
  id: number;
  name: string;
  line?: number;
  source?: string;
};

type DfTableData = {
  columns: string[];
  rows: string[][];
  totalRows: number;
};

type VisualNode = {
  name: string;
  value: string;
  type?: string;
  children?: VisualNode[];
  dfTable?: DfTableData;
};

type VisualPayload = {
  status: string;
  sessionName?: string;
  sessionType?: string;
  expression: string;
  frame?: StackFrameInfo;
  focused?: VisualNode;
  scopes: VisualNode[];
  updatedAt: string;
};

class DebugVisualizerPanel {
  static current: DebugVisualizerPanel | undefined;

  private readonly panel: vscode.WebviewPanel;
  private readonly disposables: vscode.Disposable[] = [];
  private expression = '';

  private constructor(private readonly context: vscode.ExtensionContext) {
    this.panel = vscode.window.createWebviewPanel(
      'debugVisualizerClone',
      'Debug Visualizer Clone',
      vscode.ViewColumn.Beside,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
      }
    );

    this.panel.webview.html = this.getHtml();
    this.panel.onDidDispose(() => this.dispose(), null, this.disposables);
    this.panel.webview.onDidReceiveMessage(async (message) => {
      if (message?.type === 'refresh') {
        await this.refresh();
      }

      if (message?.type === 'setExpression') {
        this.expression = String(message.expression ?? '').trim();
        this.updateTitle();
        await this.refresh();
      }

      if (message?.type === 'clearExpression') {
        this.expression = '';
        this.updateTitle();
        await this.refresh();
      }
    }, null, this.disposables);
  }

  static show(context: vscode.ExtensionContext): DebugVisualizerPanel {
    if (!DebugVisualizerPanel.current) {
      DebugVisualizerPanel.current = new DebugVisualizerPanel(context);
    } else {
      DebugVisualizerPanel.current.panel.reveal(vscode.ViewColumn.Beside);
    }

    void DebugVisualizerPanel.current.refresh();
    return DebugVisualizerPanel.current;
  }

  async setExpression(expression: string): Promise<void> {
    this.expression = expression.trim();
    this.updateTitle();
    await this.refresh();
  }

  async refresh(): Promise<void> {
    const payload = await buildPayload(this.expression);
    await this.panel.webview.postMessage({ type: 'render', payload });
  }

  dispose(): void {
    DebugVisualizerPanel.current = undefined;
    while (this.disposables.length > 0) {
      this.disposables.pop()?.dispose();
    }
  }

  get currentExpression(): string {
    return this.expression;
  }

  private updateTitle(): void {
    this.panel.title = this.expression
      ? `Debug Visualizer Clone: ${this.expression}`
      : 'Debug Visualizer Clone';
  }

  private getHtml(): string {
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Debug Visualizer Clone</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #0b1220;
      --panel: #111a2b;
      --panel-soft: #162238;
      --accent: #f59e0b;
      --accent-2: #38bdf8;
      --text: #e5edf9;
      --muted: #9fb2cc;
      --border: rgba(159, 178, 204, 0.18);
      --good: #34d399;
      --bad: #f97316;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
    }

    body {
      margin: 0;
      padding: 16px;
      background: radial-gradient(circle at top, #162238 0%, var(--bg) 55%);
      color: var(--text);
    }

    .toolbar {
      display: grid;
      grid-template-columns: 1fr auto auto;
      gap: 10px;
      margin-bottom: 16px;
    }

    input {
      width: 100%;
      box-sizing: border-box;
      padding: 10px 12px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.04);
      color: var(--text);
    }

    button {
      border: 0;
      border-radius: 10px;
      padding: 10px 14px;
      cursor: pointer;
      font-weight: 600;
      color: #08111f;
      background: linear-gradient(135deg, var(--accent), #fde68a);
    }

    button.secondary {
      background: linear-gradient(135deg, var(--accent-2), #bfdbfe);
    }

    .hero {
      background: linear-gradient(160deg, rgba(245, 158, 11, 0.18), rgba(56, 189, 248, 0.12));
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 16px;
      margin-bottom: 16px;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.18);
    }

    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      color: var(--muted);
      font-size: 12px;
      margin-top: 8px;
    }

    .grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 16px;
    }

    .card {
      background: rgba(17, 26, 43, 0.9);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 16px;
    }

    .card h2 {
      margin: 0 0 12px;
      font-size: 14px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--muted);
    }

    .empty {
      color: var(--muted);
      padding: 12px;
      border-radius: 12px;
      background: rgba(255, 255, 255, 0.03);
    }

    details {
      margin: 4px 0;
      padding-left: 8px;
      border-left: 1px solid rgba(159, 178, 204, 0.16);
    }

    summary {
      list-style: none;
      cursor: pointer;
      padding: 6px 0;
    }

    summary::-webkit-details-marker {
      display: none;
    }

    .node {
      display: grid;
      grid-template-columns: minmax(120px, 220px) 1fr;
      gap: 12px;
      align-items: start;
    }

    .name {
      color: #fde68a;
      word-break: break-word;
    }

    .value {
      color: var(--text);
      word-break: break-word;
    }

    .type {
      color: var(--accent-2);
      margin-left: 8px;
      font-size: 12px;
    }

    .status-good {
      color: var(--good);
    }

    .status-bad {
      color: var(--bad);
    }

    .quick-buttons {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin-bottom: 14px;
    }

    .quick-label {
      font-size: 12px;
      color: var(--muted);
    }

    button.qb {
      font-size: 11px;
      padding: 5px 10px;
      border-radius: 6px;
      background: rgba(245, 158, 11, 0.12);
      color: var(--accent);
      border: 1px solid rgba(245, 158, 11, 0.25);
      cursor: pointer;
      font-weight: 500;
    }

    button.qb:hover {
      background: rgba(245, 158, 11, 0.25);
    }

    .df-wrap {
      overflow: auto;
      max-height: 420px;
      border-radius: 10px;
      border: 1px solid var(--border);
    }

    table.df {
      border-collapse: collapse;
      width: 100%;
      font-size: 12px;
      font-family: "IBM Plex Mono", "Cascadia Code", monospace;
    }

    table.df thead {
      position: sticky;
      top: 0;
      z-index: 2;
    }

    table.df th {
      background: #0b1220;
      color: var(--accent);
      padding: 7px 12px;
      text-align: left;
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }

    table.df td {
      padding: 5px 12px;
      color: var(--text);
      border-bottom: 1px solid rgba(159, 178, 204, 0.08);
      white-space: nowrap;
    }

    table.df tr:nth-child(even) td {
      background: rgba(255, 255, 255, 0.02);
    }

    table.df tr:hover td {
      background: rgba(56, 189, 248, 0.07);
    }

    .df-meta {
      font-size: 11px;
      color: var(--muted);
      margin-top: 8px;
    }
  </style>
</head>
<body>
  <div class="quick-buttons">
    <span class="quick-label">Quick inspect:</span>
    <button class="qb" data-expr="final_output_df">final_output_df</button>
    <button class="qb" data-expr="master_df">master_df</button>
    <button class="qb" data-expr="agg_ligo">agg_ligo</button>
    <button class="qb" data-expr="agg_mpesa">agg_mpesa</button>
    <button class="qb" data-expr="df_shift">df_shift</button>
    <button class="qb" data-expr="df_ligo_mapped">df_ligo_mapped</button>
  </div>
  <div class="toolbar">
    <input id="expression" placeholder="Expression to evaluate, e.g. order.items[0]" />
    <button id="refresh" class="secondary">Refresh</button>
    <button id="clear">Clear</button>
  </div>

  <section class="hero">
    <div id="status">Waiting for a debug session.</div>
    <div class="meta" id="meta"></div>
  </section>

  <section class="grid">
    <div class="card">
      <h2>Focused Expression</h2>
      <div id="focused" class="empty">No expression selected.</div>
    </div>
    <div class="card">
      <h2>Current Scopes</h2>
      <div id="scopes" class="empty">No scopes loaded yet.</div>
    </div>
  </section>

  <script>
    const vscode = acquireVsCodeApi();
    const expressionInput = document.getElementById('expression');
    const statusEl = document.getElementById('status');
    const metaEl = document.getElementById('meta');
    const focusedEl = document.getElementById('focused');
    const scopesEl = document.getElementById('scopes');

    function escapeHtml(value) {
      return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function renderDfTable(node) {
      var t = node.dfTable;
      var html = '<div class="df-meta">' + escapeHtml(node.value) + '</div>';
      html += '<div class="df-wrap"><table class="df"><thead><tr>';
      for (var i = 0; i < t.columns.length; i++) {
        html += '<th>' + escapeHtml(String(t.columns[i])) + '</th>';
      }
      html += '</tr></thead><tbody>';
      for (var r = 0; r < t.rows.length; r++) {
        html += '<tr>';
        for (var c = 0; c < t.rows[r].length; c++) {
          html += '<td>' + escapeHtml(String(t.rows[r][c])) + '</td>';
        }
        html += '</tr>';
      }
      html += '</tbody></table></div>';
      if (t.totalRows > t.rows.length) {
        html += '<div class="df-meta">Showing ' + t.rows.length + ' of ' + t.totalRows + ' rows.</div>';
      }
      return html;
    }

    function renderNode(node, open) {
      if (node.dfTable) { return renderDfTable(node); }
      var typeMarkup = node.type
        ? '<span class="type">' + escapeHtml(node.type) + '</span>'
        : '';
      var label = '<div class="node"><div><span class="name">'
        + escapeHtml(node.name)
        + '</span>'
        + typeMarkup
        + '</div><div class="value">'
        + escapeHtml(node.value)
        + '</div></div>';
      if (!node.children || node.children.length === 0) {
        return '<div>' + label + '</div>';
      }
      var children = node.children.map(function(child) { return renderNode(child, false); }).join('');
      return '<details ' + (open ? 'open' : '') + '><summary>' + label + '</summary>' + children + '</details>';
    }

    function renderCollection(nodes, emptyText) {
      if (!nodes || nodes.length === 0) {
        return '<div class="empty">' + escapeHtml(emptyText) + '</div>';
      }
      return nodes.map(function(node, index) { return renderNode(node, index < 2); }).join('');
    }

    function setExpressionFromInput() {
      vscode.postMessage({ type: 'setExpression', expression: expressionInput.value });
    }

    document.getElementById('refresh').addEventListener('click', () => {
      setExpressionFromInput();
    });

    document.getElementById('clear').addEventListener('click', () => {
      expressionInput.value = '';
      vscode.postMessage({ type: 'clearExpression' });
    });

    expressionInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        setExpressionFromInput();
      }
    });

    document.querySelectorAll('.qb').forEach(function(btn) {
      btn.addEventListener('click', function() {
        expressionInput.value = btn.getAttribute('data-expr') || '';
        setExpressionFromInput();
      });
    });

    window.addEventListener('message', (event) => {
      const payload = event.data?.payload;
      if (!payload) {
        return;
      }

      expressionInput.value = payload.expression || '';
      statusEl.textContent = payload.status;
      statusEl.className = payload.sessionName ? 'status-good' : 'status-bad';

      const meta = [];
      if (payload.sessionName) {
        meta.push('Session: ' + payload.sessionName + ' (' + (payload.sessionType || 'unknown') + ')');
      }
      if (payload.frame) {
        const source = payload.frame.source ? ' at ' + payload.frame.source + ':' + (payload.frame.line || '') : '';
        meta.push('Frame: ' + payload.frame.name + source);
      }
      meta.push('Updated: ' + payload.updatedAt);
      metaEl.innerHTML = meta.map((item) => '<span>' + escapeHtml(item) + '</span>').join('');

      focusedEl.innerHTML = payload.focused
        ? renderNode(payload.focused, true)
        : '<div class="empty">No focused expression selected.</div>';
      scopesEl.innerHTML = renderCollection(payload.scopes, 'No scopes available for the current frame.');
    });
  </script>
</body>
</html>`;
  }
}

export function activate(context: vscode.ExtensionContext): void {
  const refreshCurrent = async (): Promise<void> => {
    if (DebugVisualizerPanel.current) {
      await DebugVisualizerPanel.current.refresh();
    }
  };

  context.subscriptions.push(
    vscode.commands.registerCommand('debugVisualizerClone.open', async () => {
      DebugVisualizerPanel.show(context);
    }),
    vscode.commands.registerCommand('debugVisualizerClone.visualizeSelection', async () => {
      const panel = DebugVisualizerPanel.show(context);
      const editor = vscode.window.activeTextEditor;
      const selectedText = editor ? editor.document.getText(editor.selection).trim() : '';
      const expression = selectedText || await vscode.window.showInputBox({
        prompt: 'Expression to visualize',
        placeHolder: 'order.items[0]'
      });

      if (!expression) {
        return;
      }

      await panel.setExpression(expression);
    }),
    vscode.commands.registerCommand('debugVisualizerClone.refresh', refreshCurrent),
    vscode.commands.registerCommand('debugVisualizerClone.focusReconciliation', async () => {
      const panel = DebugVisualizerPanel.show(context);
      const session = vscode.debug.activeDebugSession;
      if (!session) {
        void vscode.window.showWarningMessage('Debug Visualizer: No active debug session. Start debugging app.py first.');
        return;
      }
      const frame = await resolveTopStackFrame(session).catch(() => undefined);
      if (!frame) {
        void vscode.window.showInformationMessage('Debug Visualizer: Session running but not paused. Enable the sidebar checkbox and click Process & Reconcile.');
        await panel.setExpression('final_output_df');
        return;
      }
      let targetExpression = 'final_output_df';
      try {
        await session.customRequest('evaluate', { expression: 'final_output_df', frameId: frame.id, context: 'watch' });
      } catch {
        targetExpression = 'master_df';
      }
      await panel.setExpression(targetExpression);
    }),
    vscode.debug.onDidStartDebugSession(() => { void refreshCurrent(); }),
    vscode.debug.onDidTerminateDebugSession(() => { void refreshCurrent(); }),
    vscode.debug.onDidChangeActiveDebugSession(() => { void refreshCurrent(); })
  );

  for (const debugType of SUPPORTED_DEBUG_TYPES) {
    context.subscriptions.push(
      vscode.debug.registerDebugAdapterTrackerFactory(debugType, {
        createDebugAdapterTracker: () => ({
          onDidSendMessage: (message: any) => {
            if (message?.type === 'event') {
              if (['continued', 'terminated', 'exited'].includes(message.event)) {
                void refreshCurrent();
              } else if (message.event === 'stopped') {
                const stoppedPanel = DebugVisualizerPanel.current;
                if (stoppedPanel && !stoppedPanel.currentExpression) {
                  void stoppedPanel.setExpression('final_output_df');
                } else {
                  void refreshCurrent();
                }
              }
            }
          }
        })
      })
    );
  }
}

export function deactivate(): void {}

async function buildPayload(expression: string): Promise<VisualPayload> {
  const session = vscode.debug.activeDebugSession;
  const updatedAt = new Date().toLocaleTimeString();

  if (!session) {
    return {
      status: 'No active debug session.',
      expression,
      scopes: [],
      updatedAt,
    };
  }

  try {
    const frame = await resolveTopStackFrame(session);
    if (!frame) {
      return {
        status: 'Debug session is active, but no stopped frame is available yet.',
        sessionName: session.name,
        sessionType: session.type,
        expression,
        scopes: [],
        updatedAt,
      };
    }

    const scopes = await loadScopes(session, frame.id);
    const focused = expression ? await evaluateExpression(session, frame.id, expression) : undefined;

    return {
      status: 'Visualizer connected to the active debug session.',
      sessionName: session.name,
      sessionType: session.type,
      expression,
      frame,
      focused,
      scopes,
      updatedAt,
    };
  } catch (error) {
    return {
      status: `Unable to inspect debug state: ${formatError(error)}`,
      sessionName: session.name,
      sessionType: session.type,
      expression,
      scopes: [],
      updatedAt,
    };
  }
}

async function resolveTopStackFrame(session: vscode.DebugSession): Promise<StackFrameInfo | undefined> {
  const threadsResponse = await session.customRequest('threads');
  const threads = Array.isArray(threadsResponse?.threads) ? threadsResponse.threads : [];

  for (const thread of threads) {
    const stackResponse = await session.customRequest('stackTrace', {
      threadId: thread.id,
      startFrame: 0,
      levels: 1,
    });

    const frame = stackResponse?.stackFrames?.[0];
    if (frame) {
      return {
        id: frame.id,
        name: frame.name,
        line: frame.line,
        source: frame.source?.path ?? frame.source?.name,
      };
    }
  }

  return undefined;
}

async function loadScopes(session: vscode.DebugSession, frameId: number): Promise<VisualNode[]> {
  const scopesResponse = await session.customRequest('scopes', { frameId });
  const scopes = Array.isArray(scopesResponse?.scopes) ? scopesResponse.scopes : [];

  const nodes = await Promise.all(scopes.map(async (scope: any) => ({
    name: scope.name,
    value: scope.expensive ? 'Expensive scope' : 'Scope',
    type: 'scope',
    children: scope.variablesReference > 0
      ? await loadVariables(session, scope.variablesReference, 0)
      : [],
  })));

  return nodes;
}

async function evaluateExpression(
  session: vscode.DebugSession,
  frameId: number,
  expression: string
): Promise<VisualNode> {
  const result = await session.customRequest('evaluate', {
    expression,
    frameId,
    context: 'watch',
  });

  const node: VisualNode = {
    name: expression,
    value: String(result?.result ?? ''),
    type: result?.type ? String(result.type) : undefined,
  };

  if ((node.type ?? '').toLowerCase().includes('dataframe')) {
    const dfTable = await tryExtractDataFrame(session, frameId, expression);
    if (dfTable) {
      node.dfTable = dfTable;
      return node;
    }
  }

  node.children = result?.variablesReference > 0
    ? await loadVariables(session, result.variablesReference, 0)
    : [];

  return node;
}

async function loadVariables(
  session: vscode.DebugSession,
  variablesReference: number,
  depth: number
): Promise<VisualNode[]> {
  const response = await session.customRequest('variables', { variablesReference });
  const variables = Array.isArray(response?.variables) ? response.variables : [];
  const limited = variables.slice(0, MAX_CHILDREN);

  const children = await Promise.all(limited.map(async (item: any) => ({
    name: String(item.name ?? ''),
    value: String(item.value ?? ''),
    type: item.type ? String(item.type) : undefined,
    children: item.variablesReference > 0 && depth + 1 < MAX_DEPTH
      ? await loadVariables(session, item.variablesReference, depth + 1)
      : [],
  })));

  if (variables.length > MAX_CHILDREN) {
    children.push({
      name: '...truncated',
      value: `${variables.length - MAX_CHILDREN} more children not shown`,
      type: 'limit',
      children: [],
    });
  }

  return children;
}

function formatError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

async function tryExtractDataFrame(
  session: vscode.DebugSession,
  frameId: number,
  expression: string
): Promise<DfTableData | undefined> {
  try {
    const jsonExpr = expression + ".head(300).to_json(orient='split', default_handler=str)";
    const res = await session.customRequest('evaluate', { expression: jsonExpr, frameId, context: 'watch' });
    const raw = String(res?.result ?? '');
    const unquoted = unpackPythonStringResult(raw);
    if (!unquoted) {
      return undefined;
    }
    const parsed: { columns: unknown[]; data: unknown[][] } = JSON.parse(unquoted);
    if (!Array.isArray(parsed?.columns) || !Array.isArray(parsed?.data)) {
      return undefined;
    }
    const lenRes = await session.customRequest('evaluate', {
      expression: 'len(' + expression + ')',
      frameId,
      context: 'watch',
    });
    const totalRows = parseInt(String(lenRes?.result ?? '0'), 10) || 0;
    return {
      columns: parsed.columns.map(String),
      rows: parsed.data.map((row) => (Array.isArray(row) ? row : []).map(String)),
      totalRows,
    };
  } catch {
    return undefined;
  }
}

function unpackPythonStringResult(raw: string): string | undefined {
  const s = raw.trim();
  if (s.startsWith("'") && s.endsWith("'") && s.length >= 2) {
    return s.slice(1, -1).replace(/\\'/g, "'").replace(/\\\\/g, '\\');
  }
  if (s.startsWith('"') && s.endsWith('"') && s.length >= 2) {
    return s.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, '\\');
  }
  if (s.startsWith('{') || s.startsWith('[')) {
    return s;
  }
  return undefined;
}