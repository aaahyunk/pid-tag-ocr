// Parity check: JS grammar port (web/grammar.js) vs Python validate.py.
//
// Usage:
//   python3 -m pid_tag_ocr.validate --cache cache_holdout/V01_03_033_117_3.csv \
//       --vendor V01 --out /tmp/py_canonical.json
//   node tests/verify_js_port.mjs /tmp/py_canonical.json
//
// Exits non-zero and prints a mismatch table if any token's decoded/layer/confident
// differs from the Python reference, or if the auto-decision rate differs.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, "..");
const PidGrammar = require(path.join(ROOT, "web", "grammar.js"));

const pyJsonPath = process.argv[2] || "/tmp/py_canonical.json";
const py = JSON.parse(fs.readFileSync(pyJsonPath, "utf-8"));
const candidatePaths = [
  path.join(ROOT, "cache_holdout", py.cache),
  path.join(ROOT, "cache", py.cache),
];
const cachePath = candidatePaths.find((p) => fs.existsSync(p));
if (!cachePath) {
  console.error(`cache file not found in cache_holdout/ or cache/: ${py.cache}`);
  process.exit(2);
}

async function main() {
  const dataDir = path.join(ROOT, "web", "data");
  const readText = async (name) => fs.readFileSync(path.join(dataDir, name), "utf-8");
  const isaData = JSON.parse(fs.readFileSync(path.join(dataDir, "isa_5_1.json"), "utf-8"));
  const grammar = await PidGrammar.HierarchicalGrammar.load(readText, isaData);

  const cacheText = fs.readFileSync(cachePath, "utf-8");
  const rows = PidGrammar.parseCSVObjects(cacheText);

  const result = PidGrammar.decodeFile(rows, grammar, py.vendor);

  console.log(`JS  : n_detections=${result.nDetections} n_tag_candidates=${result.nTagCandidates}`);
  console.log(`JS  : layers=${JSON.stringify(Object.fromEntries(result.layerCount))}`);
  console.log(`PY  : n_detections=${py.n_detections} n_tag_candidates=${py.n_tag_candidates}`);
  console.log(`PY  : layers=${JSON.stringify(py.layer_contribution)}`);

  const jsConfident = result.records.filter((r) => r.confident).length;
  const jsAutoRate = jsConfident / result.nTagCandidates;
  const pyReviewRate = py.metrics.human_review_rate;
  const pyAutoRate = 1 - pyReviewRate;
  console.log(
    `JS  auto-decision rate: ${(jsAutoRate * 100).toFixed(1)}%  (${jsConfident}/${result.nTagCandidates})`
  );
  console.log(
    `PY  auto-decision rate: ${(pyAutoRate * 100).toFixed(1)}%  (human_review_rate=${(pyReviewRate * 100).toFixed(1)}%)`
  );

  // records in py.records are in the same row order validate.py iterated (only
  // is_tag rows), matching result.records order exactly.
  const pyRecords = py.records;
  const jsRecords = result.records;

  const mismatches = [];
  if (pyRecords.length !== jsRecords.length) {
    console.log(
      `\n!! record count differs: PY=${pyRecords.length} JS=${jsRecords.length} -- cannot align by index, dumping both lengths only`
    );
  }
  const n = Math.min(pyRecords.length, jsRecords.length);
  for (let i = 0; i < n; i++) {
    const p = pyRecords[i];
    const j = jsRecords[i];
    const same =
      p.raw === j.raw &&
      p.decoded === j.decoded &&
      p.layer === j.layer &&
      Boolean(p.confident) === Boolean(j.confident);
    if (!same) {
      mismatches.push({
        idx: i,
        raw: p.raw,
        py_decoded: p.decoded,
        js_decoded: j.decoded,
        py_layer: p.layer,
        js_layer: j.layer,
        py_confident: p.confident,
        js_confident: j.confident,
      });
    }
  }

  if (mismatches.length === 0) {
    console.log(`\n✓ PARITY OK -- all ${n} tag-candidate tokens match Python exactly.`);
    console.log(
      jsAutoRate.toFixed(6) === pyAutoRate.toFixed(6)
        ? "✓ auto-decision rate matches exactly."
        : `✗ auto-decision rate differs: JS=${jsAutoRate} PY=${pyAutoRate}`
    );
    process.exit(mismatches.length === 0 && jsAutoRate.toFixed(6) === pyAutoRate.toFixed(6) ? 0 : 1);
  } else {
    console.log(`\n✗ MISMATCH -- ${mismatches.length} / ${n} tokens differ:\n`);
    console.log(
      "idx | raw | py_decoded -> js_decoded | py_layer -> js_layer | py_conf -> js_conf"
    );
    for (const m of mismatches) {
      console.log(
        `${m.idx} | ${m.raw} | ${m.py_decoded} -> ${m.js_decoded} | ${m.py_layer} -> ${m.js_layer} | ${m.py_confident} -> ${m.js_confident}`
      );
    }
    process.exit(1);
  }
}

main();
