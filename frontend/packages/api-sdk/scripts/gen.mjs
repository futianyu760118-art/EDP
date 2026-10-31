/**
 * EDP-105 契约生成管线（包内脚本，避免跨包路径问题）：
 * 1. 校验 contracts/openapi.json 字节 sha256 与 contracts/openapi.sha256 一致（防篡改/漏导出）；
 * 2. openapi-typescript 生成 src/generated/schema.d.ts；
 * 3. 写 src/generated/fingerprint.json（CI 门禁比对用，见 T22）。
 */
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const sdkRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
// frontend/packages/api-sdk → 仓库根（contracts/ 中立场）
const repoRoot = path.resolve(sdkRoot, "..", "..", "..");
const contractPath = path.join(repoRoot, "contracts", "openapi.json");
const shaPath = path.join(repoRoot, "contracts", "openapi.sha256");
const outDir = path.join(sdkRoot, "src", "generated");
const schemaPath = path.join(outDir, "schema.d.ts");
const fingerprintPath = path.join(outDir, "fingerprint.json");

const actualSha = createHash("sha256").update(readFileSync(contractPath)).digest("hex");
const expectedSha = readFileSync(shaPath, "utf8").trim();
if (actualSha !== expectedSha) {
  console.error("[gen] contracts/openapi.json 与 openapi.sha256 指纹不符：");
  console.error(`  openapi.sha256 = ${expectedSha}`);
  console.error(`  实际 sha256    = ${actualSha}`);
  console.error("  请先重新导出契约快照（backend: uv run python scripts/export_openapi.py）再生成 SDK。");
  process.exit(1);
}

mkdirSync(outDir, { recursive: true });

const require = createRequire(import.meta.url);
const entry = require.resolve("openapi-typescript");
let pkgDir = path.dirname(entry);
while (!existsSync(path.join(pkgDir, "package.json"))) {
  pkgDir = path.dirname(pkgDir);
}
const pkg = JSON.parse(readFileSync(path.join(pkgDir, "package.json"), "utf8"));
const binField = typeof pkg.bin === "string" ? pkg.bin : pkg.bin?.["openapi-typescript"];
const binPath = binField ? path.join(pkgDir, binField) : null;

if (!binPath || !existsSync(binPath)) {
  console.error("[gen] 未找到 openapi-typescript CLI 入口，请先 pnpm install。");
  process.exit(1);
}

// 仓库路径含非 ASCII（如中文目录名）时，openapi-typescript 内部 redocly 解析器会
// 对路径做 URL 编码导致 ENOENT；先复制到系统临时目录（纯 ASCII）再生成。
const tmpDir = mkdtempSync(path.join(os.tmpdir(), "edp-api-sdk-gen-"));
const tmpContract = path.join(tmpDir, "openapi.json");
copyFileSync(contractPath, tmpContract);

const result = spawnSync(process.execPath, [binPath, tmpContract, "-o", schemaPath], {
  stdio: "inherit",
});
rmSync(tmpDir, { recursive: true, force: true });
if (result.status !== 0) {
  console.error("[gen] openapi-typescript 生成失败。");
  process.exit(result.status ?? 1);
}

const fingerprint = { sha256: actualSha, generatedAt: new Date().toISOString() };
writeFileSync(fingerprintPath, `${JSON.stringify(fingerprint, null, 2)}\n`, "utf8");
console.log(`[gen] src/generated/schema.d.ts + fingerprint.json 已生成（sha256=${actualSha.slice(0, 8)}）`);
