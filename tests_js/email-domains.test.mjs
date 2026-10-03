import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// The addresses allowed to verify (and so to order, deliver and upload photos) are listed twice: in the
// server (app.py ALLOWED_EMAIL_DOMAINS) and in the page (static/app.js). If they drift, the page would let
// someone type an address the server then refuses, or hide one the server accepts.
const domains = (source, pattern) => [...pattern.exec(source)[1].matchAll(/"(@[^"]+)"/g)].map((m) => m[1]);

test("the page and the server allow exactly the same email domains", () => {
  const py = readFileSync(new URL("../app.py", import.meta.url), "utf8");
  const js = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
  const server = domains(py, /^ALLOWED_EMAIL_DOMAINS\s*=\s*\(([^)]*)\)/m);
  const page = domains(js, /^const ALLOWED_EMAIL_DOMAINS\s*=\s*\[([^\]]*)\]/m);
  assert.deepEqual(page, server);
  assert.ok(server.includes("@ltc.lu"));
});

test("every language's invalid-address text names every allowed domain", () => {
  const i18n = readFileSync(new URL("../static/i18n.js", import.meta.url), "utf8");
  const texts = [...i18n.matchAll(/^\s+invalidUniLuEmail:\s*"([^"]+)"/gm)].map((m) => m[1]);
  assert.equal(texts.length, 11);
  for (const text of texts) for (const d of ["@uni.lu", "@student.uni.lu", "@ltc.lu"]) assert.ok(text.includes(d), `${d} missing in: ${text}`);
});
