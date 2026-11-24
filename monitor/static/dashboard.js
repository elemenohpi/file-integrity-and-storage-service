// dashboard.js -- course staff file, do not modify.
//
// Polls /api/state and redraws every chart in place. No external network
// calls -- everything (including Chart.js) is served from this container.

(function () {
  "use strict";

  const NODE_NAMES = ["gateway", "scheduler", "storage", "exec1", "exec2", "exec3"];
  const EXEC_NAMES = ["exec1", "exec2", "exec3"];
  const RUN_MINUTES = 60;   // a sequence is 60 simulated minutes long
  // the charts whose horizontal axis is the simulated time
  const TIME_CHARTS = ["throughput", "latency", "queue", "pending", "fileaccess",
    "comm", "overhead", "cpu", "mem"];

  function load(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function save(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* ignore */ } }

  // ---- colours -------------------------------------------------------------
  // Read again whenever the theme changes, see rebuildCharts().
  let COLORS = {};
  let NODE_COLOR = {};

  function readColors() {
    const css = getComputedStyle(document.documentElement);
    const v = (name) => css.getPropertyValue(name).trim();
    COLORS = {
      s1: v("--series-1"), s2: v("--series-2"), s3: v("--series-3"),
      s4: v("--series-4"), s5: v("--series-5"), s6: v("--series-6"),
      s7: v("--series-7"), s8: v("--series-8"),
      grid: v("--grid"), axis: v("--axis"), ink: v("--text-secondary"),
      muted: v("--text-muted"), surface: v("--surface-1"),
    };
    NODE_COLOR = {
      gateway: COLORS.s1, scheduler: COLORS.s2, storage: COLORS.s3,
      exec1: COLORS.s4, exec2: COLORS.s7, exec3: COLORS.s8,
    };
  }

  // ---- numbers -------------------------------------------------------------
  function fmt(n, digits) {
    if (n === null || n === undefined || Number.isNaN(Number(n))) return "--";
    const d = digits === undefined ? 1 : digits;
    return Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function fmtLoose(n) {   // at most one decimal, none when the number is whole
    if (n === null || n === undefined || Number.isNaN(Number(n))) return "--";
    return Number(n).toLocaleString("en-US", { maximumFractionDigits: 1 });
  }
  function esc(text) {
    return String(text === null || text === undefined ? "" : text)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ---- axes and options ----------------------------------------------------
  function timeAxis() {
    return {
      type: "linear", min: 0, max: RUN_MINUTES,
      ticks: { color: COLORS.muted, stepSize: 5, includeBounds: false, maxRotation: 0 },
      grid: { color: COLORS.grid }, border: { color: COLORS.axis },
      title: { display: true, text: "simulated minute", color: COLORS.ink },
    };
  }
  function categoryAxis() {
    return {
      ticks: { color: COLORS.muted }, grid: { display: false }, border: { color: COLORS.axis },
    };
  }
  // whole: the values are counts, so the axis has no fractions.
  function valueAxis(title, whole, max) {
    const axis = {
      type: "linear", beginAtZero: true,
      ticks: { color: COLORS.muted }, grid: { color: COLORS.grid }, border: { color: COLORS.axis },
      title: { display: true, text: title, color: COLORS.ink },
    };
    if (whole) axis.ticks.precision = 0;
    if (max !== undefined) axis.max = max;
    return axis;
  }

  // title: shown above a chart that has no legend.
  function chartOptions(xAxis, yAxis, title) {
    const overTime = xAxis.type === "linear";
    return {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: !title, labels: { color: COLORS.ink, boxWidth: 10, boxHeight: 10 } },
        title: { display: !!title, text: title || "", color: COLORS.ink,
          font: { size: 12, weight: "normal" }, padding: { top: 4, bottom: 10 } },
        tooltip: {
          mode: "index", intersect: false,
          callbacks: {
            title: (items) => {
              if (!items.length) return "";
              return overTime ? "minute " + fmt(items[0].parsed.x, 1) : items[0].label;
            },
            label: (item) => {
              // the value as it was given: a log scale has no place for zero
              const y = (item.raw !== null && typeof item.raw === "object") ? item.raw.y : item.raw;
              return (item.dataset.label || "") + ": " + fmtLoose(y);
            },
          },
        },
      },
      scales: { x: xAxis, y: yAxis },
    };
  }

  function lineDataset(label, color, extra) {
    return Object.assign({
      label, data: [], borderColor: color, backgroundColor: color,
      borderWidth: 2, pointRadius: 0, tension: 0.15, spanGaps: true,
    }, extra || {});
  }

  // ---- the start of each hostile event, drawn on the time charts -----------
  let markers = [];   // {n, x}: the number of the event and its start in simulated minutes
  let showMarkers = load("fis-markers") !== "off";

  function drawMarkers(chart, labels) {
    if (!showMarkers || !markers.length) return;
    const x = chart.scales.x, area = chart.chartArea, ctx = chart.ctx;
    ctx.save();
    ctx.font = "10px system-ui, -apple-system, 'Segoe UI', sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    let lastPx = -100, row = 0;
    markers.forEach((m) => {
      if (m.x < x.min || m.x > x.max) return;
      const px = x.getPixelForValue(m.x);
      if (!labels) {
        ctx.strokeStyle = COLORS.muted;
        ctx.globalAlpha = 0.75;
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(px, area.top);
        ctx.lineTo(px, area.bottom);
        ctx.stroke();
        return;
      }
      // numbers of events that start close together go on separate rows
      row = (px - lastPx < 14) ? (row + 1) % 3 : 0;
      lastPx = px;
      const text = String(m.n);
      const w = ctx.measureText(text).width + 4;
      const top = area.top + 1 + row * 12;
      ctx.fillStyle = COLORS.surface;
      ctx.fillRect(px - w / 2, top, w, 11);
      ctx.fillStyle = COLORS.ink;
      ctx.fillText(text, px, top + 1);
    });
    ctx.restore();
  }

  const markerPlugin = {
    id: "eventMarkers",
    beforeDatasetsDraw(chart) { drawMarkers(chart, false); },
    afterDatasetsDraw(chart) { drawMarkers(chart, true); },
  };

  // ---- log scale -----------------------------------------------------------
  let logOn = {};
  try { logOn = JSON.parse(load("fis-log") || "{}") || {}; } catch (e) { logOn = {}; }

  // On a log scale only 1, 2 and 5 times a power of ten get a label, so that
  // the labels do not run into each other.
  // The lines of a log axis: 1, 2 and 5 times each power of ten. An axis that
  // covers many powers of ten keeps only the powers, and one that covers less
  // than a power of ten gets every whole step.
  function logTicks(axis) {
    const lo = axis.min, hi = axis.max;
    if (!(lo > 0) || !(hi > lo)) return;
    const make = (leads) => {
      const out = [];
      for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++) {
        leads.forEach((k) => {
          const v = Number((k * Math.pow(10, e)).toPrecision(3));
          if (v >= lo * (1 - 1e-9) && v <= hi * (1 + 1e-9)) out.push({ value: v });
        });
      }
      return out;
    };
    let ticks = make([1, 2, 5]);
    if (ticks.length > 9) ticks = make([1]);
    if (ticks.length < 3) ticks = make([1, 2, 3, 4, 5, 6, 7, 8, 9]);
    if (ticks.length >= 3) axis.ticks = ticks;
  }
  function logTickLabel(value) {
    return Number(value).toLocaleString("en-US", { maximumSignificantDigits: 3 });
  }

  function setScaleType(chart, name) {
    const y = chart.options.scales.y;
    const on = !!logOn[name];
    y.type = on ? "logarithmic" : "linear";
    y.beginAtZero = !on;
    y.afterBuildTicks = on ? logTicks : undefined;
    y.ticks.autoSkip = !on;
    y.ticks.callback = on ? logTickLabel : Chart.Ticks.formatters.numeric;
  }

  function initLogButtons() {
    document.querySelectorAll("button[data-log]").forEach((btn) => {
      const names = btn.dataset.log.split(" ");
      const show = () => btn.setAttribute("aria-pressed", logOn[names[0]] ? "true" : "false");
      show();
      btn.addEventListener("click", () => {
        const on = !logOn[names[0]];
        names.forEach((name) => {
          logOn[name] = on;
          if (charts[name]) { setScaleType(charts[name], name); charts[name].update(); }
        });
        save("fis-log", JSON.stringify(logOn));
        show();
      });
    });
  }

  // ---- charts --------------------------------------------------------------
  const charts = {};

  function mkChart(name, type, datasets, options, labels) {
    const el = document.getElementById("chart-" + name);
    const data = { datasets };
    if (labels) data.labels = labels;
    const plugins = TIME_CHARTS.indexOf(name) >= 0 ? [markerPlugin] : [];
    charts[name] = new Chart(el.getContext("2d"), { type, data, options, plugins });
    setScaleType(charts[name], name);
    if (logOn[name]) charts[name].update();
  }

  function initCharts() {
    const nodeBars = (label) => [{ label, data: [0, 0, 0],
      backgroundColor: EXEC_NAMES.map((n) => NODE_COLOR[n]) }];
    const nodeLines = () => NODE_NAMES.map((n) => lineDataset(n, NODE_COLOR[n]));

    mkChart("throughput", "line",
      [lineDataset("jobs completed per simulated minute", COLORS.s1)],
      chartOptions(timeAxis(), valueAxis("jobs / minute")));

    mkChart("latency", "line", [
      lineDataset("p50 latency (ms)", COLORS.s1),
      lineDataset("p95 latency (ms)", COLORS.s8),
      lineDataset("mean wait in queue (ms)", COLORS.s4),
      lineDataset("mean run time (ms)", COLORS.s3),
    ], chartOptions(timeAxis(), valueAxis("ms")));

    mkChart("queue", "line", [
      lineDataset("queue length (max)", COLORS.s8),
      lineDataset("queue length (mean)", COLORS.s1),
    ], chartOptions(timeAxis(), valueAxis("jobs waiting")));

    mkChart("pending", "line",
      [lineDataset("jobs pending", COLORS.s7)],
      chartOptions(timeAxis(), valueAxis("jobs", true)));

    mkChart("pernode", "bar", nodeBars("jobs started"),
      chartOptions(categoryAxis(), valueAxis("jobs", true), "jobs started on each node (whole run)"),
      EXEC_NAMES);

    mkChart("fileaccess", "line", [
      lineDataset("upload p50 (ms)", COLORS.s1),
      lineDataset("upload p95 (ms)", COLORS.s2),
      lineDataset("request p50 (ms)", COLORS.s3),
      lineDataset("request p95 (ms)", COLORS.s4),
    ], chartOptions(timeAxis(), valueAxis("ms")));

    mkChart("comm", "line", [
      lineDataset("storage op mean (ms)", COLORS.s7),
      lineDataset("call rtt mean (ms)", COLORS.s5),
    ], chartOptions(timeAxis(), valueAxis("ms")));

    mkChart("overhead", "line",
      [lineDataset("network bytes / payload byte", COLORS.s2)],
      chartOptions(timeAxis(), valueAxis("ratio")));

    mkChart("cpu", "line", nodeLines(), chartOptions(timeAxis(), valueAxis("CPU %")));
    mkChart("mem", "line", nodeLines(), chartOptions(timeAxis(), valueAxis("MB")));

    mkChart("work", "bar", nodeBars("/work usage %"),
      chartOptions(categoryAxis(), valueAxis("%", false, 100), "/work usage now (%)"),
      EXEC_NAMES);

    mkChart("fairness", "bar",
      [{ label: "mean latency (ms)", data: [], backgroundColor: COLORS.s1 }],
      chartOptions(categoryAxis(), valueAxis("ms")), []);

    mkChart("compare", "line", [
      lineDataset("this run", COLORS.s1, { pointRadius: 3, tension: 0 }),
      lineDataset("earlier run", COLORS.s8, { pointRadius: 3, tension: 0 }),
    ], chartOptions(timeAxis(), valueAxis("")));
  }

  // ---- help texts behind the "?" buttons --------------------------------
  // Each text says what is measured and where it comes from.
  const WINDOW_NOTE = "Each point covers the two simulated minutes before it. " +
    "A point is added every 20 simulated seconds.";
  const LATENCY_NOTE = "Job latency is the time from fis submit until the monitor " +
    "sees the status done.";
  const LOG_NOTE = "Log scale: every step up the vertical axis is ten times the " +
    "step below it, so that small and large values can be read on the same " +
    "chart. A value of zero is drawn at the bottom.";

  const HELP = {
    topbar:
      "sequence: the sequence being played (SEQUENCE in .env).\n" +
      "speed: simulated seconds per real second (SPEED in .env).\n" +
      "sim time: simulated minutes since the sequence started.\n" +
      "events: events of the sequence played so far, out of all its events.\n" +
      "running / finished: finished means every event was played and every job " +
      "is done or lost. The clock then stops.",
    overview:
      "Totals of the whole run so far. Hover over or tap the ? of a tile for its " +
      "meaning. Every delay on this page is in simulated milliseconds.",
    throughput:
      "Jobs completed per simulated minute.\n" +
      "Latency: p50 and p95 job latency of the jobs that finished in the window. " +
      LATENCY_NOTE + " Mean wait in queue: from the submission of a job until the " +
      "scheduler gives it to an execution node. Mean run time: how long the " +
      "execution node spent on a job. Wait and run time come from the log of the " +
      "scheduler.\n" + WINDOW_NOTE + "\n" + LOG_NOTE,
    queue:
      "Queue length: the number of jobs waiting in the queue of the scheduler, the highest " +
      "and the mean value. The scheduler records the length of the queue every " +
      "time a job is submitted or started. " + WINDOW_NOTE + "\n" +
      "Jobs pending: the jobs that were submitted and are not yet done or lost, " +
      "at the time of the point. The monitor counts them.\n" +
      "Jobs started on each node: how many jobs each execution node has started " +
      "since the run began, from the log of the scheduler.",
    fileaccess:
      "Upload and request: how long fis upload and fis request take for the people of the " +
      "sequence, the median (p50) and p95, measured by the monitor around the " +
      "client.\n" +
      "Storage op and call rtt: the mean time the storage node needed for one operation (PUT, GET " +
      "or DEL), and the mean time of a call from one node to another, from " +
      "sending the request until the reply arrives. A call includes the work of " +
      "the node that answers. Both come from the logs of the nodes.\n" + WINDOW_NOTE +
      "\n" + LOG_NOTE,
    overhead:
      "All bytes that the six nodes sent and received over the network, divided by " +
      "the bytes of file contents that the people of the sequence uploaded and " +
      "requested in the same window. The network bytes come from Docker, the " +
      "file bytes from the monitor.\n" + WINDOW_NOTE + "\n" + LOG_NOTE,
    resources:
      "CPU %: CPU use of each node, in percent of one CPU. Each node may use " +
      "at most one CPU.\n" +
      "MB: memory use of each node. Each node may use at most 256 MB.\n" +
      "/work usage %: how full the work disk /work of each execution node is now, in " +
      "percent of its 64 MB.\n" +
      "The values come from Docker. " + WINDOW_NOTE,
    nodes:
      "Every node of the service as Docker sees it now.\n" +
      "Status: running, or the state Docker reports when the node is not running.\n" +
      "Restarts: how often Docker restarted the node since the run started.\n" +
      "Dot: green running, yellow running after at least one restart, red not running.\n" +
      "CPU %, Mem (MB) and /work %: the latest measurement.",
    fairness:
      "The mean job latency of each person in the sequence, over all of their " +
      "completed jobs so far. " + LATENCY_NOTE + "\n" + LOG_NOTE,
    hostile:
      "One row for each hostile event of the sequence. A row is written when the " +
      "monitor has judged the outcome, which for some events is a few simulated " +
      "minutes after the event.\n" +
      "#: the number of the row. The charts over time show a dashed line with " +
      "this number where the event started.\n" +
      "Started: the simulated minute in which the event started.\n" +
      "Judged: the simulated minute in which the outcome was recorded.\n" +
      "Outcome: succeeded when the event achieved what it tried to do, blocked " +
      "when the system stopped it, error when the monitor could not carry it out " +
      "or judge it.\n" +
      "Evidence: what the monitor saw that led to the outcome.",
    downloads:
      "The files of the current run, also saved in runs/.\n" +
      "checkpoints.csv: one row every five simulated minutes.\n" +
      "jobs.csv: one row for each job.\n" +
      "hostile.csv: one row for each hostile event.\n" +
      "summary.json: the totals of the run.",
    compare:
      "One measurement of this run at every checkpoint (every five simulated " +
      "minutes), and the same measurement of an earlier run that you choose " +
      "from runs/. A checkpoint covers the five simulated minutes before it; " +
      "the totals and jobs pending are the values at the checkpoint. The values " +
      "come from the checkpoints.csv of both runs. Only compare runs made at " +
      "the same speed.\n" + LOG_NOTE,
  };

  const TILES = [
    { label: "Jobs submitted", unit: "", value: (s) => fmt(s.totals.jobs_submitted, 0),
      help: "Jobs the monitor has submitted since the run started. The monitor " +
        "submits every job with fis submit, as one of the people of the sequence." },
    { label: "Jobs completed", unit: "", value: (s) => fmt(s.totals.jobs_completed, 0),
      help: "Jobs that reached the status done, and whose result the monitor then read." },
    { label: "Jobs lost", unit: "", value: (s) => fmt(s.totals.jobs_lost, 0),
      tone: (s) => (s.totals.jobs_lost > 0 ? "bad" : ""),
      help: "Jobs that were not done ten simulated minutes after they were " +
        "submitted. The monitor stops waiting for them. The number is red when " +
        "it is above zero." },
    { label: "Accuracy", unit: "%", value: (s) => fmt(s.totals.accuracy_pct, 1),
      tone: (s) => (s.totals.accuracy_pct !== null && s.totals.accuracy_pct !== undefined &&
        s.totals.accuracy_pct < 100 ? "bad" : ""),
      help: "The share of the output lines of completed jobs that are equal to the " +
        "line a correct system gives. Each line is one verdict, for example " +
        "\"report.txt: intact\". Ambiguous verdicts are left out. The number is " +
        "red when it is below 100." },
    { label: "Ambiguous verdicts", unit: "", value: (s) => fmt(s.totals.verdicts_ambiguous || 0, 0),
      help: "Output lines of a check whose file was uploaded again or changed in the " +
        "library while the job was waiting or running. More than one answer can be " +
        "right for them, so they are left out of the accuracy." },
    { label: "Latency p50", unit: "ms", value: (s) => fmt(s.totals.latency_p50_ms, 0),
      help: "The median job latency: half of the completed jobs took at most this " +
        "long. " + LATENCY_NOTE + " It moves in steps of about 2,000 ms, because the " +
        "monitor asks for the status every two simulated seconds." },
    { label: "Latency p95", unit: "ms", value: (s) => fmt(s.totals.latency_p95_ms, 0),
      help: "95 of 100 completed jobs took at most this long, and the slowest 5 of " +
        "100 took longer. " + LATENCY_NOTE },
    { label: "Sim time", unit: "min", value: (s) => fmt(s.sim_minutes, 1),
      help: "Simulated minutes since the sequence started. With SPEED=10, one " +
        "simulated minute takes six real seconds." },
  ];

  // The tiles are built once and only their values change afterwards, so that
  // an open help text is not removed by the next poll.
  let tileValues = null;

  function renderTiles(state) {
    const el = document.getElementById("tiles");
    if (!tileValues) {
      el.innerHTML = TILES.map((t) =>
        `<div class="tile"><div class="label"><span>${t.label}</span>` +
        `<button class="help" type="button" data-help="${esc(t.help)}"` +
        ` aria-label="What ${esc(t.label)} means">?</button></div>` +
        `<div class="value"><span class="num"></span><span class="unit">${t.unit}</span></div></div>`
      ).join("");
      tileValues = Array.from(el.querySelectorAll(".tile .num"));
    }
    TILES.forEach((t, i) => {
      tileValues[i].textContent = t.value(state);
      tileValues[i].parentElement.className = "value " + (t.tone ? t.tone(state) : "");
    });
  }

  // ---- the help tooltip ---------------------------------------------------
  // One tooltip for every "?" button. It opens on hover and on keyboard focus,
  // and a click or a tap keeps it open until the next click or Escape.
  function initHelp() {
    document.querySelectorAll(".help[data-help-key]").forEach((b) => {
      b.dataset.help = HELP[b.dataset.helpKey] || "";
    });

    const tip = document.createElement("div");
    tip.id = "help-tip";
    tip.setAttribute("role", "tooltip");
    tip.hidden = true;
    document.body.appendChild(tip);

    let current = null;
    let pinned = false;

    function place(btn) {
      const r = btn.getBoundingClientRect();
      const w = tip.offsetWidth, h = tip.offsetHeight;
      const left = Math.max(8, Math.min(r.left + r.width / 2 - w / 2, window.innerWidth - w - 8));
      let top = r.bottom + 8;
      if (top + h > window.innerHeight - 8) top = r.top - h - 8;
      tip.style.left = left + "px";
      tip.style.top = Math.max(8, top) + "px";
    }
    function show(btn) {
      if (current && current !== btn) hide();
      current = btn;
      tip.textContent = btn.dataset.help || "";
      tip.hidden = false;
      btn.setAttribute("aria-describedby", "help-tip");
      btn.setAttribute("aria-expanded", "true");
      place(btn);
    }
    function hide() {
      if (current) {
        current.removeAttribute("aria-describedby");
        current.setAttribute("aria-expanded", "false");
      }
      current = null;
      pinned = false;
      tip.hidden = true;
    }

    document.addEventListener("mouseover", (e) => {
      const b = e.target.closest(".help");
      if (b && !pinned) show(b);
    });
    document.addEventListener("mouseout", (e) => {
      const b = e.target.closest(".help");
      if (b && b === current && !pinned && !b.contains(e.relatedTarget)) hide();
    });
    document.addEventListener("focusin", (e) => {
      const b = e.target.closest(".help");
      if (b && b !== current) show(b);
    });
    document.addEventListener("focusout", (e) => {
      const b = e.target.closest(".help");
      if (b && b === current) hide();
    });
    document.addEventListener("click", (e) => {
      const b = e.target.closest(".help");
      if (b) {
        if (b === current && pinned) { hide(); return; }
        show(b);
        pinned = true;
        return;
      }
      if (pinned) hide();
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
    window.addEventListener("scroll", () => { if (current) place(current); }, true);
    window.addEventListener("resize", () => { if (current) place(current); });
  }

  // ---- drawing one state ---------------------------------------------------
  function meanOfDict(d, key) {
    if (!d) return null;
    const vals = Object.values(d).map((v) => v[key]).filter((v) => v !== null && v !== undefined);
    if (!vals.length) return null;
    return vals.reduce((a, b) => a + b, 0) / vals.length;
  }

  // The time charts end at minute 60, or later when the run takes longer.
  function timeAxisEnd(lastMinute) {
    return Math.max(RUN_MINUTES, Math.ceil(lastMinute || 0));
  }

  function updateLine(name, ts, getters) {
    const chart = charts[name];
    getters.forEach((get, i) => {
      chart.data.datasets[i].data = ts.map((p) => {
        const y = get(p);
        return { x: p.t_min, y: (y === undefined ? null : y) };
      });
    });
    chart.options.scales.x.max = timeAxisEnd(ts.length ? ts[ts.length - 1].t_min : 0);
    chart.update();
  }

  function updateBars(name, labels, values) {
    const chart = charts[name];
    chart.data.labels = labels;
    chart.data.datasets[0].data = values;
    chart.update();
  }

  function renderCharts(state) {
    const ts = state.timeseries || [];

    updateLine("throughput", ts, [(p) => p.throughput_per_min]);
    updateLine("latency", ts, [
      (p) => p.latency_p50, (p) => p.latency_p95,
      (p) => p.queue_wait_mean, (p) => p.run_time_mean,
    ]);
    updateLine("queue", ts, [(p) => p.queue_len_max, (p) => p.queue_len_mean]);
    updateLine("pending", ts, [(p) => p.jobs_pending]);
    updateLine("fileaccess", ts, [
      (p) => p.upload_p50, (p) => p.upload_p95,
      (p) => p.request_p50, (p) => p.request_p95,
    ]);
    updateLine("comm", ts, [
      (p) => meanOfDict(p.storage_by_op, "mean"),
      (p) => meanOfDict(p.call_by_dest, "mean"),
    ]);
    updateLine("overhead", ts, [(p) => p.overhead_ratio]);
    updateLine("cpu", ts, NODE_NAMES.map((n) => (p) => (p.cpu || {})[n]));
    updateLine("mem", ts, NODE_NAMES.map((n) => (p) => (p.mem_mb || {})[n]));

    const started = state.per_node_total || {};
    updateBars("pernode", EXEC_NAMES, EXEC_NAMES.map((n) => started[n] || 0));

    const last = ts[ts.length - 1];
    const wp = (last && last.work_pct) || {};
    updateBars("work", EXEC_NAMES, EXEC_NAMES.map((n) => wp[n] || 0));

    const people = Object.entries(state.fairness || {}).sort((a, b) => a[0].localeCompare(b[0]));
    updateBars("fairness", people.map((e) => e[0]), people.map((e) => e[1]));
  }

  function renderNodeTable(state) {
    const tbody = document.querySelector("#table-nodes tbody");
    const nodes = state.nodes || {};
    const names = NODE_NAMES.filter((n) => n in nodes)
      .concat(Object.keys(nodes).filter((n) => NODE_NAMES.indexOf(n) < 0).sort());
    const rows = names.map((name) => {
      const n = nodes[name];
      let dotClass = "unknown";
      if (n.status === "running") dotClass = "good";
      else if (n.status) dotClass = "critical";
      if ((n.restarts || 0) > 0 && dotClass === "good") dotClass = "warning";
      return `<tr>
        <td><span class="status-dot ${dotClass}"></span>${esc(name)}</td>
        <td>${esc(n.status || "--")}</td>
        <td>${n.restarts || 0}</td>
        <td>${n.cpu_pct !== undefined && n.cpu_pct !== null ? fmt(n.cpu_pct, 1) : "--"}</td>
        <td>${n.mem_used ? fmt(n.mem_used / (1024 * 1024), 1) : "--"}</td>
        <td>${n.work_pct !== undefined && n.work_pct !== null ? fmt(n.work_pct, 0) : "--"}</td>
      </tr>`;
    });
    tbody.innerHTML = rows.join("");
  }

  // The table is only rebuilt when a row was added, so that text selected in
  // it stays selected.
  let hostileRows = -1;

  function renderHostile(state) {
    const section = document.getElementById("section-hostile");
    const events = state.hostile || [];
    if (!state.has_hostile) { section.style.display = "none"; markers = []; return; }
    section.style.display = "";

    markers = [];
    events.forEach((h, i) => {
      const t = Number(h.t_event);
      if (h.t_event !== null && h.t_event !== undefined && h.t_event !== "" && !Number.isNaN(t)) {
        markers.push({ n: i + 1, x: t / 60 });
      }
    });
    markers.sort((a, b) => a.x - b.x);

    if (events.length === hostileRows) return;
    hostileRows = events.length;
    const minute = (v, perMinute) =>
      (v === null || v === undefined || v === "" ? "--" : fmt(Number(v) / perMinute, 1));
    document.querySelector("#table-hostile tbody").innerHTML = events.map((h, i) => {
      const outcomeClass = "outcome-" + String(h.outcome || "").replace(/[^a-z]/g, "-");
      return `<tr>
        <td>${i + 1}</td>
        <td>${minute(h.t_event, 60)}</td>
        <td>${minute(h.t_sim, 60000)}</td>
        <td>${esc(h.kind)}</td>
        <td>${esc(h.description)}</td>
        <td class="${outcomeClass}">${esc(h.outcome)}</td>
        <td>${esc(h.evidence)}</td>
      </tr>`;
    }).join("");
  }

  function renderTopbar(state) {
    const startupBanner = document.getElementById("startup-banner");
    if (state.startup_ok === false) {
      startupBanner.style.display = "";
      startupBanner.textContent = state.startup_message || "the gateway never answered at start-up";
    } else {
      startupBanner.style.display = "none";
    }
    document.getElementById("pill-sequence").textContent = "sequence: " + state.sequence;
    document.getElementById("pill-speed").textContent = "speed: " + state.speed + "x";
    document.getElementById("pill-time").textContent = "sim time: " + fmt(state.sim_minutes, 1) + " min";
    document.getElementById("pill-progress").textContent =
      "events: " + state.sequence_progress.fired + " / " + state.sequence_progress.total;
    const pillState = document.getElementById("pill-state");
    if (state.finished) {
      pillState.textContent = "finished";
      pillState.className = "pill state-finished";
    } else {
      pillState.textContent = "running";
      pillState.className = "pill state-running";
    }
  }

  let lastState = null;

  function renderAll(state) {
    renderTopbar(state);
    renderTiles(state);
    renderHostile(state);   // before the charts: it sets the event markers
    renderCharts(state);
    renderNodeTable(state);
  }

  let polls = 0;
  let compareIsFinal = false;

  async function poll() {
    try {
      const resp = await fetch("/api/state", { cache: "no-store" });
      const state = await resp.json();
      lastState = state;
      renderAll(state);
      // a new checkpoint is written every five simulated minutes
      polls += 1;
      if (!compareIsFinal && polls % 10 === 0) {
        compareIsFinal = !!state.finished;
        loadCompare();
      }
    } catch (e) {
      // keep the dashboard alive even if one poll fails
      console.error("poll failed", e);
    } finally {
      setTimeout(poll, 1500);
    }
  }

  // ---- theme ---------------------------------------------------------------
  function currentTheme() {
    const chosen = document.documentElement.getAttribute("data-theme");
    if (chosen) return chosen;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark" : "light";
  }

  // The charts take their colours from the theme, so they are built again
  // when it changes.
  function rebuildCharts() {
    readColors();
    Object.keys(charts).forEach((name) => { charts[name].destroy(); delete charts[name]; });
    initCharts();
    if (lastState) renderCharts(lastState);
    renderCompare();
  }

  function initTheme() {
    const saved = load("fis-theme");
    if (saved) document.documentElement.setAttribute("data-theme", saved);
    document.getElementById("theme-toggle").addEventListener("click", () => {
      const next = currentTheme() === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      save("fis-theme", next);
      rebuildCharts();
    });
    if (window.matchMedia) {
      const media = window.matchMedia("(prefers-color-scheme: dark)");
      const onChange = () => {
        if (!document.documentElement.getAttribute("data-theme")) rebuildCharts();
      };
      if (media.addEventListener) media.addEventListener("change", onChange);
    }
  }

  function initMarkersToggle() {
    const box = document.getElementById("markers-toggle");
    box.checked = showMarkers;
    box.addEventListener("change", () => {
      showMarkers = box.checked;
      save("fis-markers", showMarkers ? "on" : "off");
      TIME_CHARTS.forEach((name) => { if (charts[name]) charts[name].update(); });
    });
  }

  // ---- compare with an earlier run --------------------------------------
  // The measurements of checkpoints.csv that can be compared: [column, label].
  const COMPARE_METRICS = [
    ["job_latency_p95_ms", "p95 job latency (ms)"],
    ["job_latency_p50_ms", "p50 job latency (ms)"],
    ["job_latency_mean_ms", "mean job latency (ms)"],
    ["queue_wait_mean_ms", "mean wait in queue (ms)"],
    ["run_time_mean_ms", "mean run time (ms)"],
    ["throughput_jobs_per_sim_minute", "jobs completed per simulated minute"],
    ["queue_len_max", "highest queue length"],
    ["jobs_pending", "jobs pending"],
    ["jobs_completed_total", "jobs completed (total so far)"],
    ["jobs_lost_total", "jobs lost (total so far)"],
    ["verdict_accuracy_pct", "accuracy (%)"],
    ["upload_latency_p95_ms", "p95 upload time (ms)"],
    ["request_latency_p95_ms", "p95 request time (ms)"],
    ["storage_time_mean_ms", "mean storage operation (ms)"],
    ["call_rtt_mean_ms", "mean call between nodes (ms)"],
    ["overhead_ratio_window", "network bytes per payload byte"],
  ];

  const compare = { mine: [], theirs: [], other: "" };

  function parseCsv(text) {
    const lines = text.split("\n").map((l) => l.replace(/\r$/, "")).filter((l) => l.trim().length);
    if (!lines.length) return [];
    const header = lines[0].split(",");
    return lines.slice(1).map((line) => {
      const cells = line.split(",");
      const row = {};
      header.forEach((h, i) => { row[h] = cells[i]; });
      return row;
    });
  }

  function renderCompare() {
    const chart = charts.compare;
    const metricSelect = document.getElementById("compare-metric");
    if (!chart || !metricSelect.value) return;
    const column = metricSelect.value;
    const label = (COMPARE_METRICS.find((m) => m[0] === column) || ["", ""])[1];
    const points = (rows) => rows
      .map((r) => {
        const cell = r[column];
        const y = (cell === undefined || cell === "") ? null : Number(cell);
        return { x: Number(r.sim_minute), y: Number.isNaN(y) ? null : y };
      })
      .filter((p) => !Number.isNaN(p.x));
    const mine = points(compare.mine), theirs = points(compare.theirs);
    chart.data.datasets[0].data = mine;
    chart.data.datasets[1].data = theirs;
    chart.data.datasets[1].label = compare.other || "earlier run (none chosen)";
    chart.options.scales.y.title.text = label;
    chart.options.scales.x.max = timeAxisEnd(Math.max(0, ...mine.concat(theirs).map((p) => p.x)));
    chart.update();
  }

  async function loadCompare() {
    const other = document.getElementById("compare-select").value;
    const rows = (url) => fetch(url, { cache: "no-store" })
      .then((r) => (r.ok ? r.text() : "")).then(parseCsv);
    try {
      const [mine, theirs] = await Promise.all([
        rows("/download/checkpoints.csv"),
        other ? rows("/runs/" + encodeURIComponent(other) + "/checkpoints.csv") : Promise.resolve([]),
      ]);
      compare.mine = mine;
      compare.theirs = theirs;
      compare.other = other;
      renderCompare();
    } catch (e) {
      console.error("compare failed", e);
    }
  }

  async function initCompare() {
    const metricSelect = document.getElementById("compare-metric");
    COMPARE_METRICS.forEach(([column, label]) => {
      const opt = document.createElement("option");
      opt.value = column; opt.textContent = label;
      metricSelect.appendChild(opt);
    });
    const savedMetric = load("fis-compare-metric");
    if (savedMetric && COMPARE_METRICS.some((m) => m[0] === savedMetric)) metricSelect.value = savedMetric;
    metricSelect.addEventListener("change", () => {
      save("fis-compare-metric", metricSelect.value);
      renderCompare();
    });

    const runSelect = document.getElementById("compare-select");
    runSelect.addEventListener("change", loadCompare);
    try {
      const data = await (await fetch("/api/runs", { cache: "no-store" })).json();
      (data.runs || []).filter((name) => name !== data.current).forEach((name) => {
        const opt = document.createElement("option");
        opt.value = name; opt.textContent = name;
        runSelect.appendChild(opt);
      });
    } catch (e) { /* no other runs available yet */ }
    loadCompare();
  }

  initTheme();        // first: the colours below depend on the theme
  readColors();
  initHelp();
  initCharts();
  initLogButtons();
  initMarkersToggle();
  initCompare();
  poll();
})();
