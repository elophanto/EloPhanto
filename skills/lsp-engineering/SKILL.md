---
name: lsp-engineering
description: Language Server Protocol specialist building unified code intelligence systems through LSP client orchestration and semantic indexing. Adapted from msitarzewski/agency-agents.
---

## Triggers

- language server protocol
- LSP integration
- code intelligence
- semantic indexing
- symbol graph
- code navigation
- go to definition
- find references
- hover documentation
- graph daemon
- multi-language LSP
- LSIF
- code visualization
- symbol resolution
- LSP orchestration

## Instructions

### Build the LSP Aggregator
- Orchestrate multiple LSP clients (TypeScript, PHP, Go, Rust, Python) concurrently.
- Transform LSP responses into unified graph schema (nodes: files/symbols, edges: contains/imports/calls/refs).
- Implement real-time incremental updates via file watchers and git hooks.
- Maintain sub-500ms response times for definition/reference/hover requests.
- TypeScript and PHP support must be production-ready first.

### Create Semantic Index Infrastructure
- Build nav.index.jsonl with symbol definitions, references, and hover documentation.
- Implement LSIF import/export for pre-computed semantic data.
- Design SQLite/JSON cache layer for persistence and fast startup.
- Stream graph diffs via WebSocket for live updates.
- Ensure atomic updates that never leave the graph in inconsistent state.

### Optimize for Scale and Performance
- Handle 25k+ symbols without degradation (target: 100k symbols at 60fps).
- Implement progressive loading and lazy evaluation strategies.
- Use memory-mapped files and zero-copy techniques where possible.
- Batch LSP requests to minimize round-trip overhead.
- Cache aggressively but invalidate precisely.

### LSP Protocol Compliance
- Strictly follow LSP 3.17 specification for all client communications.
- Handle capability negotiation properly for each language server.
- Implement proper lifecycle management (initialize -> initialized -> shutdown -> exit).
- Never assume capabilities; always check server capabilities response.

### Graph Consistency Requirements
- Every symbol must have exactly one definition node.
- All edges must reference valid node IDs.
- File nodes must exist before symbol nodes they contain.
- Import edges must resolve to actual file/module nodes.
- Reference edges must point to definition nodes.

### Performance Contracts
- /graph endpoint must return within 100ms for datasets under 10k nodes.
- /nav/:symId lookups must complete within 20ms (cached) or 60ms (uncached).
- WebSocket event streams must maintain <50ms latency.
- Memory usage must stay under 500MB for typical projects.

### Workflow
1. Set up LSP infrastructure: install language servers, verify they work.
2. Build graph daemon with WebSocket server, HTTP endpoints, file watcher.
3. Integrate language servers with proper capabilities, multi-root workspace support, request batching.
4. Optimize performance: profile bottlenecks, implement graph diffing, use worker threads, add distributed caching.

## Deliverables

### graphd Core Architecture
```typescript
interface GraphDaemon {
  lspClients: Map<string, LanguageClient>;
  graph: {
    nodes: Map<NodeId, GraphNode>;
    edges: Map<EdgeId, GraphEdge>;
    index: SymbolIndex;
  };
  httpServer: {
    '/graph': () => GraphResponse;
    '/nav/:symId': (symId: string) => NavigationResponse;
    '/stats': () => SystemStats;
  };
  wsServer: {
    onConnection: (client: WSClient) => void;
    emitDiff: (diff: GraphDiff) => void;
  };
}

interface GraphNode {
  id: string;
  kind: 'file' | 'module' | 'class' | 'function' | 'variable' | 'type';
  file?: string;
  range?: Range;
  detail?: string;
}

interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: 'contains' | 'imports' | 'extends' | 'implements' | 'calls' | 'references';
  weight?: number;
}
```

### Navigation Index Format
```jsonl
{"symId":"sym:AppController","def":{"uri":"file:///src/controllers/app.php","l":10,"c":6}}
{"symId":"sym:AppController","refs":[{"uri":"file:///src/routes.php","l":5,"c":10}]}
{"symId":"sym:AppController","hover":{"contents":{"kind":"markdown","value":"```php\nclass AppController extends BaseController\n```"}}}
```

## Success Metrics

- graphd serves unified code intelligence across all languages
- Go-to-definition completes in <150ms for any symbol
- Hover documentation appears within 60ms
- Graph updates propagate to clients in <500ms after file save
- System handles 100k+ symbols without performance degradation
- Zero inconsistencies between graph state and file system
