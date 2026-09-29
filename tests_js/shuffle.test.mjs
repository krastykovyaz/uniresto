import { test } from "node:test";
import assert from "node:assert/strict";
import { orderFromStorage, shuffled } from "../static/shuffle.js";

const NAMES = ["Food House", "Food Café", "Food Lab", "Food Zone"];

test("shuffled keeps every item exactly once and does not touch the input", () => {
  const input = [...NAMES];
  const out = shuffled(input);
  assert.deepEqual([...out].sort(), [...NAMES].sort());
  assert.deepEqual(input, NAMES);
});

test("shuffled is deterministic for a given random source", () => {
  const seq = (values) => { let i = 0; return () => values[i++ % values.length]; };
  assert.deepEqual(shuffled(NAMES, seq([0, 0, 0])), ["Food Café", "Food Lab", "Food Zone", "Food House"]);
  assert.deepEqual(shuffled(NAMES, seq([0.99, 0.99, 0.99])), NAMES);
});

test("every one of the 24 orderings can come up, roughly equally often", () => {
  const counts = new Map();
  const N = 24000;
  for (let i = 0; i < N; i++) {
    const key = shuffled(NAMES).join("|");
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  assert.equal(counts.size, 24);
  for (const n of counts.values()) assert.ok(n > 700 && n < 1300, `an ordering came up ${n} times of ${N}`);
});

test("each restaurant lands first about a quarter of the time", () => {
  const first = new Map();
  const N = 8000;
  for (let i = 0; i < N; i++) { const f = shuffled(NAMES)[0]; first.set(f, (first.get(f) ?? 0) + 1); }
  for (const name of NAMES) assert.ok(first.get(name) > 1700 && first.get(name) < 2300, `${name} first ${first.get(name)} times`);
});

test("a saved order for this session is reused as it is", () => {
  const saved = ["Food Zone", "Food Lab", "Food House", "Food Café"];
  assert.deepEqual(orderFromStorage(NAMES, JSON.stringify(saved)), { order: saved, fresh: false });
});

test("nothing saved, garbage, or a saved order that no longer fits all get a fresh shuffle", () => {
  for (const raw of [null, undefined, "", "not json", "{}", "[]", '["Food Lab"]', JSON.stringify([...NAMES, "Extra"]), JSON.stringify(["Food Lab", "Food Lab", "Food Zone", "Food House"]), JSON.stringify(["a", "b", "c", "d"])]) {
    const result = orderFromStorage(NAMES, raw);
    assert.equal(result.fresh, true, String(raw));
    assert.deepEqual([...result.order].sort(), [...NAMES].sort());
  }
});
