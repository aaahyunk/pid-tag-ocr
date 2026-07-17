// pid_tag_ocr Control Room -- static, no backend. All state lives in these
// module-level JS variables only; no localStorage/sessionStorage is used
// anywhere in this file.
(function () {
  "use strict";

  // ---- in-memory app state ----
  let grammar = null;
  let rows = []; // parsed original CSV rows (objects with x,y,w,h,rot,conf,raw)
  let vendor = null;
  let currentFileName = null;
  let decodeResult = null; // {records, layerCount, typeCount, nDetections, nTagCandidates}
  let review = new Map(); // rowIndex -> { value, reviewed } for tag-candidate rows
  let queueOrder = []; // rowIndex list of records needing review, original order
  let queuePos = 0;
  let currentFilter = "all";

  // ---- DOM refs ----
  const $ = (id) => document.getElementById(id);
  const fileInput = $("fileInput");
  const downloadBtn = $("downloadBtn");
  const vendorBadge = $("vendorBadge");
  const fileNameBadge = $("fileNameBadge");
  const emptyState = $("emptyState");
  const loadStatus = $("loadStatus");
  const dashboard = $("dashboard");
  const reviewBanner = $("reviewBanner");
  const reviewBannerText = $("reviewBannerText");
  const openQueueBtn = $("openQueueBtn");
  const tableSection = $("tableSection");
  const resultTableBody = $("resultTableBody");
  const queueOverlay = $("queueOverlay");
  const queueBody = $("queueBody");
  const queueDone = $("queueDone");
  const queueFill = $("queueFill");
  const queueCount = $("queueCount");
  const queueChip = $("queueChip");
  const queueRaw = $("queueRaw");
  const queueInput = $("queueInput");
  const approveBtn = $("approveBtn");
  const closeQueueBtn = $("closeQueueBtn");
  const closeQueueBtn2 = $("closeQueueBtn2");

  // ---- boot: load grammar data over fetch (relative paths -> GitHub Pages safe) ----
  async function boot() {
    try {
      const readText = (name) =>
        fetch("./data/" + name).then((res) => {
          if (!res.ok) throw new Error(name + ": HTTP " + res.status);
          return res.text();
        });
      const isaData = await fetch("./data/isa_5_1.json").then((res) => res.json());
      grammar = await PidGrammar.HierarchicalGrammar.load(readText, isaData);
      loadStatus.textContent = `문법 데이터 로드 완료 · 벤더 ${grammar.vendors.join(", ")}`;
      fileInput.disabled = false;
    } catch (err) {
      loadStatus.textContent = "문법 데이터 로드 실패: " + err.message;
      console.error(err);
    }
  }

  fileInput.addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    if (file) handleFile(file);
  });

  function handleFile(file) {
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result);
      rows = PidGrammar.parseCSVObjects(text);
      vendor = /^V\d{2}/.test(file.name) ? file.name.slice(0, 3) : null;
      currentFileName = file.name;
      runDecode();
    };
    reader.onerror = () => {
      alert("파일을 읽지 못했습니다: " + file.name);
    };
    reader.readAsText(file);
  }

  function runDecode() {
    decodeResult = PidGrammar.decodeFile(rows, grammar, vendor);
    review = new Map();
    for (const rec of decodeResult.records) {
      review.set(rec.rowIndex, { value: rec.decoded, reviewed: rec.confident });
    }
    queueOrder = decodeResult.records.filter((r) => !r.confident).map((r) => r.rowIndex);
    queuePos = 0;

    vendorBadge.hidden = false;
    vendorBadge.textContent = vendor ? "VENDOR " + vendor : "VENDOR 미지정 (전체 탐색)";
    fileNameBadge.hidden = false;
    fileNameBadge.textContent = currentFileName;
    fileNameBadge.title = currentFileName;
    emptyState.hidden = true;
    dashboard.hidden = false;
    tableSection.hidden = false;
    downloadBtn.disabled = false;

    renderDashboard();
    renderTable();
  }

  // ---- dashboard ----
  function currentStats() {
    const total = decodeResult.nTagCandidates;
    let autoCount = 0;
    for (const v of review.values()) if (v.reviewed) autoCount++;
    const autoRate = total ? autoCount / total : 0;
    const reviewRate = total ? 1 - autoRate : 0;
    return { total, autoCount, autoRate, reviewRate };
  }

  function renderDashboard() {
    const { total, autoCount, autoRate, reviewRate } = currentStats();
    const lc = decodeResult.layerCount;

    $("autoDial").style.setProperty("--pct", (autoRate * 100).toFixed(1));
    $("autoRateNum").textContent = (autoRate * 100).toFixed(1) + "%";
    $("reviewRateNum").textContent = (reviewRate * 100).toFixed(1) + "%";
    $("reviewCountSub").textContent = `${total - autoCount} / ${total}건`;
    $("totalTagsNum").textContent = String(total);
    $("totalDetSub").textContent = `detections ${decodeResult.nDetections}`;

    const isa = lc.get("isa") || 0;
    const vend = lc.get("vendor") || 0;
    const proj = lc.get("project") || 0;
    const draw = lc.get("drawing") || 0;
    const rej = lc.get("reject") || 0;
    $("lampIsa").textContent = String(isa);
    $("lampVendor").textContent = String(vend);
    $("lampProject").textContent = String(proj);
    $("lampDrawing").textContent = String(draw);
    $("lampReject").textContent = String(rej);
    document.querySelectorAll(".lamp").forEach((el) => {
      const layer = el.dataset.layer;
      const count = lc.get(layer) || 0;
      el.classList.toggle("lit", count > 0);
    });

    const remaining = queueOrder.length - reviewedInQueueCount();
    reviewBanner.hidden = false;
    reviewBanner.classList.toggle("clear", remaining === 0);
    reviewBannerText.textContent =
      remaining === 0 ? "검토 필요 항목 없음 — 전부 처리 완료" : `검토 필요 ${remaining}건`;
    openQueueBtn.disabled = remaining === 0;
  }

  function reviewedInQueueCount() {
    let n = 0;
    for (const idx of queueOrder) if (review.get(idx).reviewed) n++;
    return n;
  }

  // ---- table ----
  function renderTable() {
    resultTableBody.innerHTML = "";
    const frag = document.createDocumentFragment();
    for (const rec of decodeResult.records) {
      const st = review.get(rec.rowIndex);
      const isAuto = st.reviewed;
      if (currentFilter === "auto" && !isAuto) continue;
      if (currentFilter === "review" && isAuto) continue;

      const tr = document.createElement("tr");
      tr.className = isAuto ? "s-auto" : "s-review";

      const tdStatus = document.createElement("td");
      const chip = document.createElement("span");
      chip.className = "chip " + (isAuto ? "green" : "red");
      chip.textContent = isAuto ? "자동 확정" : "검토 필요";
      tdStatus.appendChild(chip);

      const tdRaw = document.createElement("td");
      tdRaw.textContent = rec.raw;

      const tdDecoded = document.createElement("td");
      tdDecoded.textContent = st.value;
      tdDecoded.className = "decoded-cell" + (st.value !== rec.raw ? " changed" : "");

      const tdType = document.createElement("td");
      tdType.textContent = rec.type;

      const tdLayer = document.createElement("td");
      tdLayer.textContent = rec.layer.toUpperCase();

      const tdAction = document.createElement("td");
      if (!isAuto) {
        const btn = document.createElement("button");
        btn.className = "mini";
        btn.textContent = "검토";
        btn.addEventListener("click", () => openQueueAt(rec.rowIndex));
        tdAction.appendChild(btn);
      } else {
        tdAction.textContent = "—";
      }

      tr.append(tdStatus, tdRaw, tdDecoded, tdType, tdLayer, tdAction);
      frag.appendChild(tr);
    }
    resultTableBody.appendChild(frag);
  }

  document.querySelectorAll(".filter-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentFilter = btn.dataset.filter;
      renderTable();
    });
  });

  // ---- review queue (Field-Queue interaction) ----
  function openQueueAt(rowIndex) {
    const idx = queueOrder.indexOf(rowIndex);
    queuePos = idx >= 0 ? idx : 0;
    openQueue();
  }

  function openQueue() {
    // resume at the first not-yet-reviewed item
    let start = queueOrder.findIndex((idx) => !review.get(idx).reviewed);
    if (start === -1) start = 0;
    queuePos = queuePos < queueOrder.length && !review.get(queueOrder[queuePos]).reviewed ? queuePos : start;
    queueOverlay.hidden = false;
    renderQueueItem();
  }

  function closeQueue() {
    queueOverlay.hidden = true;
  }

  function renderQueueItem() {
    const remaining = queueOrder.filter((idx) => !review.get(idx).reviewed);
    if (remaining.length === 0) {
      queueBody.hidden = true;
      document.querySelector(".queue-actions").hidden = true;
      queueDone.hidden = false;
      queueFill.style.width = "100%";
      queueCount.textContent = "0건 남음";
      return;
    }
    queueBody.hidden = false;
    document.querySelector(".queue-actions").hidden = false;
    queueDone.hidden = true;

    if (review.get(queueOrder[queuePos]).reviewed) {
      queuePos = queueOrder.indexOf(remaining[0]);
    }
    const rowIndex = queueOrder[queuePos];
    const rec = decodeResult.records.find((r) => r.rowIndex === rowIndex);

    const doneCount = queueOrder.length - remaining.length;
    queueFill.style.width = `${(doneCount / queueOrder.length) * 100}%`;
    queueCount.textContent = `${remaining.length}건 남음 (${doneCount}/${queueOrder.length} 처리)`;
    queueChip.textContent = rec.layer.toUpperCase() + " · NEVER FABRICATE";
    queueRaw.textContent = rec.raw;
    queueInput.value = review.get(rowIndex).value;
    queueInput.focus();
    queueInput.select();
  }

  function approveCurrentAndNext() {
    const remaining = queueOrder.filter((idx) => !review.get(idx).reviewed);
    if (remaining.length === 0) return;
    const rowIndex = queueOrder[queuePos];
    const value = queueInput.value.trim().toUpperCase() || review.get(rowIndex).value;
    review.set(rowIndex, { value, reviewed: true });

    approveBtn.classList.remove("stamp");
    void approveBtn.offsetWidth;
    approveBtn.classList.add("stamp");

    renderDashboard();
    renderTable();

    const stillRemaining = queueOrder.filter((idx) => !review.get(idx).reviewed);
    if (stillRemaining.length === 0) {
      renderQueueItem();
    } else {
      queuePos = queueOrder.indexOf(stillRemaining[0]);
      renderQueueItem();
    }
  }

  openQueueBtn.addEventListener("click", openQueue);
  closeQueueBtn.addEventListener("click", closeQueue);
  closeQueueBtn2.addEventListener("click", closeQueue);
  approveBtn.addEventListener("click", approveCurrentAndNext);
  queueInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      approveCurrentAndNext();
    }
  });
  queueOverlay.addEventListener("click", (e) => {
    if (e.target === queueOverlay) closeQueue();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !queueOverlay.hidden) closeQueue();
  });

  // ---- CSV download: original columns + decoded + layer + status ----
  function csvField(v) {
    const s = v === undefined || v === null ? "" : String(v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }

  function downloadCSV() {
    if (!decodeResult) return;
    const recByRow = new Map(decodeResult.records.map((r) => [r.rowIndex, r]));
    const header = ["x", "y", "w", "h", "rot", "conf", "raw", "decoded", "layer", "status"];
    const lines = [header.join(",")];

    rows.forEach((row, rowIndex) => {
      const rec = recByRow.get(rowIndex);
      let decodedVal, layer, status;
      if (rec) {
        const st = review.get(rowIndex);
        decodedVal = st.value;
        layer = rec.layer;
        status = st.reviewed ? "auto" : "review";
      } else {
        decodedVal = row.raw;
        layer = "n/a";
        status = "auto";
      }
      const out = [row.x, row.y, row.w, row.h, row.rot, row.conf, row.raw, decodedVal, layer, status];
      lines.push(out.map(csvField).join(","));
    });

    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "pid_tags_decoded.csv";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  downloadBtn.addEventListener("click", downloadCSV);

  fileInput.disabled = true;
  boot();
})();
