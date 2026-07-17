/*
 * JS port of pid_tag_ocr's Python decoder.
 * Source of truth: src/pid_tag_ocr/token_types.py, standards/isa.py, grammar.py
 * Ported logic must stay byte-for-byte behaviorally identical to the Python --
 * see tests/verify_js_port.mjs for the parity check against validate.py.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.PidGrammar = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // ============================================================
  // RFC4180 CSV parsing (matches Python csv.DictReader, incl. utf-8-sig BOM)
  // ============================================================
  function parseCSV(text) {
    const rows = [];
    let row = [];
    let field = "";
    let inQuotes = false;
    let i = 0;
    const len = text.length;
    while (i < len) {
      const c = text[i];
      if (inQuotes) {
        if (c === '"') {
          if (text[i + 1] === '"') {
            field += '"';
            i += 2;
            continue;
          }
          inQuotes = false;
          i++;
          continue;
        }
        field += c;
        i++;
        continue;
      } else {
        if (c === '"') {
          inQuotes = true;
          i++;
          continue;
        }
        if (c === ",") {
          row.push(field);
          field = "";
          i++;
          continue;
        }
        if (c === "\r") {
          i++;
          continue;
        }
        if (c === "\n") {
          row.push(field);
          rows.push(row);
          row = [];
          field = "";
          i++;
          continue;
        }
        field += c;
        i++;
        continue;
      }
    }
    if (field.length > 0 || row.length > 0) {
      row.push(field);
      rows.push(row);
    }
    return rows;
  }

  function parseCSVObjects(text) {
    const rows = parseCSV(text);
    if (!rows.length) return [];
    if (rows[0][0] && rows[0][0].charCodeAt(0) === 0xfeff) {
      rows[0][0] = rows[0][0].slice(1);
    }
    const header = rows[0];
    const out = [];
    for (let r = 1; r < rows.length; r++) {
      if (rows[r].length === 1 && rows[r][0] === "") continue;
      const obj = {};
      for (let c = 0; c < header.length; c++) {
        obj[header[c]] = rows[r][c] !== undefined ? rows[r][c] : "";
      }
      out.push(obj);
    }
    return out;
  }

  // ============================================================
  // token_types.py port
  // ============================================================
  function mask(t) {
    let out = "";
    for (const c of t) {
      if (c >= "0" && c <= "9") out += "#";
      else if ((c >= "A" && c <= "Z") || (c >= "a" && c <= "z")) out += "A";
      else out += c;
    }
    return out;
  }

  function isNominalPipeSize(t) {
    return /^\d{1,4}[A-Z]$/.test(t) || /^\d{1,3}"$/.test(t);
  }

  function isLineNumber(t) {
    if ((t.match(/-/g) || []).length < 2) return false;
    const fields = t.split("-");
    if (fields.length < 3) return false;
    const hasSize = /^\d{1,3}("|[A-Z])?$/.test(fields[0]);
    const hasLongNum = fields.some((f) => f.replace(/\D/g, "").length >= 3);
    return hasSize && hasLongNum;
  }

  function isInstrumentTag(t) {
    return /^[A-Z]{3,4}-?\d{2,6}[A-Z]?$/.test(t);
  }

  function isEquipmentTag(t) {
    return /^[A-Z]{1,2}-\d{2,6}[A-Z]?$/.test(t);
  }

  function isDrawingReference(t) {
    if (/^(PID|DWG|DRG|REF)/.test(t)) return true;
    return /^[A-Z]\d{3,5}-\d{1,3}$/.test(t);
  }

  function isAnnotation(t) {
    if (t.indexOf("-") === -1 && /^[A-Z]{3,}\d{1,2}$/.test(t)) return true;
    if (t.indexOf("/") !== -1) return true;
    if (t.indexOf('"') !== -1 && !/^\d{1,3}"$/.test(t) && !isLineNumber(t)) return true;
    return false;
  }

  const RULES = [
    ["line_number", isLineNumber],
    ["annotation", isAnnotation],
    ["nominal_pipe_size", isNominalPipeSize],
    ["drawing_reference", isDrawingReference],
    ["equipment_tag", isEquipmentTag],
    ["instrument_tag", isInstrumentTag],
  ];

  const TAG_TYPES = new Set([
    "instrument_tag",
    "instrument_code",
    "line_number",
    "equipment_tag",
    "drawing_reference",
    "nominal_pipe_size",
  ]);

  function classify(token) {
    const t = (token || "").trim().toUpperCase();
    const m = mask(t);
    if (t.length < 2) return { token: t, type: "unknown", isTag: false, mask: m };
    for (const [name, pred] of RULES) {
      if (pred(t, m)) return { token: t, type: name, isTag: TAG_TYPES.has(name), mask: m };
    }
    if (/^[A-Z]+$/.test(t) && t.length >= 2 && t.length <= 4) {
      return { token: t, type: "instrument_code", isTag: true, mask: m };
    }
    const d = (t.match(/[0-9]/g) || []).length;
    const isAlpha = /^[A-Z]+$/.test(t);
    if (d && !isAlpha && d / t.length >= 0.15) {
      return { token: t, type: "unknown", isTag: true, mask: m };
    }
    return { token: t, type: "unknown", isTag: false, mask: m };
  }

  function isTagCandidate(token) {
    return classify(token).isTag;
  }

  // ============================================================
  // standards/isa.py port
  // ============================================================
  class ISA {
    constructor(data) {
      this.firstLetterKeys = new Set(Object.keys(data.first_letter));
      this.firstModifierKeys = new Set(Object.keys(data.first_letter_modifier));
      this.readoutKeys = new Set(Object.keys(data.succeeding_readout_passive));
      this.outputKeys = new Set(Object.keys(data.succeeding_output_active));
      this.commonTagsKeys = new Set(Object.keys(data.common_tags));
      this.succeeding = new Set([...this.readoutKeys, ...this.outputKeys]);
      this.usersChoice = new Set(
        Object.entries(data.first_letter)
          .filter(([, v]) => v === "User's Choice")
          .map(([k]) => k)
      );
    }
    isKnownTag(code) {
      return this.commonTagsKeys.has(code);
    }
    validInstrumentCode(code) {
      if (!code || !/^[A-Za-z]+$/.test(code) || code.length < 1 || code.length > 5) return false;
      if (!this.firstLetterKeys.has(code[0])) return false;
      let body = code.slice(1);
      const suffixes = ["HH", "LL", "H", "L", "M", "C", "D", "O"];
      for (const suf of suffixes) {
        if (body.endsWith(suf) && body.length > suf.length) {
          body = body.slice(0, body.length - suf.length);
          break;
        }
      }
      if (body.length > 0 && this.firstModifierKeys.has(body[0])) body = body.slice(1);
      for (const c of body) {
        if (!(this.succeeding.has(c) || this.usersChoice.has(c))) return false;
      }
      return true;
    }
  }

  const INSTR_RE = /^(?<prefix>\d+-)?(?<letters>[A-Z]{1,5})-?(?<loop>\d{1,6})(?<suffix>[A-Z])?$/;

  function parseInstrument(token, isa) {
    const m = INSTR_RE.exec((token || "").trim().toUpperCase());
    if (!m) return null;
    const letters = m.groups.letters;
    return {
      raw: token,
      prefix: m.groups.prefix || null,
      letters,
      loop: m.groups.loop,
      suffix: m.groups.suffix || null,
      firstLetter: letters ? letters[0] : "",
      succeeding: letters.slice(1),
      isaValid: isa.validInstrumentCode(letters),
    };
  }

  // ============================================================
  // Ratcliff/Obershelp ratio (difflib.SequenceMatcher(None,a,b).ratio() port)
  // Only used for the rare cross-mask-repair tie-break.
  // ============================================================
  function longestMatch(a, b, alo, ahi, blo, bhi) {
    let bestI = alo,
      bestJ = blo,
      bestSize = 0;
    const b2j = new Map();
    for (let j = blo; j < bhi; j++) {
      const c = b[j];
      if (!b2j.has(c)) b2j.set(c, []);
      b2j.get(c).push(j);
    }
    let j2len = new Map();
    for (let i = alo; i < ahi; i++) {
      const newj2len = new Map();
      const js = b2j.get(a[i]) || [];
      for (const j of js) {
        const k = (j2len.get(j - 1) || 0) + 1;
        newj2len.set(j, k);
        if (k > bestSize) {
          bestI = i - k + 1;
          bestJ = j - k + 1;
          bestSize = k;
        }
      }
      j2len = newj2len;
    }
    return [bestI, bestJ, bestSize];
  }

  function matchingBlocksTotal(a, b) {
    let total = 0;
    const stack = [[0, a.length, 0, b.length]];
    while (stack.length) {
      const [alo, ahi, blo, bhi] = stack.pop();
      const [i, j, k] = longestMatch(a, b, alo, ahi, blo, bhi);
      if (k === 0) continue;
      total += k;
      if (alo < i && blo < j) stack.push([alo, i, blo, j]);
      if (i + k < ahi && j + k < bhi) stack.push([i + k, ahi, j + k, bhi]);
    }
    return total;
  }

  function seqRatio(a, b) {
    if (!a.length && !b.length) return 1.0;
    const matched = matchingBlocksTotal(a, b);
    return (2 * matched) / (a.length + b.length);
  }

  // ============================================================
  // grammar.py port -- HierarchicalGrammar
  // ============================================================
  function cartesianProduct(arrays) {
    let out = [[]];
    for (const arr of arrays) {
      const next = [];
      for (const combo of out) {
        for (const item of arr) {
          next.push([...combo, item]);
        }
      }
      out = next;
    }
    return out;
  }

  function keyOf(vendor, m) {
    return vendor + " " + m;
  }
  function splitKey(key) {
    const idx = key.indexOf(" ");
    return [key.slice(0, idx), key.slice(idx + 1)];
  }

  function confuseSet(grammar, s, maxsub, cap) {
    maxsub = maxsub || 2;
    cap = cap || 1500;
    let out = new Set([s]);
    for (let iter = 0; iter < maxsub; iter++) {
      const added = new Set();
      for (const v of out) {
        for (let i = 0; i < v.length; i++) {
          const ch = v[i];
          const reach = grammar.conf.get(ch) || "";
          for (const a of reach) {
            added.add(v.slice(0, i) + a + v.slice(i + 1));
          }
        }
        if (added.size + out.size > cap) break;
      }
      for (const x of added) out.add(x);
      if (out.size > cap) break;
    }
    return out;
  }

  class HierarchicalGrammar {
    constructor(isa) {
      this.isa = isa;
      this.slots = new Map(); // "vendor mask" -> Array<Set<char>>
      this.vocab = new Map(); // vendor -> Map(tag -> freq)
      this.masksByVendor = new Map(); // vendor -> Set(mask)
      this.conf = new Map(); // char -> string of true chars
      this._vocabAllCache = null;
    }

    static async load(readText, isaData) {
      const isa = new ISA(isaData);
      const g = new HierarchicalGrammar(isa);

      const slotsText = await readText("grammar_slots.csv");
      for (const r of parseCSVObjects(slotsText)) {
        const v = r.vendor,
          m = r.mask,
          i = parseInt(r.slot_index, 10);
        const key = keyOf(v, m);
        if (!g.slots.has(key)) {
          g.slots.set(
            key,
            Array.from({ length: m.length }, () => new Set())
          );
        }
        g.slots.get(key)[i] = new Set(r.allowed_chars.split(""));
        if (!g.masksByVendor.has(v)) g.masksByVendor.set(v, new Set());
        g.masksByVendor.get(v).add(m);
      }

      const vocabText = await readText("grammar_vocab.csv");
      for (const r of parseCSVObjects(vocabText)) {
        if (!g.vocab.has(r.vendor)) g.vocab.set(r.vendor, new Map());
        g.vocab.get(r.vendor).set(r.tag, parseInt(r.freq, 10));
      }

      const confText = await readText("grammar_conf.csv");
      for (const r of parseCSVObjects(confText)) {
        g.conf.set(r.misread_char, r.true_chars);
      }

      g._vocabAllCache = g._computeVocabAll();
      return g;
    }

    get vendors() {
      return Array.from(this.masksByVendor.keys()).sort();
    }

    _computeVocabAll() {
      const out = new Map();
      for (const counter of this.vocab.values()) {
        for (const [tag, freq] of counter) {
          out.set(tag, (out.get(tag) || 0) + freq);
        }
      }
      return out;
    }

    _vocabGet(vendor, tag) {
      const vc = this.vocab.get(vendor);
      return vc ? vc.get(tag) || 0 : 0;
    }

    _validIn(t, vendor) {
      const sl = this.slots.get(keyOf(vendor, mask(t)));
      if (!sl || sl.length !== t.length) return false;
      for (let i = 0; i < t.length; i++) {
        if (!sl[i].has(t[i])) return false;
      }
      return true;
    }

    valid(t, vendor) {
      const vends = vendor ? [vendor] : this.vendors;
      return vends.some((v) => this._validIn(t, v));
    }

    _repairSlots(raw, vendor, maxEdits) {
      maxEdits = maxEdits === undefined ? 3 : maxEdits;
      const sl = this.slots.get(keyOf(vendor, mask(raw)));
      if (!sl || sl.length !== raw.length) return null;
      const bad = [];
      for (let i = 0; i < raw.length; i++) {
        if (!sl[i].has(raw[i])) bad.push(i);
      }
      if (bad.length === 0) return raw;
      if (bad.length > maxEdits) return null;
      const opts = [];
      for (const i of bad) {
        const reach = new Set((this.conf.get(raw[i]) || "").split(""));
        reach.add(raw[i]);
        const ok = [...reach].filter((c) => sl[i].has(c));
        if (ok.length === 0) return null;
        opts.push([i, ok]);
      }
      const cands = new Set();
      for (const pick of cartesianProduct(opts.map((o) => o[1]))) {
        const s = raw.split("");
        opts.forEach(([i], idx) => {
          s[i] = pick[idx];
        });
        cands.add(s.join(""));
      }
      const vall = this._vocabAllCache;
      const hits = [...cands].filter((c) => (vall.get(c) || 0) >= 2);
      if (hits.length === 1) return hits[0];
      if (cands.size === 1) return [...cands][0];
      return null;
    }

    // Classify WHY Never-Fabricate rejected this token, for human-review triage.
    // Diagnostic only -- computed after decode() has already given up, so it never
    // influences confident/layer. Mirrors grammar.py::_reject_reason exactly.
    //   variant_conflict  structure is known (ISA letter form, or an induced
    //                     vendor/project mask) but this instance's characters
    //                     disagree with it and could not be repaired confidently.
    //   truncated         raw's own shape has no support, but it lines up as a
    //                     prefix/suffix of a longer known mask for this vendor --
    //                     suggests the OCR box clipped part of the tag.
    //   sparse            raw's shape has no support at all: no matching vendor
    //                     mask, and no longer mask it could be a fragment of.
    //   unknown           fallback when there is no vendor context to reason with.
    _rejectReason(raw, tt, vends) {
      if (!vends || vends.length === 0) return "unknown";

      if (tt.type === "instrument_tag") {
        const parsed = parseInstrument(raw, this.isa);
        if (parsed && !parsed.isaValid) return "variant_conflict";
      }

      const m = mask(raw);
      if (vends.some((v) => this.slots.has(keyOf(v, m)))) return "variant_conflict";

      for (const v of vends) {
        for (const key of this.slots.keys()) {
          const [vv, gm] = splitKey(key);
          if (vv !== v || gm.length <= m.length) continue;
          if (gm.startsWith(m) || gm.endsWith(m)) return "truncated";
        }
      }

      return "sparse";
    }

    _repairCrossMask(raw, vendor, maxEdits) {
      maxEdits = maxEdits === undefined ? 3 : maxEdits;
      const m = mask(raw);
      const cands = new Set();
      for (const [key, sl] of this.slots) {
        const [v, gm] = splitKey(key);
        if (v !== vendor || gm.length !== raw.length || gm === m) continue;
        const diff = [];
        for (let i = 0; i < gm.length; i++) {
          if (gm[i] !== m[i]) diff.push(i);
        }
        if (diff.length === 0 || diff.length > maxEdits) continue;
        let feasible = true;
        const opts = [];
        for (const i of diff) {
          const reach = new Set((this.conf.get(raw[i]) || "").split(""));
          reach.add(raw[i]);
          const ok = [...reach].filter((c) => sl[i].has(c));
          if (ok.length === 0) {
            feasible = false;
            break;
          }
          opts.push([i, ok]);
        }
        if (!feasible) continue;
        let skip = false;
        for (let i = 0; i < raw.length; i++) {
          if (diff.includes(i)) continue;
          if (!sl[i].has(raw[i])) {
            skip = true;
            break;
          }
        }
        if (skip) continue;
        for (const pick of cartesianProduct(opts.map((o) => o[1]))) {
          const s = raw.split("");
          opts.forEach(([i], idx) => {
            s[i] = pick[idx];
          });
          const cd = s.join("");
          if (mask(cd) === gm) cands.add(cd);
        }
      }
      if (cands.size === 0) return null;
      const vall = this._vocabAllCache;
      const hits = [...cands].filter((c) => (vall.get(c) || 0) >= 1);
      if (hits.length === 1) return hits[0];
      if (cands.size === 1) return [...cands][0];
      let best = null;
      let bestFreq = -1;
      let bestRatio = -1;
      for (const c of cands) {
        const freq = vall.get(c) || 0;
        const ratio = seqRatio(c, raw);
        if (freq > bestFreq || (freq === bestFreq && ratio > bestRatio)) {
          best = c;
          bestFreq = freq;
          bestRatio = ratio;
        }
      }
      return (vall.get(best) || 0) >= 1 ? best : null;
    }

    decode(rawInput, vendor, drawingVocab) {
      const raw = (rawInput || "").trim().toUpperCase();
      const tt = classify(raw);

      // L1: bare instrument codes (pure letters, 2-5 chars)
      if (/^[A-Z]+$/.test(raw) && raw.length >= 2 && raw.length <= 5) {
        if (this.isa.commonTagsKeys.has(raw)) {
          return decoded(raw, raw, "isa", true, "instrument_code", "ISA known");
        }
        for (const alt of confuseSet(this, raw, 2)) {
          if (this.isa.commonTagsKeys.has(alt)) {
            return decoded(raw, alt, "isa", true, "instrument_code", "ISA snap");
          }
        }
        if (this.isa.validInstrumentCode(raw)) {
          return decoded(raw, raw, "isa", true, "instrument_code", "ISA form");
        }
      }

      // L1: instrument tags
      if (tt.type === "instrument_tag") {
        const parsed = parseInstrument(raw, this.isa);
        if (parsed && parsed.isaValid && this.isa.commonTagsKeys.has(parsed.letters)) {
          return decoded(raw, raw, "isa", true, tt.type, "ISA known tag");
        }
        if (parsed) {
          for (const alt of confuseSet(this, parsed.letters, 2)) {
            if (this.isa.commonTagsKeys.has(alt)) {
              const fixed = raw.replace(parsed.letters, alt);
              return decoded(raw, fixed, "isa", true, tt.type, "ISA snap");
            }
          }
        }
      }

      // L4: exact match in this drawing's own repeated tokens
      if (drawingVocab && (drawingVocab.get(raw) || 0) >= 2) {
        return decoded(raw, raw, "drawing", true, tt.type, "drawing repeat");
      }

      // L2/L3: exact vocab hit
      const vends = vendor ? [vendor] : this.vendors;
      for (const v of vends) {
        if (this._vocabGet(v, raw) >= 2) {
          const layer = vendor ? "vendor" : "project";
          return decoded(raw, raw, layer, true, tt.type, "vocab exact");
        }
      }

      // L2/L3: slot-valid as-is
      if (this.valid(raw, vendor)) {
        return decoded(raw, raw, vendor ? "vendor" : "project", true, tt.type, "slot valid");
      }

      // L2/L3: slot repair
      for (const v of vends) {
        const fixed = this._repairSlots(raw, v);
        if (fixed && fixed !== raw) {
          return decoded(raw, fixed, vendor ? "vendor" : "project", true, tt.type, "slot repair");
        }
      }

      // L2/L3: cross-mask repair
      for (const v of vends) {
        const fixed = this._repairCrossMask(raw, v);
        if (fixed && fixed !== raw) {
          return decoded(raw, fixed, vendor ? "vendor" : "project", true, tt.type, "cross-mask repair");
        }
      }

      // L1 fallback: instrument letters that at least follow ISA form
      if (tt.type === "instrument_tag") {
        const parsed = parseInstrument(raw, this.isa);
        if (parsed && parsed.isaValid) {
          return decoded(raw, raw, "isa", true, tt.type, "ISA form ok");
        }
      }

      // Never Fabricate
      const reason = this._rejectReason(raw, tt, vends);
      return decoded(raw, raw, "reject", false, tt.type, "no confident resolution", reason);
    }
  }

  function decoded(raw, decodedVal, layer, confident, tokenType, note, rejectReason) {
    return { raw, decoded: decodedVal, layer, confident, tokenType, note, rejectReason: rejectReason || "" };
  }

  // ============================================================
  // Driver: decode a whole cache file the way validate.py::run() does
  // (operational metrics only -- no gold in the browser flow)
  // ============================================================
  function decodeFile(rows, grammar, vendor) {
    const drawingVocab = new Map();
    for (const row of rows) {
      const raw = (row.raw || "").trim().toUpperCase();
      if (classify(raw).isTag) drawingVocab.set(raw, (drawingVocab.get(raw) || 0) + 1);
    }
    const records = [];
    const layerCount = new Map();
    const typeCount = new Map();
    const rejectReasonCount = new Map();
    rows.forEach((row, rowIndex) => {
      const raw = (row.raw || "").trim().toUpperCase();
      const tt = classify(raw);
      typeCount.set(tt.type, (typeCount.get(tt.type) || 0) + 1);
      if (!tt.isTag) return;
      const d = grammar.decode(raw, vendor, drawingVocab);
      layerCount.set(d.layer, (layerCount.get(d.layer) || 0) + 1);
      if (d.layer === "reject") {
        rejectReasonCount.set(d.rejectReason, (rejectReasonCount.get(d.rejectReason) || 0) + 1);
      }
      records.push({
        rowIndex,
        raw,
        decoded: d.decoded,
        layer: d.layer,
        type: d.tokenType,
        confident: d.confident,
        note: d.note,
        rejectReason: d.rejectReason,
        orig: row,
      });
    });
    return {
      records,
      layerCount,
      typeCount,
      rejectReasonCount,
      nDetections: rows.length,
      nTagCandidates: records.length,
    };
  }

  return {
    parseCSV,
    parseCSVObjects,
    mask,
    classify,
    isTagCandidate,
    ISA,
    parseInstrument,
    seqRatio,
    HierarchicalGrammar,
    decodeFile,
  };
});
