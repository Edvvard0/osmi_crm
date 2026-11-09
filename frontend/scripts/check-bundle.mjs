// Проверка prod-бандла: нет source maps и console.*
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

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
if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}
console.log(`bundle ok (${files.length} files)`);
