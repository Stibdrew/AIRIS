// ---------------------------------------------------------------------------
// AIRIS — client-side behavior
// Sidebar toggle · account dropdown · hover detail · live readings
// · alert filtering · AQI chart
// ---------------------------------------------------------------------------

(function initSidebar() {
  const menuBtn = document.getElementById('menuBtn');
  const sidebar = document.getElementById('sidebar');
  const scrim = document.getElementById('sidebarScrim');
  const closeBtn = document.getElementById('sidebarClose');
  if (!menuBtn || !sidebar || !scrim) return;

  // Single source of truth for the two independent sidebar states:
  //  - "open"      -> mobile drawer is showing (only meaningful <=860px)
  //  - "collapsed" -> desktop rail is shrunk to icons-only (only >860px)
  // The button reads/writes whichever state applies to the current
  // viewport instead of just toggling a CSS class blindly.
  const MOBILE_QUERY = '(max-width: 860px)';
  const COLLAPSE_KEY = 'airis:sidebarCollapsed';
  const mql = window.matchMedia(MOBILE_QUERY);

  function isMobile() {
    return mql.matches;
  }

  function readStoredCollapsed() {
    try {
      return window.localStorage.getItem(COLLAPSE_KEY) === '1';
    } catch (err) {
      return false;
    }
  }
  function writeStoredCollapsed(collapsed) {
    try {
      window.localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0');
    } catch (err) {
      /* localStorage unavailable (private mode, etc.) — degrade silently */
    }
  }

  function isDrawerOpen() {
    return sidebar.classList.contains('is-open');
  }
  function openDrawer() {
    sidebar.classList.add('is-open');
    scrim.classList.add('is-visible');
    menuBtn.setAttribute('aria-expanded', 'true');
  }
  function closeDrawer() {
    sidebar.classList.remove('is-open');
    scrim.classList.remove('is-visible');
    menuBtn.setAttribute('aria-expanded', 'false');
  }

  function isCollapsed() {
    return sidebar.classList.contains('is-collapsed');
  }
  function setCollapsed(collapsed) {
    sidebar.classList.toggle('is-collapsed', collapsed);
    menuBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  }

  // Restore the desktop rail preference on load.
  if (!isMobile()) {
    setCollapsed(readStoredCollapsed());
  }

  menuBtn.addEventListener('click', () => {
    if (isMobile()) {
      if (isDrawerOpen()) closeDrawer();
      else openDrawer();
    } else {
      const collapsed = !isCollapsed();
      setCollapsed(collapsed);
      writeStoredCollapsed(collapsed);
    }
  });

  scrim.addEventListener('click', closeDrawer);
  if (closeBtn) closeBtn.addEventListener('click', closeDrawer);
  sidebar.querySelectorAll('.nav-item').forEach((item) => {
    item.addEventListener('click', closeDrawer);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isDrawerOpen()) closeDrawer();
  });

  // Keep the two states from bleeding into each other when the viewport
  // crosses the breakpoint (e.g. rotating a tablet, resizing a window).
  function handleViewportChange(e) {
    if (e.matches) {
      // Now mobile: the rail-collapse class doesn't apply here.
      setCollapsed(false);
    } else {
      // Now desktop: drop any open drawer state, restore the rail preference.
      closeDrawer();
      setCollapsed(readStoredCollapsed());
    }
  }
  if (typeof mql.addEventListener === 'function') {
    mql.addEventListener('change', handleViewportChange);
  } else if (typeof mql.addListener === 'function') {
    mql.addListener(handleViewportChange); // Safari <14 fallback
  }
})();

// ---------------------------------------------------------------------------
// Alerts filtering
// ---------------------------------------------------------------------------
(function initAlertFilters() {
  const tabs = document.getElementById('filterTabs');
  const list = document.getElementById('notifList');
  const emptyMsg = document.getElementById('emptyFiltered');
  if (!tabs || !list) return;

  const cards = Array.from(list.querySelectorAll('.notif-card'));

  tabs.addEventListener('click', (e) => {
    const btn = e.target.closest('.filter-tab');
    if (!btn) return;

    tabs.querySelectorAll('.filter-tab').forEach((t) => t.classList.remove('is-active'));
    btn.classList.add('is-active');

    const filter = btn.dataset.filter;
    let visibleCount = 0;

    cards.forEach((card) => {
      const severity = card.dataset.severity;
      const isRead = card.dataset.read === '1';
      let show = true;

      if (filter === 'warning') show = severity === 'warning';
      else if (filter === 'info') show = severity === 'info';
      else if (filter === 'unread') show = !isRead;

      card.hidden = !show;
      if (show) visibleCount += 1;
    });

    if (emptyMsg) emptyMsg.hidden = visibleCount !== 0;
  });
})();

