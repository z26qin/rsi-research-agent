#!/usr/bin/env node
// The only artifact input is .generated/artifacts; original reports are never read.
import {constants} from 'node:fs';
import {lstat, mkdir, open, realpath, writeFile} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {z} from 'zod';

const root = await realpath(fileURLToPath(new URL('../', import.meta.url)));
const input = '.generated/artifacts';
const output = 'dist/client/artifacts';
const reference = z.object({id:z.string(),path:z.string()});
const manifestSchema = z.object({
  schemaVersion:z.literal(1),snapshotId:z.string().regex(/^[a-zA-Z0-9_-]+$/),snapshotAt:z.string(),
  availability:z.enum(['complete','partial','unavailable']),sessions:z.array(reference),briefs:z.array(reference),
  gaps:z.array(z.unknown()),profiles:z.array(z.unknown()),
  diagnostics:z.array(z.object({file:z.string(),code:z.string(),message:z.string()})),
});

async function directories(relative, allowMissing = false) {
  let cursor = root;
  for (const part of relative.split('/')) {
    cursor = path.join(cursor, part);
    let entry;
    try { entry = await lstat(cursor); }
    catch (error) { if (allowMissing && error.code === 'ENOENT') return; throw error; }
    if (entry.isSymbolicLink()) throw new Error('Symbolic links are not allowed in build paths: '+relative);
    if (!entry.isDirectory()) throw new Error('Expected a build directory: '+relative);
  }
}

async function readSnapshot(relative) {
  await directories(path.posix.dirname(relative));
  const filename = path.join(root, relative);
  const metadata = await lstat(filename);
  if (metadata.isSymbolicLink()) throw new Error('Symbolic links are not allowed in artifact inputs: '+relative);
  if (!metadata.isFile() || metadata.size > 64 * 1024 * 1024) throw new Error('Invalid artifact file: '+relative);
  const handle = await open(filename, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    const before = await handle.stat();
    const data = await handle.readFile();
    const after = await handle.stat();
    if (before.ino !== metadata.ino || before.dev !== metadata.dev || before.size !== after.size || before.mtimeMs !== after.mtimeMs || data.length !== after.size) {
      throw new Error('Artifact changed while preparing build: '+relative);
    }
    // Invalid JSON must not become a seemingly usable published snapshot.
    JSON.parse(data.toString('utf8'));
    return data;
  } finally { await handle.close(); }
}

async function build() {
  const arguments_ = process.argv.slice(2);
  if (arguments_.length > 1 || (arguments_.length === 1 && arguments_[0] !== '--local')) {
    throw new Error('Usage: node scripts/build_artifacts.mjs [--local]');
  }
  const local = arguments_[0] === '--local';
  // Validate before Vite empties its output and before the preserved packaging wrapper writes.
  for (const directory of ['dist/client','dist/server','dist/.openai']) await directories(directory, true);
  const files = new Map();
  if (local) {
    const index = await readSnapshot(input+'/index.json');
    const manifest = manifestSchema.parse(JSON.parse(index.toString('utf8')));
    for (const row of [...manifest.sessions,...manifest.briefs]) {
      if (!/^snapshots\/[a-zA-Z0-9_-]+\/[a-zA-Z0-9_.-]+\.json$/.test(row.path) || row.path.split('/')[1] !== manifest.snapshotId) {
        throw new Error('Invalid snapshot reference: '+row.path);
      }
      if (!files.has(row.path)) files.set(row.path, await readSnapshot(input+'/'+row.path));
    }
    // Publish the captured index last; no later read can mix manifest generations.
    files.set('index.json', index);
  }
  const result = spawnSync(process.execPath, [path.join(root,'node_modules/vite/bin/vite.js'),'build','--outDir','dist/client','--emptyOutDir'], {cwd:root,stdio:'inherit'});
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error('Vite build failed'+(result.signal?' ('+result.signal+')':''));
  for (const [relative,data] of files) {
    const destination = path.join(root,output,relative);
    await directories(path.posix.dirname(output+'/'+relative), true);
    await mkdir(path.dirname(destination), {recursive:true});
    await writeFile(destination, data, {flag:'wx'});
  }
  console.log(local ? 'Local build includes the selected generated research snapshot.' : 'Demo build: local research artifacts are excluded.');
}

try { await build(); }
catch (error) { console.error(error.message); process.exitCode = 1; }
