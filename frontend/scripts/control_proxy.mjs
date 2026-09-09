import { readFile } from 'node:fs/promises';
import { realpathSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { homedir } from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

export function controlProxy(frontendRoot) {
  return {
    name: 'restricted-local-control',
    configureServer(server) {
      const project = realpathSync(process.env.MOMENTUM_ARTIFACT_PROJECT_ROOT || path.dirname(execFileSync('git', ['rev-parse', '--path-format=absolute', '--git-common-dir'], {cwd: frontendRoot, encoding: 'utf8'}).trim()));
      const key = createHash('sha256').update(project).digest('hex').slice(0, 16);
      const state = process.env.MOMENTUM_CONTROL_STATE_DIR || path.join(homedir(), '.local/state/momentum-ui', key);
      server.middlewares.use('/control', async (req, res) => {
        const reply = (code, value) => { res.statusCode = code; res.setHeader('Content-Type', 'application/json'); res.setHeader('Cache-Control', 'no-store'); res.end(JSON.stringify(value)); };
        const port = server.httpServer?.address()?.port ?? server.config.server.port ?? 4173;
        const origins = [`http://127.0.0.1:${port}`, `http://localhost:${port}`];
        const origin = req.headers.origin;
        if (!origins.map(o => new URL(o).host).includes(req.headers.host) || (origin && !origins.includes(origin)) || (req.method === 'POST' && !origins.includes(origin)))
          return reply(403, {error: 'Same-origin local access required'});
        if (!((req.method === 'GET' && req.url === '/status') || (req.method === 'POST' && ['/jobs', '/schedule'].includes(req.url))))
          return reply(404, {error: 'Unsupported control endpoint'});
        try {
          const chunks = []; let bytes = 0;
          if (req.method === 'POST') {
            if (req.headers['content-type'] !== 'application/json') return reply(400, {error: 'JSON required'});
            for await (const chunk of req) { bytes += chunk.length; if (bytes > 16384) return reply(413, {error: 'Request too large'}); chunks.push(chunk); }
          }
          const connection = JSON.parse(await readFile(path.join(state, 'connection.json'), 'utf8'));
          if (!Number.isInteger(connection.port) || connection.port < 1 || connection.port > 65535 || typeof connection.token !== 'string') throw new Error('Invalid local connection');
          const response = await fetch(`http://127.0.0.1:${connection.port}${req.url}`, {
            method: req.method, headers: {'X-Control-Token': connection.token, 'Content-Type': 'application/json', ...(origin ? {Origin: origin} : {})},
            body: req.method === 'POST' ? Buffer.concat(chunks) : undefined, signal: AbortSignal.timeout(10000),
          });
          reply(response.status, await response.json());
        } catch { reply(503, {error: 'Local control service is offline. Start the local control service to run jobs or manage the schedule.'}); }
      });
    },
  };
}
