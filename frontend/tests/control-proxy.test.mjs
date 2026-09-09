import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {controlProxy} from '../scripts/control_proxy.mjs';

test('proxy authenticates only same-origin fixed requests without exposing the private token', async () => {
  const temp = await mkdtemp(path.join(tmpdir(), 'momentum-proxy-'));
  const previous = process.env.MOMENTUM_CONTROL_STATE_DIR;
  process.env.MOMENTUM_CONTROL_STATE_DIR = temp;
  const backend = createServer((req, res) => {
    assert.equal(req.headers['x-control-token'], 'test-private-secret');
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({service: 'online'}));
  });
  await new Promise(r => backend.listen(0, '127.0.0.1', r));
  await writeFile(path.join(temp, 'connection.json'), JSON.stringify({port: backend.address().port, token: 'test-private-secret'}));
  let middleware;
  const frontend = createServer((req, res) => {req.url = req.url.replace(/^\/control/, ''); void middleware(req, res);});
  await new Promise(r => frontend.listen(0, '127.0.0.1', r));
  const port = frontend.address().port;
  controlProxy(process.cwd()).configureServer({httpServer: frontend, config: {server: {port}}, middlewares: {use: (_, handler) => {middleware = handler;}}});
  const base = 'http://127.0.0.1:' + port;
  try {
    const good = await fetch(base + '/control/status');
    assert.equal(good.status, 200);
    assert.equal(await good.text(), '{"service":"online"}');
    assert.equal((await fetch(base + '/control/schedule', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{"enabled":true}'})).status, 403);
    assert.equal((await fetch(base + '/control/schedule', {method:'POST', headers:{Origin:'https://evil.example','Content-Type':'application/json'}, body:'{}'})).status, 403);
    assert.equal((await fetch(base + '/control/shell', {method:'POST', headers:{Origin:base,'Content-Type':'application/json'}, body:'{}'})).status, 404);
    assert.equal((await fetch(base + '/control/jobs', {method:'POST', headers:{Origin:base,'Content-Type':'application/json'}, body:'x'.repeat(17000)})).status, 413);
    assert.equal((await fetch(base + '/control/schedule', {method:'POST', headers:{Origin:base,'Content-Type':'application/json'}, body:'{"enabled":false}'})).status, 200);
    await new Promise(r => backend.close(r));
    assert.equal((await fetch(base + '/control/status')).status, 503);
  } finally {
    frontend.closeAllConnections(); backend.closeAllConnections();
    await new Promise(r => frontend.close(r)); backend.close();
    if (previous === undefined) delete process.env.MOMENTUM_CONTROL_STATE_DIR; else process.env.MOMENTUM_CONTROL_STATE_DIR = previous;
    await rm(temp, {recursive:true, force:true});
  }
});
