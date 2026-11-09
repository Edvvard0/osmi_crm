// Проверка prod-бандла: нет source maps и console.*
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

function walk(dir) {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}
const files = walk("dist");
const errors = [];
for (const f of files) {
  if (f.endsWith(".map")) errors.push(`source map: ${f}`);
  if (f.endsWith(".js") && /console\.(log|debug|info)\(/.test(readFileSync(f, "utf8")) && !f.includes("workbox") && !f.endsWith("sw.js"))
    errors.push(`console.* в ${f}`);
}
// Начальная загрузка (скрипты и modulepreload из index.html) — не более 250 КБ gzip.
const LIMIT_KB = 250;
const html = readFileSync(join("dist", "index.html"), "utf8");
const entry = new Set(
  [...html.matchAll(/<(?:script|link)[^>]+(?:src|href)="\/?([^"]+\.js)"/g)].map((m) => m[1]),
);
let initialBytes = 0;
for (const rel of entry) {
  try {
    initialBytes += gzipSync(readFileSync(join("dist", rel))).length;
  } catch {
    errors.push(`не найден файл начальной загрузки: ${rel}`);
  }
}
const initialKb = initialBytes / 1024;
if (initialKb > LIMIT_KB) errors.push(`начальный JS ${initialKb.toFixed(1)} КБ gzip > ${LIMIT_KB} КБ`);

if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}
console.log(`bundle ok (${files.length} files, начальный JS ${initialKb.toFixed(1)} КБ gzip)`);