// ---------------------------------------------------------------------------
// Historical — daily AQI bar chart, built from a JSON data attribute so no
// charting library or CDN dependency is required.
// ---------------------------------------------------------------------------
(function initAqiChart() {
  const container = document.getElementById('aqiChart');
  if (!container) return;

  let points = [];
  try {
    points = JSON.parse(container.dataset.points || '[]');
  } catch (err) {
    console.warn('AIRIS: could not parse chart data', err);
    return;
  }

  if (!points.length) {
    container.textContent = 'No data for this month.';
    container.style.alignItems = 'center';
    container.style.justifyContent = 'center';
    container.style.color = 'var(--text-muted)';
    return;
  }

  points.forEach((point) => {
    const bar = document.createElement('div');
    const heightPct = Math.max(4, Math.min(100, point.aqi));
    bar.className = 'aqi-bar';
    if (point.aqi < 40) bar.classList.add('poor');
    else if (point.aqi < 70) bar.classList.add('low');
    bar.style.height = `${heightPct}%`;
    bar.title = `Day ${point.label}: AQI ${point.aqi}`;
    container.appendChild(bar);
  });
})();

// ---------------------------------------------------------------------------
// Account dropdown (header profile icon)
//   click trigger -> toggle · click outside -> close · Escape -> close
//   Focus returns to the trigger on Escape so keyboard users don't get lost.
// ---------------------------------------------------------------------------
(function initAccountMenu() {
  const root = document.getElementById('accountMenu');
  const trigger = document.getElementById('accountTrigger');
  const dropdown = document.getElementById('accountDropdown');
  if (!root || !trigger || !dropdown) return;

  function isOpen() {
    return root.classList.contains('is-open');
  }

  function open() {
    root.classList.add('is-open');
    dropdown.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
  }

  function close(returnFocus) {
    if (!isOpen()) return;
    root.classList.remove('is-open');
    dropdown.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
    if (returnFocus) trigger.focus();
  }

  trigger.addEventListener('click', (e) => {
    e.stopPropagation();
    if (isOpen()) close(false);
    else open();
  });

  // Clicks inside the panel shouldn't bubble up to the document handler and
  // close the menu before the link/button has done its job.
  dropdown.addEventListener('click', (e) => e.stopPropagation());

  // Navigating away or submitting logout closes the menu so it can never be
  // left stuck open behind a page transition.
  dropdown.querySelectorAll('.account-item').forEach((item) => {
    item.addEventListener('click', () => close(false));
  });

  document.addEventListener('click', () => close(false));

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isOpen()) {
      e.stopPropagation();
      close(true);
    }
  });

  // Tabbing out of the menu closes it too.
  document.addEventListener('focusin', (e) => {
    if (isOpen() && !root.contains(e.target)) close(false);
  });
})();


// ---------------------------------------------------------------------------
// Hover detail
//   One floating panel shared by every [data-tip] element. It lives on <body>
//   and is positioned with position:fixed, so it can never be clipped by a
//   scroll container and never pushes the layout around.
// ---------------------------------------------------------------------------
const AirisTooltip = (function initTooltip() {
  let panel = null;
  let current = null;

  function ensurePanel() {
    if (panel) return panel;
    panel = document.createElement('div');
    panel.className = 'airis-tip';
    panel.setAttribute('role', 'tooltip');
    panel.hidden = true;
    document.body.appendChild(panel);
    return panel;
  }

  function render(content) {
    const el = ensurePanel();
    const rows = (content.rows || [])
      .map(
        (row) =>
          `<div class="airis-tip-row${row.muted ? ' is-muted' : ''}">` +
          `<span>${row.label}</span><strong>${row.value}</strong></div>`
      )
      .join('');

    el.innerHTML =
      `<p class="airis-tip-title">${content.title}</p>` +
      (content.subtitle ? `<p class="airis-tip-sub">${content.subtitle}</p>` : '') +
      (rows ? `<div class="airis-tip-rows">${rows}</div>` : '') +
      (content.footer ? `<p class="airis-tip-foot">${content.footer}</p>` : '');
  }

  function place(anchor) {
    const el = ensurePanel();
    const rect = anchor.getBoundingClientRect();
    const box = el.getBoundingClientRect();
    const gap = 10;
    const margin = 8;

    let top = rect.bottom + gap;
    if (top + box.height > window.innerHeight - margin) {
      // Not enough room below — flip above the anchor.
      top = Math.max(margin, rect.top - box.height - gap);
    }

    let left = rect.left + rect.width / 2 - box.width / 2;
    left = Math.max(margin, Math.min(left, window.innerWidth - box.width - margin));

    el.style.top = `${Math.round(top)}px`;
    el.style.left = `${Math.round(left)}px`;
  }

  function show(anchor, content) {
    if (!content) return;
    current = anchor;
    render(content);
    const el = ensurePanel();
    el.hidden = false;
    place(anchor);
    // Fade in on the next frame so the transition actually runs.
    requestAnimationFrame(() => el.classList.add('is-visible'));
  }

  function hide() {
    current = null;
    if (!panel) return;
    panel.classList.remove('is-visible');
    panel.hidden = true;
  }

  function refresh(anchor, content) {
    // Keep an open tooltip in sync when live values land underneath it.
    if (current === anchor && content) {
      render(content);
      place(anchor);
    }
  }

  function anchorEl() {
    return current;
  }

  window.addEventListener('scroll', hide, true);
  window.addEventListener('resize', hide);

  return { show, hide, refresh, anchorEl };
})();


