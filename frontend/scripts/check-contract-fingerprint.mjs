/**
 * EDP-105 前端契约指纹门禁（T22，无依赖，node 即可运行）：
 * 1. contracts/openapi.json 字节 sha256 必须与 contracts/openapi.sha256 一致（快照自体一致）；
 * 2. packages/api-sdk/src/generated/fingerprint.json 的 sha256 必须与契约指纹一致（SDK 未过期）。
 */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const repoRoot = path.dirname(frontendRoot);
const openapiPath = path.join(repoRoot, "contracts", "openapi.json");
const shaPath = path.join(repoRoot, "contracts", "openapi.sha256");
const fingerprintPath = path.join(
  frontendRoot,
  "packages",
  "api-sdk",
  "src",
  "generated",
  "fingerprint.json",
);

function fail(message) {
  console.error(`[contract-fingerprint-gate] FAIL: ${message}`);
  process.exit(1);
}

const actualSha = createHash("sha256").update(readFileSync(openapiPath)).digest("hex");
const recordedSha = readFileSync(shaPath, "utf8").trim();
if (actualSha !== recordedSha) {
  fail(
    `contracts/openapi.json 与 openapi.sha256 指纹不符（快照自体不一致）：\n` +
      `  openapi.sha256 = ${recordedSha}\n` +
      `  实际 sha256    = ${actualSha}\n` +
      `  请在 backend/ 下运行 uv run python scripts/export_openapi.py 重新导出并提交。`,
  );
}

const sdkSha = JSON.parse(readFileSync(fingerprintPath, "utf8")).sha256;
if (sdkSha !== actualSha) {
  fail(
    `packages/api-sdk/src/generated/fingerprint.json 与契约指纹不符（SDK 过期：契约变更后未重新生成）：\n` +
      `  SDK 指纹   = ${sdkSha}\n` +
      `  契约指纹   = ${actualSha}\n` +
      `  请在 frontend/ 下运行 pnpm --filter api-sdk gen 重新生成 SDK。`,
  );
}

console.log(`contract fingerprint OK (${actualSha.slice(0, 8)})`);
