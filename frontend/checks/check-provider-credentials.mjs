import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadEnv } from 'vite';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const env = loadEnv('production', root, '');
const keys = Object.entries(env)
  .filter(([name]) => /GEMINI_API_KEYS?$/.test(name))
  .flatMap(([, value]) => value.split(/[,;\s]+/))
  .filter((value) => value.length > 8 && !/example|placeholder|replace|your_/i.test(value));
const failures = [];
let scanned = 0;
async function scan(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const filename = path.join(directory, entry.name);
    if (entry.isDirectory()) { await scan(filename); continue; }
    if (!/\.(?:js|html|json|map)$/.test(entry.name)) continue;
    const source = await readFile(filename, 'utf8');
    scanned += 1;
    if (keys.some((key) => source.includes(key)) || /AIza[0-9A-Za-z_-]{35}/.test(source)) failures.push(path.relative(root, filename));
  }
}
await scan(path.join(root, 'dist'));
if (failures.length) {
  console.error(`FAIL: provider credential material found in ${failures.join(', ')}`);
  process.exitCode = 1;
} else {
  console.log(`PASS: scanned ${scanned} production artifacts; zero provider credential matches.`);
}