// ---------------------------------------------------------------------------
// Live readings
//   Polls /api/readings and writes the values into whatever the current page
//   is showing (stat cards, restroom cards, live table) plus the hover detail.
//   Server-side is the single source of truth — see sensor_data.py.
// ---------------------------------------------------------------------------
(function initLiveReadings() {
  const statCards = Array.from(document.querySelectorAll('.metric-card[data-metric]'));
  const restroomCards = Array.from(document.querySelectorAll('.restroom-card[data-code]'));
  const liveRows = Array.from(document.querySelectorAll('.live-row[data-code]'));
  if (!statCards.length && !restroomCards.length && !liveRows.length) return;

  const REFRESH_MS = 4000;

  const UNITS = {
    aqi: '',
    temperature: '°C',
    humidity: '%',
    voc: ' ppb',
    co2: ' ppm',
    occupancy: '',
  };
  const LABELS = {
    aqi: 'AQI',
    temperature: 'Temperature',
    humidity: 'Humidity',
    voc: 'VOC',
    co2: 'CO₂',
    occupancy: 'Occupancy',
  };

  let payload = readInitialPayload();

  function readInitialPayload() {
    const node = document.getElementById('readingsPayload');
    if (!node) return null;
    try {
      return JSON.parse(node.textContent);
    } catch (err) {
      console.warn('AIRIS: could not parse initial readings payload', err);
      return null;
    }
  }

  function temp(value) {
    return Number(value).toFixed(1);
  }

  function fmt(metric, value) {
    const shown = metric === 'temperature' ? temp(value) : value;
    return `${shown}${UNITS[metric] || ''}`;
  }

  // --- hover content -------------------------------------------------------

  function statTip(metric) {
    if (!payload) return null;
    const stat = payload.summary[metric];
    if (!stat) return null;

    const rows = payload.restrooms.map((r) => ({
      label: r.name.replace('Restroom ', 'Restroom '),
      value: fmt(metric, r[metric]),
    }));

    rows.push({ label: 'Average', value: fmt(metric, stat.avg), muted: true });
    rows.push({ label: 'Minimum', value: fmt(metric, stat.min), muted: true });
    rows.push({ label: 'Maximum', value: fmt(metric, stat.max), muted: true });
    rows.push({ label: 'Monitored', value: `${stat.count} restrooms`, muted: true });
    if (metric === 'aqi') {
      rows.push({ label: 'Trend', value: stat.trend, muted: true });
    }

    return {
      title: `${LABELS[metric]} — building average`,
      subtitle: `${fmt(metric, stat.avg)} across ${stat.count} restrooms`,
      rows: rows,
      footer: `Simulated readings · updated ${payload.updated_at}`,
    };
  }

  function restroomTip(code) {
    if (!payload) return null;
    const r = payload.restrooms.find((item) => item.code === code);
    if (!r) return null;

    const rows = [
      { label: 'AQI', value: r.aqi },
      { label: 'Temperature', value: `${temp(r.temperature)}°C` },
      {
        label: r.held_field === 'humidity' ? 'Humidity (sensor offline)' : 'Humidity',
        value: `${r.humidity}%`,
        muted: r.held_field === 'humidity',
      },
      { label: 'VOC', value: `${r.voc} ppb` },
      { label: 'CO₂', value: `${r.co2} ppm` },
      { label: 'Occupancy', value: r.occupancy },
      {
        label: `${r.sensor_type} threshold`,
        value: r.threshold_label,
        muted: true,
      },
      { label: 'Last updated', value: r.last_updated, muted: true },
    ];

    return {
      title: `${r.name} — ${r.floor} · ${r.wing}`,
      subtitle: `${r.status === 'warning' ? 'Warning' : 'Normal'} · ${r.condition_note}`,
      rows: rows,
      footer: `${r.sensor_type} sensor ${r.sensor_status.toLowerCase()} · simulated reading`,
    };
  }

  function tipFor(el) {
    if (el.dataset.metric) return statTip(el.dataset.metric);
    if (el.dataset.code) return restroomTip(el.dataset.code);
    return null;
  }

  // --- painting ------------------------------------------------------------

  function setText(scope, field, text) {
    const node = scope.querySelector(`[data-field="${field}"]`);
    if (node && node.textContent !== text) node.textContent = text;
  }

  function paint() {
    if (!payload) return;

    const stamp = document.getElementById('lastUpdated');
    if (stamp) stamp.textContent = payload.updated_at;

    statCards.forEach((card) => {
      const metric = card.dataset.metric;
      const stat = payload.summary[metric];
      if (!stat) return;
      setText(card, 'value', metric === 'temperature' ? temp(stat.avg) : String(stat.avg));
      if (metric === 'aqi') {
        setText(card, 'hint', stat.trend);
        card.classList.toggle('tone-warning', stat.avg < 60);
        card.classList.toggle('tone-neutral', stat.avg >= 60);
      }
    });

    restroomCards.forEach((card) => {
      const r = payload.restrooms.find((item) => item.code === card.dataset.code);
      if (!r) return;

      card.className = card.className.replace(/status-\w+/, `status-${r.status}`);
      setText(card, 'aqi', String(r.aqi));
      setText(card, 'temperature', `${temp(r.temperature)}°C`);
      setText(card, 'humidity', `${r.humidity}%`);
      setText(card, 'voc', `${r.voc} ppb`);
      setText(card, 'co2', `${r.co2} ppm`);
      setText(card, 'occupancy', String(r.occupancy));
      setText(
        card,
        'occupancy-line',
        `${r.occupancy} ${r.occupancy === 1 ? 'person' : 'people'} inside`
      );
      setText(card, 'note', r.condition_note);

      const badge = card.querySelector('[data-field="badge"] .badge');
      if (badge) {
        badge.className = `badge badge-${r.status === 'warning' ? 'warning' : 'normal'}`;
        badge.innerHTML = `<i class="dot"></i>${
          r.status === 'warning' ? 'Warning' : 'Normal'
        }`;
      }

      const threshold = card.querySelector('[data-field="threshold"]');
      if (threshold) {
        threshold.className = `threshold-chip ${r.over_threshold ? 'exceeded' : 'ok'}`;
        threshold.textContent = `${r.over_threshold ? 'Exceeded' : 'Within'} ${
          r.threshold_label
        } threshold`;
      }
    });

    liveRows.forEach((row) => {
      const r = payload.restrooms.find((item) => item.code === row.dataset.code);
      if (!r) return;
      setText(row, 'aqi', String(r.aqi));
      setText(row, 'temperature', `${temp(r.temperature)}°C`);
      setText(row, 'humidity', `${r.humidity}%`);
      setText(row, 'voc', `${r.voc} ppb`);
      setText(row, 'co2', `${r.co2} ppm`);
      setText(row, 'occupancy', String(r.occupancy));
    });

    // If a tooltip is open, refresh its contents in place.
    const open = AirisTooltip.anchorEl();
    if (open) AirisTooltip.refresh(open, tipFor(open));
  }

  // --- hover wiring --------------------------------------------------------

  [].concat(statCards, restroomCards).forEach((el) => {
    el.addEventListener('mouseenter', () => AirisTooltip.show(el, tipFor(el)));
    el.addEventListener('mouseleave', () => AirisTooltip.hide());
    el.addEventListener('focus', () => AirisTooltip.show(el, tipFor(el)));
    el.addEventListener('blur', () => AirisTooltip.hide());
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') AirisTooltip.hide();
  });

  // --- polling -------------------------------------------------------------

  let timer = null;

  async function poll() {
    try {
      const res = await fetch('/api/readings', {
        headers: { 'X-Requested-With': 'fetch' },
        credentials: 'same-origin',
      });
      if (res.status === 401) {
        // Session ended (logged out, or expired in another tab). Stop polling
        // and let the server send us to the login page.
        clearInterval(timer);
        window.location.href = '/login';
        return;
      }
      if (!res.ok) return; // transient server hiccup — hold the last values
      payload = await res.json();
      paint();
    } catch (err) {
      /* transient network issue — keep showing the last known values */
    }
  }

  paint();
  timer = setInterval(poll, REFRESH_MS);
})();
