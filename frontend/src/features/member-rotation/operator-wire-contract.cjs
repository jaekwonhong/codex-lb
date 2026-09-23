"use strict";

// Invoked by the ASGI integration test with its unmodified response on stdin.
// Compile product TS in memory; use installed dependencies and no build/cache.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");

function rejectNetwork() {
  throw new Error("Real network is forbidden in the operator wire contract");
}

require("node:net").Socket.prototype.connect = rejectNetwork;
require("node:http").request = rejectNetwork;
require("node:http").get = rejectNetwork;
require("node:https").request = rejectNetwork;
require("node:https").get = rejectNetwork;
require("node:dns").lookup = rejectNetwork;
require("node:dns").resolve = rejectNetwork;
global.fetch = rejectNetwork;

const frontend = path.resolve(__dirname, "../../..");
const productRequire = Module.createRequire(path.join(frontend, "package.json"));
const ts = productRequire("typescript");
const cache = new Map();

function load(filename) {
  if (cache.has(filename)) return cache.get(filename).exports;
  const source = fs.readFileSync(filename, "utf8");
  const compiled = ts.transpileModule(source.replaceAll("import.meta.env.DEV", "false"), {
    fileName: filename,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
  }).outputText;
  const mod = new Module(filename, module);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  mod.require = (name) => {
    if (name.startsWith("@/")) return load(path.join(frontend, "src", `${name.slice(2)}.ts`));
    return productRequire(name);
  };
  cache.set(filename, mod);
  mod._compile(compiled, filename);
  return mod.exports;
}

async function main() {
  const wire = JSON.parse(fs.readFileSync(0, "utf8"));
  const { RotationOperatorResponseSchema } = load(path.join(__dirname, "schemas.ts"));
  const { getMemberRotationOperatorStatus } = load(path.join(__dirname, "api.ts"));
  assert(wire.workspaces.length > 0);
  assert.deepEqual(RotationOperatorResponseSchema.parse(wire), wire);
  let responseBody = wire;
  let calls = 0;
  global.fetch = async (url, options) => {
    assert.equal(url, "/api/member-rotation/operator");
    assert.equal(options.method, "GET");
    calls += 1;
    return new Response(JSON.stringify(responseBody), {
      status: 200,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  };
  assert.deepEqual(await getMemberRotationOperatorStatus(), wire);
  const noncanonical = structuredClone(wire);
  const quota = noncanonical.workspaces[0].quota;
  quota.count24h = quota.count24H;
  delete quota.count24H;
  responseBody = noncanonical;
  await assert.rejects(getMemberRotationOperatorStatus(), { code: "invalid_response_schema" });
  assert.equal(calls, 2);
  global.fetch = rejectNetwork;
  console.log(JSON.stringify({ schema: "pass", client: "pass", noncanonical: "rejected", workspaces: wire.workspaces.length }));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
