import assert from 'node:assert/strict';
import {cp, mkdir, mkdtemp, readFile, readdir, rm, symlink, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import test from 'node:test';

const frontend = fileURLToPath(new URL('../', import.meta.url));
const marker = 'PRIVATE_RESEARCH_BUILD_BOUNDARY_79f083';

async function fixture(t) {
  const temporary = await mkdtemp(path.join(tmpdir(), 'momentum-build-test-'));
  t.after(() => rm(temporary, {recursive:true, force:true}));
  const root = path.join(temporary, 'frontend');
  await mkdir(root);
  for (const name of ['src','scripts','worker','.openai','index.html','package.json','vite.config.mjs']) {
    await cp(path.join(frontend, name), path.join(root, name), {recursive:true});
  }
  await symlink(path.join(frontend, 'node_modules'), path.join(root, 'node_modules'), 'dir');
  const source = path.join(root, '.generated/artifacts');
  await mkdir(path.join(source, 'snapshots/current'), {recursive:true});
  const manifest = {schemaVersion:1,snapshotId:'current',snapshotAt:'2026-09-08T12:00:00Z',availability:'complete',
    sessions:[{id:'selected-session',path:'snapshots/current/session.json'}],briefs:[],gaps:[],profiles:[],diagnostics:[]};
  await writeFile(path.join(source, 'index.json'), JSON.stringify(manifest));
  await writeFile(path.join(source, 'snapshots/current/session.json'), JSON.stringify({id:'selected-session',marker}));
  await writeFile(path.join(source, 'snapshots/current/unreferenced.json'), 'DO_NOT_COPY_UNREFERENCED');
  await mkdir(path.join(source, 'snapshots/old'));
  await writeFile(path.join(source, 'snapshots/old/old.json'), 'DO_NOT_COPY_OLD');
  return {root,source,manifest};
}

function build(root, local = false) {
  return spawnSync('npm', ['run', local ? 'build:local' : 'build'], {cwd:root,encoding:'utf8',timeout:90_000});
}

async function contents(directory) {
  let result = '';
  for (const entry of await readdir(directory, {withFileTypes:true})) {
    const file = path.join(directory, entry.name);
    result += entry.isDirectory() ? await contents(file) : (await readFile(file)).toString();
  }
  return result;
}

test('default builds omit private snapshots, local builds include only references, and a default rebuild removes them', async t => {
  const {root,source} = await fixture(t);
  const original = await contents(source);
  let result = build(root);
  assert.equal(result.status, 0, result.stdout + result.stderr);
  await assert.rejects(readFile(path.join(root, 'dist/client/artifacts/index.json')), {code:'ENOENT'});
  assert.equal((await contents(path.join(root, 'dist'))).includes(marker), false);

  result = build(root, true);
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.equal(JSON.parse(await readFile(path.join(root, 'dist/client/artifacts/snapshots/current/session.json'))).marker, marker);
  assert.deepEqual(await readdir(path.join(root, 'dist/client/artifacts/snapshots')), ['current']);
  assert.deepEqual(await readdir(path.join(root, 'dist/client/artifacts/snapshots/current')), ['session.json']);
  assert.equal((await contents(path.join(root, 'dist'))).includes('DO_NOT_COPY'), false);

  result = build(root);
  assert.equal(result.status, 0, result.stdout + result.stderr);
  await assert.rejects(readFile(path.join(root, 'dist/client/artifacts/index.json')), {code:'ENOENT'});
  assert.equal((await contents(path.join(root, 'dist'))).includes(marker), false);
  assert.equal(await contents(source), original, 'Builds must leave generated source snapshots untouched');
});

test('local build rejects traversal references and leaves outside files untouched', async t => {
  const {root,source,manifest} = await fixture(t);
  manifest.sessions[0].path = '../../secret.json';
  await writeFile(path.join(root, 'secret.json'), marker);
  await writeFile(path.join(source, 'index.json'), JSON.stringify(manifest));
  const result = build(root, true);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Invalid snapshot reference/);
  assert.equal(await readFile(path.join(root, 'secret.json'), 'utf8'), marker);
});

test('local build rejects symlinked snapshot files', async t => {
  const {root,source} = await fixture(t);
  await writeFile(path.join(root, 'secret.json'), marker);
  const file = path.join(source, 'snapshots/current/session.json');
  await rm(file);
  await symlink(path.join(root, 'secret.json'), file);
  const result = build(root, true);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Symbolic links/);
});

test('default build refuses a symlinked output directory before Vite can clear it', async t => {
  const {root} = await fixture(t);
  const outside = path.join(root, 'protected');
  await mkdir(outside);
  await writeFile(path.join(outside, 'keep.json'), marker);
  await mkdir(path.join(root, 'dist'));
  await symlink(outside, path.join(root, 'dist/client'), 'dir');
  const result = build(root);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Symbolic links/);
  assert.equal(await readFile(path.join(outside, 'keep.json'), 'utf8'), marker);
});
