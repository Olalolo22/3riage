/**
 * 3riage — Contributor Triage Engine Frontend
 * Linear / Raycast style dense keyboard-driven triage dashboard.
 */

(function () {
  'use strict';

  let triageData = null;
  let activeFilter = 'all';
  let searchQuery = '';
  let selectedItem = null;
  let flatItemsList = [];
  let isDemoMode = false;
  let authMode = 'demo';
  let oauthConfigured = false;
  let canForkViaCli = false;
  let loadGeneration = 0;
  let lastModalTrigger = null;
  let externalOnly = false;
  try {
    externalOnly = localStorage.getItem('3riage-external-only') === 'true';
  } catch (e) {}
  // 'contributor' (your PRs, bids, claims) or 'maintainer' (incoming PRs on repos you maintain)
  let currentView = 'contributor';
  let maintainerData = null;
  try {
    if (localStorage.getItem('3riage-view') === 'maintainer') currentView = 'maintainer';
  } catch (e) {}

  // DOM Elements
  const statusUser = document.getElementById('status-user');
  const connectionStatus = document.getElementById('connection-status');
  const countAll = document.getElementById('count-all');
  const countNeedsYou = document.getElementById('count-needs-you');
  const countWaiting = document.getElementById('count-waiting');
  const countIssues = document.getElementById('count-issues');
  const countClaims = document.getElementById('count-claims');
  const searchInput = document.getElementById('search-input');
  const btnThemeToggle = document.getElementById('btn-theme-toggle');
  const btnRefresh = document.getElementById('btn-refresh');
  const btnLogout = document.getElementById('btn-logout');
  const listContainer = document.getElementById('list-container');
  const listTitle = document.getElementById('list-title');
  const listCounter = document.getElementById('list-counter');
  const btnExternalOnly = document.getElementById('btn-external-only');
  const emptyDetail = document.getElementById('empty-detail');
  const detailContent = document.getElementById('detail-content');
  const filterTabs = document.querySelectorAll('.filter-tab');
  const contributorFilters = document.getElementById('view-filters');
  const maintainerFilters = document.getElementById('maintainer-filters');
  const modeButtons = document.querySelectorAll('.mode-btn');
  const mainContent = document.getElementById('main-content');
  const btnBackToList = document.getElementById('btn-back-to-list');
  const demoBanner = document.getElementById('demo-banner');
  const btnBannerConnect = document.getElementById('btn-banner-connect');
  const connectModal = document.getElementById('connect-modal');
  const btnCloseModal = document.getElementById('btn-close-modal');
  const btnModalDismiss = document.getElementById('btn-modal-dismiss');

  const SVG_ICONS = {
    zap: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>',
    clock: '<circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline>',
    checkCircle: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline>',
    issue: '<circle cx="12" cy="12" r="10"></circle><circle cx="12" cy="12" r="2" fill="currentColor"></circle>',
    award: '<circle cx="12" cy="8" r="6"></circle><path d="M15.477 12.89 17 22l-5-3-5 3 1.523-9.11"></path>',
    ban: '<circle cx="12" cy="12" r="10"></circle><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"></line>',
    fork: '<circle cx="12" cy="18" r="3"></circle><circle cx="6" cy="6" r="3"></circle><circle cx="18" cy="6" r="3"></circle><path d="M18 9v2c0 .6-.4 1-1 1H7c-.6 0-1-.4-1-1V9"></path><path d="M12 12v3"></path>',
    check: '<polyline points="20 6 9 17 4 12"></polyline>',
    xCircle: '<circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line>',
    alert: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line>',
    link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path>',
    undo: '<polyline points="9 14 4 9 9 4"></polyline><path d="M20 20v-7a4 4 0 0 0-4-4H4"></path>',
    edit: '<path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>',
    copy: '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>',
    cpu: '<rect x="4" y="4" width="16" height="16" rx="2" ry="2"></rect><rect x="9" y="9" width="6" height="6"></rect><line x1="9" y1="1" x2="9" y2="4"></line><line x1="15" y1="1" x2="15" y2="4"></line><line x1="9" y1="20" x2="9" y2="23"></line><line x1="15" y1="20" x2="15" y2="23"></line><line x1="20" y1="9" x2="23" y2="9"></line><line x1="20" y1="14" x2="23" y2="14"></line><line x1="1" y1="9" x2="4" y2="9"></line><line x1="1" y1="14" x2="4" y2="14"></line>',
  };

  function uiIcon(name, colorClass = '', size = 13) {
    const inner = SVG_ICONS[name];
    if (!inner) return '';
    const cls = colorClass ? `ui-icon ${colorClass}` : 'ui-icon';
    return `<svg class="${cls}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;
  }

  function formatRelativeAge(isoTs, fallbackDays) {
    if (isoTs) {
      const dt = new Date(isoTs);
      if (!Number.isNaN(dt.getTime())) {
        const diffSec = Math.max(0, Math.floor((Date.now() - dt.getTime()) / 1000));
        if (diffSec < 60) return 'just now';
        if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
        if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
        const days = Math.floor(diffSec / 86400);
        if (days < 30) return `${days}d ago`;
        const sameYear = dt.getFullYear() === new Date().getFullYear();
        return dt.toLocaleDateString(undefined, sameYear
          ? { month: 'short', day: 'numeric' }
          : { month: 'short', day: 'numeric', year: 'numeric' });
      }
    }
    if (fallbackDays === null || fallbackDays === undefined) return '';
    if (fallbackDays === 0) return 'today';
    return `${fallbackDays}d ago`;
  }

  function formatDetailTimestamp(isoTs, fallbackDays, emptyLabel = 'None recorded') {
    if (isoTs) {
      const dt = new Date(isoTs);
      if (!Number.isNaN(dt.getTime())) {
        const rel = formatRelativeAge(isoTs, fallbackDays);
        const now = new Date();
        const sameDay =
          dt.getFullYear() === now.getFullYear() &&
          dt.getMonth() === now.getMonth() &&
          dt.getDate() === now.getDate();
        const stamp = sameDay
          ? dt.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
          : dt.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
        const text = rel === stamp ? rel : `${rel} · ${stamp}`;
        return { text, title: dt.toLocaleString() };
      }
    }
    if (fallbackDays !== null && fallbackDays !== undefined) {
      return { text: fallbackDays === 0 ? 'today' : `${fallbackDays}d ago`, title: '' };
    }
    return { text: emptyLabel, title: '' };
  }

  // -------------------------------------------------------------------------
  // Linked issue / CI helpers
  // -------------------------------------------------------------------------

  // Linking only matters on other people's repos (Wave / bounty settlement).
  function isUnlinkedExternal(item) {
    return item && item.has_closing_link === false && !isOwnRepoItem(item);
  }

  function ciLabel(item) {
    if (!item || !item.ci_state) return '';
    const passed = Number(item.ci_passed) || 0;
    const failed = Number(item.ci_failed) || 0;
    const pending = Number(item.ci_pending) || 0;
    const total = Number(item.ci_total) || 0;
    const more = item.ci_partial ? '+' : '';
    if (item.ci_state === 'NONE') return 'No CI';
    if (item.ci_state === 'AWAITING_APPROVAL') return 'Not run yet. May need maintainer approval';
    if (failed > 0) return `${passed}/${total}${more} passing · ${failed} failing`;
    if (pending > 0) return `${passed}/${total}${more} passing · ${pending} running`;
    return `All ${total}${more} passing`;
  }

  function ciColor(item) {
    if (!item || !item.ci_state) return '';
    if (item.ci_state === 'FAILURE') return 'var(--color-red)';
    if (item.ci_state === 'SUCCESS') return 'var(--color-green)';
    if (item.ci_state === 'PENDING' || item.ci_state === 'AWAITING_APPROVAL') return 'var(--color-yellow)';
    return '';
  }

  function linkedIssueLabel(item) {
    if (item.has_closing_link === true) {
      return (item.linked_issues || []).join(', ') || 'Linked';
    }
    if (item.has_closing_link === false) return 'None';
    return 'Unknown';
  }

  function linkCalloutHtml(item) {
    if (!isUnlinkedExternal(item)) return '';
    const base = escapeHtml(item.base_branch || 'another branch');
    const def = escapeHtml(item.default_branch || 'the default branch');
    let headline = 'No linked issue';
    let body = 'Add a closing line to the PR description so GitHub links this PR to its issue and Drips can settle your points.';
    if (item.closing_link_reason === 'non_default_base') {
      headline = 'Closing keyword will not work on this branch';
      body = `This PR targets <code>${base}</code>, not the default branch <code>${def}</code>, so GitHub ignores closing keywords. Ask the maintainer to link the issue manually from the PR's Development section.`;
    } else if (item.closing_link_reason === 'keyword_not_linked') {
      headline = 'Issue mentioned but not linked';
      body = 'Your description has a closing keyword, but GitHub has not linked any issue. Check the issue number and the repo.';
    }

    const suggestions = item.suggested_close_issues || [];
    let snippetHtml = '';
    if (suggestions.length > 0) {
      const lead = item.suggestion_confidence === 'ambiguous'
        ? 'You are assigned to more than one issue here. Pick the one this PR fixes:'
        : 'You are assigned to this issue in the same repo:';
      const buttons = suggestions.map(n => {
        const line = `Closes #${Number(n)}`;
        return `<button type="button" class="btn btn-secondary btn-snippet" data-copy-url="${escapeHtml(line)}" data-copy-msg="Copied: ${escapeHtml(line)}">${uiIcon('copy', '', 12)} ${escapeHtml(line)}</button>`;
      }).join('');
      snippetHtml = `<div class="callout-lead">${lead}</div><div class="callout-actions">${buttons}</div>`;
    }

    return `
      <div class="callout callout-yellow">
        <div class="callout-header">${uiIcon('alert', 'icon-yellow', 13)} ${escapeHtml(headline)}</div>
        <div class="callout-body">${body}</div>
        ${snippetHtml}
      </div>
    `;
  }

  // -------------------------------------------------------------------------
  // Maintainer Mode helpers
  // -------------------------------------------------------------------------

  const MAINT_BUCKET_PILLS = {
    SUSPICIOUS: ['pill-red', 'Suspicious'],
    BOUNCE_BACK: ['pill-yellow', 'Bounce back'],
    REVIEW_NOW: ['pill-green', 'Review now'],
    DRAFTS: ['pill-muted', 'Draft'],
  };

  function toneClass(tone) {
    return { red: 'pill-red', yellow: 'pill-yellow', green: 'pill-green' }[tone] || 'pill-muted';
  }

  function hasReason(item, code) {
    return (item.reasons || []).some(r => r.code === code);
  }

  function formatCount(n) {
    return Number(n || 0).toLocaleString('en-US');
  }

  function incomingWhyLines(item) {
    const who = `@${escapeHtml(item.author)}`;
    const lines = [];
    const notOn = escapeHtml((item.not_assigned_on || []).join(', '));
    const yesOn = escapeHtml((item.assigned_on || []).join(', '));
    if (item.assignment_status === 'not_assigned') {
      lines.push(`${who} was never assigned to ${notOn}.`);
    } else if (item.assignment_status === 'partly_assigned') {
      lines.push(`${who} is assigned to ${yesOn} but not to ${notOn}.`);
    } else if (item.assignment_status === 'unverifiable') {
      lines.push(`There is no linked issue, so you can't check whether ${who} was assigned.`);
    }
    if (item.large_diff) {
      lines.push(`Large change: +${formatCount(item.additions)} / -${formatCount(item.deletions)} across ${formatCount(item.changed_files)} files.`);
    }
    if ((item.sensitive_files || []).length) {
      lines.push('It touches dependency, install or CI files, where risky code usually hides.');
    }
    if (item.is_first_timer) lines.push('This is their first contribution to the repo.');
    if (item.ci_below_threshold) {
      const done = (Number(item.ci_passed) || 0) + (Number(item.ci_failed) || 0);
      lines.push(`Only ${Number(item.ci_passed) || 0} of ${done} finished checks pass. Your bar is 6 of 10.`);
    } else if (item.ci_state === 'AWAITING_APPROVAL') {
      lines.push("CI hasn't run yet. Workflows may be waiting for your approval.");
    }
    if (!lines.length) {
      lines.push(item.bucket === 'DRAFTS'
        ? 'The author marked this as a draft.'
        : `${who} is assigned to ${yesOn}, the issue is linked, and CI looks healthy.`);
    }
    return lines;
  }

  function incomingSuggestedReply(item) {
    if (item.bucket !== 'SUSPICIOUS' && item.bucket !== 'BOUNCE_BACK') return '';
    const asks = [];
    const notAssigned = item.assignment_status === 'not_assigned' || item.assignment_status === 'partly_assigned';
    if (notAssigned) {
      asks.push("This issue isn't assigned to you, so I can't review it yet. Please ask to be assigned on the issue first.");
    }
    if (item.has_closing_link === false) {
      asks.push('Please add `Closes #<issue number>` to the description so this PR links to the issue you were assigned.');
    }
    if (item.ci_below_threshold) {
      asks.push(`${Number(item.ci_failed) || 0} checks are failing. Please get CI passing.`);
    }
    if (!asks.length) return '';
    return `Thanks for the PR! ${asks.join(' ')}${notAssigned ? '' : " I'll review once that's done."}`;
  }

  // -------------------------------------------------------------------------
  // Lifecycle & Fetching
  // -------------------------------------------------------------------------

  function consumeAuthErrorParam() {
    const params = new URLSearchParams(window.location.search);
    const err = params.get('auth_error');
    if (!err) return;

    const messages = {
      access_denied: 'GitHub sign-in was cancelled.',
      invalid_state: 'Sign-in state cookie expired or did not match. Please try again.',
      token_exchange_failed: 'GitHub OAuth token exchange failed — check Client ID, Client Secret, and Callback URL.',
      viewer_lookup_failed: 'Signed in, but could not fetch your GitHub username.',
      oauth_failed: 'Could not complete GitHub sign-in. Please try again.',
      oauth_not_configured: 'GitHub OAuth is not configured on this host yet.',
    };
    showToast(messages[err] || `GitHub auth notice: ${err}`, 9000);

    params.delete('auth_error');
    const nextQs = params.toString();
    const nextUrl = `${window.location.pathname}${nextQs ? '?' + nextQs : ''}${window.location.hash}`;
    window.history.replaceState({}, '', nextUrl);
  }

  let activeFetchController = null;

  async function fetchJsonWithTimeout(url, options = {}, timeoutMs = 20000) {
    const controller = new AbortController();
    activeFetchController = controller;
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetch(url, { ...options, signal: controller.signal });
      const text = await res.text();
      let json = null;
      if (text) {
        try {
          json = JSON.parse(text);
        } catch (_) {
          json = null;
        }
      }
      return { res, json, rawText: text };
    } finally {
      clearTimeout(timer);
      if (activeFetchController === controller) {
        activeFetchController = null;
      }
    }
  }

  async function loadTriage(forceRefresh = false, forceDemo = false) {
    if (activeFetchController) {
      activeFetchController.abort();
      activeFetchController = null;
    }
    const requestGen = ++loadGeneration;
    btnRefresh.classList.add('spinning');
    renderSkeletons();

    try {
      const params = new URLSearchParams(window.location.search);
      const isForcedDemo = forceDemo || params.get('demo') === 'true' || params.get('demo') === '1';
      const qs = new URLSearchParams();
      if (isForcedDemo) qs.set('demo', 'true');
      if (currentView === 'maintainer') qs.set('view', 'maintainer');
      const query = qs.toString() ? `?${qs.toString()}` : '';
      const url = forceRefresh ? `/api/refresh${query}` : `/api/triage${query}`;
      const method = forceRefresh ? 'POST' : 'GET';
      const { res, json } = await fetchJsonWithTimeout(url, { method }, 20000);
      if (requestGen !== loadGeneration) return;

      if (res.status === 401) {
        showToast((json && json.error) || 'GitHub session expired. Showing demo mode.', 6000);
        const fallbackUrl = currentView === 'maintainer' ? '/api/triage?demo=true&view=maintainer' : '/api/triage?demo=true';
        const fallback = await fetchJsonWithTimeout(fallbackUrl, {}, 15000);
        if (requestGen !== loadGeneration) return;
        if (fallback.json && fallback.json.status === 'ok') {
          applyTriageResponse(fallback.json);
          return;
        }
      }

      if (!res.ok) {
        throw new Error((json && json.error) || `Server returned HTTP ${res.status}. Please retry.`);
      }

      if (!json || json.status !== 'ok') {
        throw new Error((json && json.error) || 'Failed to fetch triage data');
      }

      applyTriageResponse(json);
    } catch (err) {
      if (requestGen !== loadGeneration) return;
      const isTimeout = err && err.name === 'AbortError';
      const message = isTimeout
        ? 'Request timed out after 20s waiting on GitHub.'
        : (err && err.message ? err.message : 'Failed to load triage data');
      console.error(err);
      connectionStatus.classList.add('offline');
      statusUser.textContent = isTimeout ? 'Timed out' : 'Error connecting';
      listContainer.innerHTML = `
        <div style="padding: 24px 16px; color: var(--color-red); font-size: 12px; line-height: 1.6;">
          <strong>Error loading triage:</strong><br>${escapeHtml(message)}
          <br><br>
          <span style="color: var(--text-muted);">Try refreshing, or load sample demo data while checking your connection.</span>
          <div style="margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap;">
            <button type="button" class="btn btn-secondary" id="btn-retry-load">Retry</button>
            <button type="button" class="btn btn-secondary" id="btn-load-demo">Open Demo Mode</button>
          </div>
        </div>
      `;
      const retryBtn = document.getElementById('btn-retry-load');
      if (retryBtn) retryBtn.addEventListener('click', () => loadTriage(false, false));
      const demoBtn = document.getElementById('btn-load-demo');
      if (demoBtn) demoBtn.addEventListener('click', () => loadTriage(false, true));
    } finally {
      if (requestGen === loadGeneration) {
        btnRefresh.classList.remove('spinning');
      }
    }
  }

  function activeData() {
    return currentView === 'maintainer' ? maintainerData : triageData;
  }

  function applyTriageResponse(json) {
    if (json.data && json.data.view === 'maintainer') {
      maintainerData = json.data;
    } else {
      triageData = json.data;
    }
    isDemoMode = !!json.is_demo;
    authMode = json.auth_mode || (isDemoMode ? 'demo' : 'env');
    oauthConfigured = !!json.oauth_configured;
    canForkViaCli = !!json.can_fork_via_cli;

    updateHeader();
    renderFeed();

    if (flatItemsList.length > 0) {
      const refreshedMatch = selectedItem
        ? flatItemsList.find(i => getItemId(i) === getItemId(selectedItem))
        : null;
      selectItem(refreshedMatch || flatItemsList[0]);
    } else {
      selectedItem = null;
      renderDetail(null);
    }
  }

  function isOwnRepoItem(item) {
    const data = activeData();
    if (!data || !data.username || !item || !item.repo) return false;
    const owner = item.repo.split('/')[0].toLowerCase();
    return owner === data.username.toLowerCase();
  }

  function getMaintainerCollections() {
    const m = (maintainerData && maintainerData.maintainer) || {};
    const tag = (arr, category) => (arr || []).map(p => ({ ...p, category }));
    return {
      suspicious: tag(m.SUSPICIOUS, 'suspicious'),
      bounce: tag(m.BOUNCE_BACK, 'bounce_back'),
      review: tag(m.REVIEW_NOW, 'review_now'),
      drafts: tag(m.DRAFTS, 'drafts'),
    };
  }

  function applyViewChrome() {
    const isMaint = currentView === 'maintainer';
    modeButtons.forEach(btn => {
      const on = btn.getAttribute('data-view') === currentView;
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    if (contributorFilters) contributorFilters.classList.toggle('hidden', isMaint);
    if (maintainerFilters) maintainerFilters.classList.toggle('hidden', !isMaint);
    if (btnExternalOnly) btnExternalOnly.classList.toggle('hidden', isMaint);
    activeFilter = isMaint ? 'm_all' : 'all';
    filterTabs.forEach(t => t.classList.toggle('active', t.getAttribute('data-filter') === activeFilter));
  }

  function switchView(view) {
    if (view === currentView) return;
    currentView = view;
    try {
      localStorage.setItem('3riage-view', view);
    } catch (e) {}
    applyViewChrome();
    selectedItem = null;
    if (mainContent) mainContent.classList.remove('viewing-detail');
    if (activeData()) {
      updateHeader();
      renderFeed();
      if (flatItemsList.length > 0) selectItem(flatItemsList[0]);
      else renderDetail(null);
    }
    loadTriage(false);
  }

  function getScopedCollections() {
    if (!triageData) {
      return { prsNeedsYou: [], prsWaiting: [], prsFine: [], issues: [], claims: [] };
    }
    const filterFn = item => !externalOnly || !isOwnRepoItem(item);
    return {
      prsNeedsYou: (triageData.prs.NEEDS_YOU || []).filter(filterFn).map(p => ({ ...p, category: 'needs_you' })),
      prsWaiting: (triageData.prs.WAITING_ON_THEM || []).filter(filterFn).map(p => ({ ...p, category: 'waiting' })),
      prsFine: (triageData.prs.PROBABLY_FINE || []).filter(filterFn).map(p => ({ ...p, category: 'probably_fine' })),
      issues: (triageData.unlinked_issues || []).filter(filterFn).map(i => ({ ...i, category: 'issues' })),
      claims: (triageData.claims || []).filter(filterFn).map(c => ({ ...c, category: 'claims' })),
    };
  }

  function updateExternalToggleUI() {
    if (!btnExternalOnly) return;
    btnExternalOnly.classList.toggle('active', externalOnly);
    btnExternalOnly.setAttribute('aria-pressed', externalOnly ? 'true' : 'false');
  }

  function updateHeader() {
    const data = activeData();
    if (!data) return;
    connectionStatus.classList.remove('offline');

    if (demoBanner) {
      demoBanner.style.display = isDemoMode ? 'flex' : 'none';
    }

    if (btnLogout) {
      btnLogout.classList.toggle('hidden', authMode !== 'oauth');
    }

    if (isDemoMode) {
      statusUser.textContent = `@${data.username} (sample)`;
    } else {
      statusUser.textContent = `@${data.username}`;
    }

    if (currentView === 'maintainer') {
      const m = getMaintainerCollections();
      const setCount = (id, n) => {
        const el = document.getElementById(id);
        if (el) el.textContent = n;
      };
      setCount('m-count-all', m.suspicious.length + m.bounce.length + m.review.length + m.drafts.length);
      setCount('m-count-suspicious', m.suspicious.length);
      setCount('m-count-bounce', m.bounce.length);
      setCount('m-count-review', m.review.length);
      setCount('m-count-drafts', m.drafts.length);
      return;
    }

    const scoped = getScopedCollections();
    const totalActive =
      scoped.prsNeedsYou.length +
      scoped.prsWaiting.length +
      scoped.prsFine.length +
      scoped.issues.length +
      scoped.claims.length;
    countAll.textContent = totalActive;
    countNeedsYou.textContent = scoped.prsNeedsYou.length;
    countWaiting.textContent = scoped.prsWaiting.length + scoped.prsFine.length;
    countIssues.textContent = scoped.issues.length;
    countClaims.textContent = scoped.claims.length;
  }

  function renderSkeletons() {
    listContainer.innerHTML = `
      <div class="skeleton-row"></div>
      <div class="skeleton-row"></div>
      <div class="skeleton-row"></div>
      <div class="skeleton-row"></div>
    `;
  }

  // -------------------------------------------------------------------------
  // Filtering & Flattening Data
  // -------------------------------------------------------------------------

  function getItemId(item) {
    return `${item.type}:${item.repo}:${item.number}`;
  }

  function getFilteredItems() {
    if (!activeData()) return [];

    let items = [];
    if (currentView === 'maintainer') {
      const m = getMaintainerCollections();
      const byFilter = {
        m_all: [...m.suspicious, ...m.review, ...m.bounce, ...m.drafts],
        m_suspicious: m.suspicious,
        m_bounce_back: m.bounce,
        m_review_now: m.review,
        m_drafts: m.drafts,
      };
      items = byFilter[activeFilter] || byFilter.m_all;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        items = items.filter(i =>
          i.title.toLowerCase().includes(q) ||
          i.repo.toLowerCase().includes(q) ||
          (i.author || '').toLowerCase().includes(q) ||
          String(i.number).includes(q)
        );
      }
      return items;
    }

    const scoped = getScopedCollections();
    const { prsNeedsYou, prsWaiting, prsFine, issues, claims } = scoped;

    if (activeFilter === 'all') {
      items = [...prsNeedsYou, ...claims, ...prsWaiting, ...prsFine, ...issues];
    } else if (activeFilter === 'needs_you') {
      items = prsNeedsYou;
    } else if (activeFilter === 'waiting') {
      items = [...prsWaiting, ...prsFine];
    } else if (activeFilter === 'issues') {
      items = issues;
    } else if (activeFilter === 'claims') {
      items = claims;
    }

    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      items = items.filter(i =>
        i.title.toLowerCase().includes(q) ||
        i.repo.toLowerCase().includes(q) ||
        String(i.number).includes(q)
      );
    }

    return items;
  }

  // -------------------------------------------------------------------------
  // Feed Rendering
  // -------------------------------------------------------------------------

  function renderFeed() {
    flatItemsList = getFilteredItems();
    listCounter.textContent = `${flatItemsList.length} items`;

    const titles = {
      all: 'All Active Items',
      needs_you: `${uiIcon('zap', 'icon-red', 12)} Needs Your Attention`,
      waiting: `${uiIcon('clock', 'icon-yellow', 12)} Waiting on Others`,
      issues: `${uiIcon('issue', 'icon-cyan', 12)} Unlinked Bids & Issues`,
      claims: `${uiIcon('award', 'icon-purple', 12)} Ready to Claim`,
      m_all: 'Incoming PRs',
      m_suspicious: `${uiIcon('alert', 'icon-red', 12)} Suspicious`,
      m_bounce_back: `${uiIcon('undo', 'icon-yellow', 12)} Bounce Back`,
      m_review_now: `${uiIcon('checkCircle', 'icon-green', 12)} Review Now`,
      m_drafts: `${uiIcon('edit', 'icon-muted', 12)} Drafts`
    };
    listTitle.innerHTML = titles[activeFilter] || 'Triage Feed';

    if (flatItemsList.length === 0) {
      let emptyText = searchQuery ? 'No items match your search filter.' : 'No items in this view.';
      if (!searchQuery && currentView === 'maintainer' && activeFilter === 'm_all') {
        emptyText = 'No open PRs from other people on repos you maintain.<br><span style="font-size: 11px;">3riage checks public repos where you have write access (up to 40, most recently active first).</span>';
      }
      listContainer.innerHTML = `
        <div style="padding: 32px 16px; text-align: center; color: var(--text-muted); font-size: 12px; line-height: 1.6;">
          ${emptyText}
        </div>
      `;
      return;
    }

    let html = '';
    let currentCategory = '';

    flatItemsList.forEach(item => {
      if ((activeFilter === 'all' || activeFilter === 'm_all') && item.category !== currentCategory) {
        currentCategory = item.category;
        const labels = {
          needs_you: `${uiIcon('zap', 'icon-red', 11)} Needs You`,
          waiting: `${uiIcon('clock', 'icon-yellow', 11)} Waiting on Them`,
          probably_fine: `${uiIcon('checkCircle', 'icon-green', 11)} Probably Fine`,
          issues: `${uiIcon('issue', 'icon-cyan', 11)} Unlinked Issues & Bids`,
          claims: `${uiIcon('award', 'icon-purple', 11)} Ready to Claim`,
          suspicious: `${uiIcon('alert', 'icon-red', 11)} Suspicious`,
          review_now: `${uiIcon('checkCircle', 'icon-green', 11)} Review Now`,
          bounce_back: `${uiIcon('undo', 'icon-yellow', 11)} Bounce Back`,
          drafts: `${uiIcon('edit', 'icon-muted', 11)} Drafts`
        };
        html += `<div class="list-section-header">${labels[currentCategory] || escapeHtml(currentCategory)}</div>`;
      }

      const isSelected = selectedItem && getItemId(selectedItem) === getItemId(item);
      const isDimmed = item.is_dimmed || item.bucket === 'PROBABLY_FINE' || item.bucket === 'DRAFTS';

      let pillHtml = '';
      let ageText = '';

      if (item.type === 'pr') {
        if (item.bucket === 'NEEDS_YOU') {
          pillHtml = `<span class="pill pill-red">Needs you</span>`;
        } else if (item.bucket === 'WAITING_ON_THEM') {
          pillHtml = `<span class="pill pill-yellow">Waiting</span>`;
        } else {
          pillHtml = `<span class="pill pill-green">Probably fine</span>`;
        }
        if (item.review_state) {
          pillHtml += ` <span class="pill pill-muted">${escapeHtml(item.review_state)}</span>`;
        }
        if (item.bot_review_actionable) {
          pillHtml += ` <span class="pill pill-red">${uiIcon('cpu', '', 10)} bot review</span>`;
        }
        if (isUnlinkedExternal(item)) {
          pillHtml += ` <span class="pill pill-yellow">No linked issue</span>`;
        }
        if (item.ci_state === 'FAILURE') {
          pillHtml += ` <span class="pill pill-red">CI failing</span>`;
        }
        if (item.their_last_comment_at || item.their_last_comment_days_ago != null) {
          ageText = formatRelativeAge(item.their_last_comment_at, item.their_last_comment_days_ago);
        } else {
          ageText = formatRelativeAge(item.your_activity_at, item.your_activity_days_ago);
        }
      } else if (item.type === 'issue') {
        if (item.role === 'applied') {
          const appCount = item.applicant_count > 1 ? ` · ${item.applicant_count} apps` : '';
          pillHtml = `<span class="pill pill-purple">applied${appCount}</span>`;
        } else if (item.role === 'assignee') {
          pillHtml = `<span class="pill pill-red">assigned</span>`;
        } else if (item.role === 'outbid') {
          pillHtml = `<span class="pill pill-muted">outbid</span>`;
        } else {
          pillHtml = `<span class="pill pill-cyan">${escapeHtml(item.role)}</span>`;
        }
        if (item.forked) {
          pillHtml += ` <span class="pill pill-green">forked</span>`;
        }
        ageText = formatRelativeAge(item.my_last_comment_at, item.days_since_my_comment);
      } else if (item.type === 'incoming_pr') {
        const bucketPill = MAINT_BUCKET_PILLS[item.bucket] || ['pill-muted', item.bucket];
        pillHtml = `<span class="pill ${bucketPill[0]}">${escapeHtml(bucketPill[1])}</span>`;
        pillHtml += ` <span class="pill pill-muted">@${escapeHtml(item.author)}</span>`;
        const flags = (item.reasons || []).filter(r => r.code !== 'assigned');
        flags.slice(0, 3).forEach(r => {
          pillHtml += ` <span class="pill ${toneClass(r.tone)}">${escapeHtml(r.label)}</span>`;
        });
        if (flags.length > 3) pillHtml += ` <span class="pill pill-muted">+${flags.length - 3}</span>`;
        ageText = formatRelativeAge(item.created_at, item.created_days_ago);
      } else if (item.type === 'claim') {
        pillHtml = `<span class="pill pill-purple">ready to claim</span>`;
        if (item.points_at_risk && !isOwnRepoItem(item)) {
          pillHtml += ` <span class="pill pill-red">Points at risk</span>`;
        }
        ageText = formatRelativeAge(item.merged_at, item.merged_days_ago);
      }

      const safeId = escapeHtml(getItemId(item));
      html += `
        <div class="list-row ${isSelected ? 'active' : ''} ${isDimmed ? 'dimmed' : ''}" data-id="${safeId}">
          <div class="row-top">
            <div class="row-repo-badge">
              <span class="row-repo-name">${escapeHtml(item.repo)}</span>
              <span class="row-number">#${Number(item.number)}</span>
            </div>
            <span class="row-age">${escapeHtml(ageText)}</span>
          </div>
          <div class="row-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</div>
          <div class="row-meta">
            ${pillHtml}
          </div>
        </div>
      `;
    });

    listContainer.innerHTML = html;

    listContainer.querySelectorAll('.list-row').forEach(row => {
      row.addEventListener('click', () => {
        const id = row.getAttribute('data-id');
        const item = flatItemsList.find(i => getItemId(i) === id);
        if (item) {
          selectItem(item);
          if (mainContent) {
            mainContent.classList.add('viewing-detail');
          }
        }
      });
    });
  }

  // -------------------------------------------------------------------------
  // Item Selection & Detail Rendering
  // -------------------------------------------------------------------------

  function selectItem(item) {
    selectedItem = item;

    listContainer.querySelectorAll('.list-row').forEach(row => {
      row.classList.toggle('active', row.getAttribute('data-id') === getItemId(item));
    });

    renderDetail(item);
  }

  function renderDetail(item) {
    if (!item) {
      emptyDetail.classList.remove('hidden');
      detailContent.classList.add('hidden');
      return;
    }

    emptyDetail.classList.add('hidden');
    detailContent.classList.remove('hidden');

    if (item.type === 'pr') {
      renderPrDetail(item);
    } else if (item.type === 'issue') {
      renderIssueDetail(item);
    } else if (item.type === 'claim') {
      renderClaimDetail(item);
    } else if (item.type === 'incoming_pr') {
      renderIncomingDetail(item);
    }

    bindCopyButtons();
  }

  function bindCopyButtons() {
    detailContent.querySelectorAll('[data-copy-url]').forEach(btn => {
      btn.addEventListener('click', () => {
        const urlToCopy = btn.getAttribute('data-copy-url') || '';
        const msg = btn.getAttribute('data-copy-msg') || 'URL copied to clipboard';
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(urlToCopy).then(() => showToast(msg)).catch(() => showToast('Copy failed'));
        } else {
          showToast(urlToCopy);
        }
      });
    });
  }

  function renderPrDetail(item) {
    let decisionBorder = 'border-yellow';
    let decisionHeadline = `${uiIcon('clock', 'icon-yellow', 15)} Waiting on Maintainer Review`;
    let decisionSubtext = 'Your activity is newer than theirs. A clean push is awaiting maintainer feedback or merge.';

    if (item.bucket === 'NEEDS_YOU') {
      decisionBorder = 'border-red';
      const botIsTheBlocker = item.bot_review_actionable &&
        (item.review_state !== 'CHANGES_REQUESTED' || item.review_author === item.bot_review_author);
      if (botIsTheBlocker) {
        const bot = escapeHtml(item.bot_review_author || 'review bot');
        decisionHeadline = `${uiIcon('cpu', 'icon-red', 15)} Action Required: Bot Review Feedback`;
        decisionSubtext = item.bot_review_reason === 'review_thread'
          ? `@${bot} left an unresolved review comment after your last push. Address it or reply in the thread.`
          : `@${bot} requested changes after your last push. Treat it like a maintainer review.`;
      } else if (item.review_state === 'CHANGES_REQUESTED') {
        decisionHeadline = `${uiIcon('zap', 'icon-red', 15)} Action Required: Changes Requested`;
        decisionSubtext = `Reviewer @${escapeHtml(item.review_author || 'maintainer')} requested changes. You have not pushed a subsequent commit yet.`;
      } else {
        decisionHeadline = `${uiIcon('zap', 'icon-red', 15)} Action Required: Reviewer Spoke Last`;
        decisionSubtext = `@${escapeHtml(item.their_last_comment_author || 'Maintainer')} left feedback. Ball is in your court to respond or commit.`;
      }
    } else if (item.bucket === 'PROBABLY_FINE') {
      decisionBorder = 'border-green';
      decisionHeadline = `${uiIcon('checkCircle', 'icon-green', 15)} Probably Fine: Approval or Sign-off`;
      decisionSubtext = 'All submitted reviews are approved, or the last comment indicates sign-off (LGTM).';
    }

    const useBotSnippet = item.bot_review_actionable && item.bot_review_body && !item.their_last_comment_body;
    const snippet = useBotSnippet ? item.bot_review_body : (item.their_last_comment_body || item.review_body || '');
    const snippetAuthor = useBotSnippet
      ? item.bot_review_author
      : (item.their_last_comment_author || item.review_author || 'maintainer');
    const snippetAge = useBotSnippet
      ? formatRelativeAge(item.bot_review_at, item.bot_review_days_ago)
      : formatRelativeAge(item.their_last_comment_at, item.their_last_comment_days_ago);
    const theirActivity = formatDetailTimestamp(item.their_activity_at, item.their_activity_days_ago, 'None recorded');
    const yourActivity = formatDetailTimestamp(item.your_activity_at, item.your_activity_days_ago, 'None recorded');
    const itemUrl = safeUrl(item.url);
    const ciText = ciLabel(item);
    const ciStyle = ciColor(item);
    const botHint = item.bot_feedback;
    const botHintAge = botHint ? formatRelativeAge(botHint.at, botHint.days_ago) : '';

    detailContent.innerHTML = `
      <div class="detail-header">
        <div class="detail-breadcrumb">
          <span class="detail-repo-tag">${escapeHtml(item.repo)} #${Number(item.number)}</span>
          <div class="detail-actions">
            <button class="btn btn-secondary" data-copy-url="${escapeHtml(itemUrl)}" data-copy-msg="URL copied to clipboard">Copy Link</button>
            <a href="${escapeHtml(itemUrl)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary">Open PR ↗</a>
          </div>
        </div>
        <h2 class="detail-title">${escapeHtml(item.title)}</h2>
      </div>

      <div class="decision-card ${decisionBorder}">
        <div class="decision-header">${decisionHeadline}</div>
        <div class="decision-subtext">${decisionSubtext}</div>
      </div>

      ${linkCalloutHtml(item)}

      ${snippet ? `
        <div class="detail-section">
          <div class="detail-section-title">Maintainer / Reviewer Snippet</div>
          <div class="feedback-quote">
            <div class="feedback-meta">@${escapeHtml(snippetAuthor)}${snippetAge ? ` (${escapeHtml(snippetAge)})` : ''}:</div>
            "${escapeHtml(snippet)}"
          </div>
        </div>
      ` : ''}

      <div class="detail-section">
        <div class="detail-section-title">Relational State Matrix</div>
        <div class="meta-grid">
          <div class="meta-item">
            <span class="meta-label">Review State</span>
            <span class="meta-value">${item.review_state ? escapeHtml(item.review_state) : 'No formal review'}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Their Last Activity</span>
            <span class="meta-value"${theirActivity.title ? ` title="${escapeHtml(theirActivity.title)}"` : ''}>${escapeHtml(theirActivity.text)}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Your Last Action</span>
            <span class="meta-value"${yourActivity.title ? ` title="${escapeHtml(yourActivity.title)}"` : ''}>${escapeHtml(yourActivity.text)}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Draft Status</span>
            <span class="meta-value">${item.is_draft ? 'Draft PR' : 'Ready for review'}</span>
          </div>
          ${ciText ? `
          <div class="meta-item">
            <span class="meta-label">CI Checks</span>
            <span class="meta-value"${ciStyle ? ` style="color: ${ciStyle};"` : ''}>${escapeHtml(ciText)}</span>
          </div>` : ''}
          ${item.has_closing_link !== undefined ? `
          <div class="meta-item">
            <span class="meta-label">Linked Issue</span>
            <span class="meta-value meta-value-icon"${isUnlinkedExternal(item) ? ' style="color: var(--color-yellow);"' : ''}>${uiIcon('link', '', 12)} ${escapeHtml(linkedIssueLabel(item))}</span>
          </div>` : ''}
        </div>
      </div>

      ${botHint ? `
        <div class="detail-section">
          <div class="detail-section-title">Bot Feedback</div>
          <div class="feedback-quote">
            <div class="feedback-meta">${uiIcon('cpu', '', 11)} @${escapeHtml(botHint.login)}${botHintAge ? ` (${escapeHtml(botHintAge)})` : ''}:</div>
            "${escapeHtml(botHint.body)}"
          </div>
        </div>
      ` : ''}
    `;
  }

  function renderIssueDetail(item) {
    let decisionBorder = 'border-purple';
    let decisionHeadline = `${uiIcon('issue', 'icon-purple', 15)} Bounty Bid / Application Active`;
    let decisionSubtext = `You applied for this issue. There are ${item.applicant_count || 1} competing applicants. Issue is currently unassigned.`;

    if (item.role === 'assignee') {
      decisionBorder = 'border-red';
      decisionHeadline = `${uiIcon('zap', 'icon-red', 15)} Assigned to You: Active Task`;
      decisionSubtext = 'The maintainer officially assigned this issue to you. Fork and submit a PR to complete it.';
    } else if (item.role === 'outbid') {
      decisionBorder = 'border-muted';
      decisionHeadline = `${uiIcon('ban', 'icon-muted', 15)} Bid Closed: Assigned to Competitor`;
      const competitors = (item.applicant_list || []).map(a => `@${escapeHtml(a)}`).join(', ');
      decisionSubtext = `The maintainer assigned this issue to ${competitors || 'another developer'}.`;
    }

    const forkReport = (triageData.fork_report || []).find(f => f.repo.toLowerCase() === item.repo.toLowerCase());
    const needsFork = forkReport ? forkReport.needs_fork : !item.forked;
    const itemUrl = safeUrl(item.url);
    const maintainerAge = formatRelativeAge(item.maintainer_comment_at, item.maintainer_comment_days_ago);
    const myCommentTs = formatDetailTimestamp(item.my_last_comment_at, item.days_since_my_comment, 'None');

    let forkActionHtml = '';
    if (needsFork) {
      if (canForkViaCli || isDemoMode) {
        forkActionHtml = `<button class="btn btn-secondary" id="btn-fork-repo" data-repo="${escapeHtml(item.repo)}">${uiIcon('fork', '', 13)} Fork Repo</button>`;
      } else {
        forkActionHtml = `<a href="${escapeHtml(safeForkUrl(item.repo))}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary">${uiIcon('fork', '', 13)} Fork on GitHub ↗</a>`;
      }
    }

    detailContent.innerHTML = `
      <div class="detail-header">
        <div class="detail-breadcrumb">
          <span class="detail-repo-tag">${escapeHtml(item.repo)} #${Number(item.number)}</span>
          <div class="detail-actions">
            ${forkActionHtml}
            <button class="btn btn-secondary" data-copy-url="${escapeHtml(itemUrl)}" data-copy-msg="Issue URL copied">Copy Link</button>
            <a href="${escapeHtml(itemUrl)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary">Open Issue ↗</a>
          </div>
        </div>
        <h2 class="detail-title">${escapeHtml(item.title)}</h2>
      </div>

      <div class="decision-card ${decisionBorder}">
        <div class="decision-header">${decisionHeadline}</div>
        <div class="decision-subtext">${decisionSubtext}</div>
      </div>

      ${item.maintainer_comment_body ? `
        <div class="detail-section">
          <div class="detail-section-title">Maintainer Guidance (@${escapeHtml(item.maintainer_comment_author)})</div>
          <div class="feedback-quote">
            <div class="feedback-meta">Maintainer${maintainerAge ? ` (${escapeHtml(maintainerAge)})` : ''}:</div>
            "${escapeHtml(item.maintainer_comment_body)}"
          </div>
        </div>
      ` : ''}

      <div class="detail-section">
        <div class="detail-section-title">Issue Pipeline Metadata</div>
        <div class="meta-grid">
          <div class="meta-item">
            <span class="meta-label">Your Role</span>
            <span class="meta-value">${escapeHtml(item.role)}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Competing Applicants</span>
            <span class="meta-value">${item.applicant_count || 1} applicants</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Your Last Comment</span>
            <span class="meta-value"${myCommentTs.title ? ` title="${escapeHtml(myCommentTs.title)}"` : ''}>${escapeHtml(myCommentTs.text)}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Fork Status</span>
            <span class="meta-value meta-value-icon" style="color: ${item.forked ? 'var(--color-green)' : 'var(--color-yellow)'};">
              ${item.forked ? `${uiIcon('check', '', 13)} Already forked` : `${uiIcon('xCircle', '', 13)} Unforked`}
            </span>
          </div>
        </div>
      </div>
    `;

    const btnFork = detailContent.querySelector('#btn-fork-repo');
    if (btnFork) {
      btnFork.addEventListener('click', () => handleFork(item.repo, btnFork));
    }
  }

  function renderClaimDetail(item) {
    const itemUrl = safeUrl(item.url);
    const mergedWhen = formatRelativeAge(item.merged_at, item.merged_days_ago) || 'recently';
    const atRisk = item.points_at_risk && !isOwnRepoItem(item);
    const linkedLine = (item.linked_issues || []).length
      ? `<br>Closes ${escapeHtml(item.linked_issues.join(', '))}`
      : '';

    detailContent.innerHTML = `
      <div class="detail-header">
        <div class="detail-breadcrumb">
          <span class="detail-repo-tag">${escapeHtml(item.repo)} #${Number(item.number)}</span>
          <div class="detail-actions">
            <button class="btn btn-secondary" data-copy-url="${escapeHtml(itemUrl)}" data-copy-msg="PR link copied for Discord!">Copy for Discord</button>
            <a href="${escapeHtml(itemUrl)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary">Open Merged PR ↗</a>
          </div>
        </div>
        <h2 class="detail-title">${escapeHtml(item.title)}</h2>
      </div>

      <div class="decision-card ${atRisk ? 'border-red' : 'border-purple'}">
        <div class="decision-header">${atRisk
          ? `${uiIcon('alert', 'icon-red', 15)} Merged, but Points at Risk`
          : `${uiIcon('award', 'icon-purple', 15)} Merged: Ready to Claim Bounty / Points`}</div>
        <div class="decision-subtext">This pull request merged ${escapeHtml(mergedWhen)}. ${atRisk
          ? `It was not linked to an issue${item.closing_link_reason === 'non_default_base'
              ? ` (it targeted <code>${escapeHtml(item.base_branch || 'another branch')}</code>, where closing keywords are ignored)`
              : ''}, so Drips may not settle points for it automatically. Raise it in the Drips Discord with the PR and issue links.`
          : 'Submit this link in your community Discord or Wave channel to claim rewards.'}</div>
      </div>

      <div class="detail-section">
        <div class="detail-section-title">Claiming Payload</div>
        <div class="feedback-quote" style="font-family: var(--font-mono); font-size: 12px;">
          ${escapeHtml(item.title)}<br>
          ${escapeHtml(itemUrl)}${linkedLine}
        </div>
      </div>
    `;
  }

  function renderIncomingDetail(item) {
    const itemUrl = safeUrl(item.url);
    const cards = {
      SUSPICIOUS: ['border-red', `${uiIcon('alert', 'icon-red', 15)} Check This Before Reading Any Code`],
      BOUNCE_BACK: ['border-yellow', `${uiIcon('undo', 'icon-yellow', 15)} Send It Back: Contributor's Move`],
      REVIEW_NOW: ['border-green', `${uiIcon('checkCircle', 'icon-green', 15)} Ready for Your Review`],
      DRAFTS: ['border-muted', `${uiIcon('edit', 'icon-muted', 15)} Draft: Not Ready Yet`],
    };
    const [border, headline] = cards[item.bucket] || cards.REVIEW_NOW;
    const why = incomingWhyLines(item).join(' ');

    const assignment = {
      assigned: ['var(--color-green)', `Assigned (${(item.assigned_on || []).join(', ')})`],
      partly_assigned: ['var(--color-red)', `Partly: yes on ${(item.assigned_on || []).join(', ')}, no on ${(item.not_assigned_on || []).join(', ')}`],
      not_assigned: ['var(--color-red)', `Not assigned (${(item.not_assigned_on || []).join(', ')})`],
      unverifiable: ['var(--color-yellow)', "Can't verify: no linked issue"],
    }[item.assignment_status] || ['', item.assignment_status || 'Unknown'];

    const blast = `+${formatCount(item.additions)} / -${formatCount(item.deletions)} · ${formatCount(item.changed_files)} file${item.changed_files === 1 ? '' : 's'}`;
    let linkText = linkedIssueLabel(item);
    if (item.has_closing_link === false && item.closing_link_reason === 'non_default_base') {
      linkText = `None (targets ${item.base_branch}, keywords ignored)`;
    }
    const ciText = ciLabel(item) || 'Unknown';
    const ciStyle = item.ci_below_threshold ? 'var(--color-red)' : ciColor(item);
    const opened = formatDetailTimestamp(item.created_at, item.created_days_ago, 'Unknown');
    const assoc = item.is_first_timer
      ? 'First-time contributor'
      : (item.author_association || 'NONE').toLowerCase().replace(/_/g, ' ');
    const reply = incomingSuggestedReply(item);
    const sensitive = item.sensitive_files || [];

    const metaItem = (label, value, color) => `
          <div class="meta-item">
            <span class="meta-label">${label}</span>
            <span class="meta-value"${color ? ` style="color: ${color};"` : ''}>${escapeHtml(value)}</span>
          </div>`;

    detailContent.innerHTML = `
      <div class="detail-header">
        <div class="detail-breadcrumb">
          <span class="detail-repo-tag">${escapeHtml(item.repo)} #${Number(item.number)}</span>
          <div class="detail-actions">
            <button class="btn btn-secondary" data-copy-url="${escapeHtml(itemUrl)}" data-copy-msg="URL copied to clipboard">Copy Link</button>
            <a href="${escapeHtml(itemUrl)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary">Open PR ↗</a>
          </div>
        </div>
        <h2 class="detail-title">${escapeHtml(item.title)}</h2>
      </div>

      <div class="decision-card ${border}">
        <div class="decision-header">${headline}</div>
        <div class="decision-subtext">${why}</div>
      </div>

      <div class="detail-section">
        <div class="detail-section-title">Merge Checklist</div>
        <div class="meta-grid">
          ${metaItem('Assignment', assignment[1], assignment[0])}
          ${metaItem('Blast Radius', blast, item.large_diff ? 'var(--color-red)' : '')}
          ${metaItem('Linked Issue', linkText, item.has_closing_link === false ? 'var(--color-yellow)' : '')}
          ${metaItem('CI Checks', ciText, ciStyle)}
          ${metaItem('Author', `@${item.author} · ${assoc}`, item.is_first_timer ? 'var(--color-yellow)' : '')}
          ${metaItem('Opened', opened.text, '')}
        </div>
      </div>

      ${sensitive.length ? `
        <div class="detail-section">
          <div class="detail-section-title">Sensitive Files Changed</div>
          <div class="feedback-quote sensitive-list">
            ${sensitive.map(p => `<code>${escapeHtml(p)}</code>`).join('')}
            ${item.files_partial ? '<div class="sensitive-note">Only the first 100 changed files were checked.</div>' : ''}
          </div>
        </div>
      ` : ''}

      ${reply ? `
        <div class="detail-section">
          <div class="detail-section-title">Suggested Reply</div>
          <div class="feedback-quote">${escapeHtml(reply)}</div>
          <div>
            <button type="button" class="btn btn-secondary btn-snippet" data-copy-url="${escapeHtml(reply)}" data-copy-msg="Reply copied. Paste it on the PR.">${uiIcon('copy', '', 12)} Copy reply</button>
          </div>
        </div>
      ` : ''}
    `;
  }

  // -------------------------------------------------------------------------
  // Fork Execution (Local CLI or Demo Simulation)
  // -------------------------------------------------------------------------

  async function handleFork(repo, btnElement) {
    if (!isDemoMode && !confirm(`Trigger fork for ${repo} under your GitHub account via local 'gh' CLI?`)) {
      return;
    }

    btnElement.disabled = true;
    btnElement.textContent = 'Forking…';

    try {
      const res = await fetch('/api/fork', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo, demo: isDemoMode })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        showToast(data.message || `Fork initiated for ${repo}`);
        if (!isDemoMode) {
          setTimeout(() => loadTriage(true), 4000);
        }
      } else {
        alert(`Fork error: ${data.error}`);
      }
    } catch (e) {
      alert(`Fork request failed: ${e.message}`);
    } finally {
      btnElement.disabled = false;
      btnElement.innerHTML = `${uiIcon('fork', '', 13)} Fork Repo`;
    }
  }

  // -------------------------------------------------------------------------
  // Auth / Modal Actions
  // -------------------------------------------------------------------------

  function handleConnectClick() {
    if (oauthConfigured) {
      window.location.href = '/api/auth/login';
      return;
    }
    openConnectModal();
  }

  function getModalFocusableElements() {
    if (!connectModal) return [];
    return Array.from(
      connectModal.querySelectorAll(
        'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )
    ).filter(el => el.offsetParent !== null);
  }

  function openConnectModal() {
    if (!connectModal) return;
    lastModalTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    connectModal.classList.remove('hidden');
    const focusables = getModalFocusableElements();
    if (focusables.length > 0) {
      focusables[0].focus();
    }
  }

  function closeConnectModal() {
    if (!connectModal) return;
    connectModal.classList.add('hidden');
    if (lastModalTrigger && typeof lastModalTrigger.focus === 'function') {
      lastModalTrigger.focus();
    }
    lastModalTrigger = null;
  }

  async function handleLogout() {
    try {
      const res = await fetch('/api/auth/logout', { method: 'POST' });
      if (!res.ok) {
        let errMsg = `Sign out failed (${res.status})`;
        try {
          const errJson = await res.json();
          if (errJson && errJson.error) errMsg = errJson.error;
        } catch (_) {}
        throw new Error(errMsg);
      }

      loadGeneration++;
      triageData = null;
      maintainerData = null;
      selectedItem = null;
      flatItemsList = [];
      if (listContainer) listContainer.innerHTML = '';
      if (listCounter) listCounter.textContent = '0 items';
      if (detailContent) {
        detailContent.innerHTML = '';
        detailContent.classList.add('hidden');
      }
      if (emptyDetail) emptyDetail.classList.remove('hidden');
      if (btnLogout) btnLogout.classList.add('hidden');
      if (mainContent) mainContent.classList.remove('viewing-detail');

      showToast('Signed out of GitHub');
      await loadTriage(false);
    } catch (e) {
      showToast(`Sign out failed: ${e.message}`);
    }
  }

  // -------------------------------------------------------------------------
  // Helpers & Toast
  // -------------------------------------------------------------------------

  function showToast(msg, durationMs = 3000) {
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = msg;
    document.body.appendChild(toast);

    setTimeout(() => toast.remove(), durationMs);
  }

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function safeUrl(url) {
    if (!url || typeof url !== 'string') return '#';
    try {
      const parsed = new URL(url, window.location.origin);
      if (parsed.protocol === 'https:' || parsed.protocol === 'http:') {
        return parsed.href;
      }
    } catch (e) {}
    return '#';
  }

  function safeForkUrl(repo) {
    if (!repo || !repo.includes('/')) return 'https://github.com/';
    const parts = repo.split('/');
    return `https://github.com/${encodeURIComponent(parts[0])}/${encodeURIComponent(parts[1])}/fork`;
  }

  // -------------------------------------------------------------------------
  // Keyboard Navigation
  // -------------------------------------------------------------------------

  window.addEventListener('keydown', e => {
    if (connectModal && !connectModal.classList.contains('hidden')) {
      if (e.key === 'Escape') {
        e.preventDefault();
        closeConnectModal();
        return;
      }
      if (e.key === 'Tab') {
        const focusables = getModalFocusableElements();
        if (focusables.length === 0) {
          e.preventDefault();
          return;
        }
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && (document.activeElement === first || !connectModal.contains(document.activeElement))) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && (document.activeElement === last || !connectModal.contains(document.activeElement))) {
          e.preventDefault();
          first.focus();
        }
        return;
      }
      return;
    }

    if (e.key === '/' && document.activeElement !== searchInput) {
      e.preventDefault();
      searchInput.focus();
      return;
    }

    if (e.key === 'Escape' && document.activeElement === searchInput) {
      searchInput.value = '';
      searchQuery = '';
      searchInput.blur();
      renderFeed();
      return;
    }

    if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
      return;
    }

    if (['ArrowDown', 'j', 'J'].includes(e.key)) {
      e.preventDefault();
      moveSelection(1);
    } else if (['ArrowUp', 'k', 'K'].includes(e.key)) {
      e.preventDefault();
      moveSelection(-1);
    } else if (['t', 'T'].includes(e.key)) {
      e.preventDefault();
      toggleTheme();
    } else if (e.key === 'Enter') {
      if (selectedItem && selectedItem.url) {
        const target = safeUrl(selectedItem.url);
        if (target !== '#') {
          window.open(target, '_blank', 'noopener,noreferrer');
        }
      }
    }
  });

  function toggleTheme() {
    const isLight = document.documentElement.getAttribute('data-theme') === 'light';
    const nextTheme = isLight ? 'dark' : 'light';
    if (nextTheme === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    try {
      localStorage.setItem('3riage-theme', nextTheme);
    } catch (e) {}
  }

  function moveSelection(delta) {
    if (flatItemsList.length === 0) return;
    const currentIndex = selectedItem
      ? flatItemsList.findIndex(i => getItemId(i) === getItemId(selectedItem))
      : -1;

    let nextIndex = currentIndex + delta;
    if (nextIndex < 0) nextIndex = 0;
    if (nextIndex >= flatItemsList.length) nextIndex = flatItemsList.length - 1;

    selectItem(flatItemsList[nextIndex]);

    const activeRow = listContainer.querySelector(`.list-row[data-id="${CSS.escape(getItemId(flatItemsList[nextIndex]))}"]`);
    if (activeRow) {
      activeRow.scrollIntoView({ block: 'nearest' });
    }
  }

  // -------------------------------------------------------------------------
  // Event Bindings
  // -------------------------------------------------------------------------

  filterTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      if (mainContent) mainContent.classList.remove('viewing-detail');
      filterTabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      activeFilter = tab.getAttribute('data-filter');
      renderFeed();

      if (flatItemsList.length > 0) {
        selectItem(flatItemsList[0]);
      } else {
        selectItem(null);
      }
    });
  });

  searchInput.addEventListener('input', e => {
    searchQuery = e.target.value.trim();
    renderFeed();
    if (flatItemsList.length > 0 && (!selectedItem || !flatItemsList.includes(selectedItem))) {
      selectItem(flatItemsList[0]);
    }
  });

  btnRefresh.addEventListener('click', () => loadTriage(true));

  modeButtons.forEach(btn => {
    btn.addEventListener('click', () => switchView(btn.getAttribute('data-view')));
  });

  if (btnThemeToggle) {
    btnThemeToggle.addEventListener('click', toggleTheme);
  }

  if (btnLogout) {
    btnLogout.addEventListener('click', handleLogout);
  }

  if (btnBackToList) {
    btnBackToList.addEventListener('click', () => {
      if (mainContent) mainContent.classList.remove('viewing-detail');
    });
  }

  if (btnBannerConnect) {
    btnBannerConnect.addEventListener('click', handleConnectClick);
  }

  if (btnCloseModal) {
    btnCloseModal.addEventListener('click', closeConnectModal);
  }

  if (btnModalDismiss) {
    btnModalDismiss.addEventListener('click', closeConnectModal);
  }

  if (connectModal) {
    connectModal.addEventListener('click', e => {
      if (e.target === connectModal) {
        closeConnectModal();
      }
    });
  }

  if (btnExternalOnly) {
    updateExternalToggleUI();
    btnExternalOnly.addEventListener('click', () => {
      externalOnly = !externalOnly;
      try {
        localStorage.setItem('3riage-external-only', String(externalOnly));
      } catch (e) {}
      updateExternalToggleUI();
      if (!triageData) return;
      updateHeader();
      renderFeed();
      if (flatItemsList.length > 0) {
        const match = selectedItem
          ? flatItemsList.find(i => getItemId(i) === getItemId(selectedItem))
          : null;
        selectItem(match || flatItemsList[0]);
      } else {
        selectedItem = null;
        renderDetail(null);
      }
    });
  }

  window.showToast = showToast;
  window.toggleTheme = toggleTheme;

  consumeAuthErrorParam();
  applyViewChrome();
  loadTriage(false);
})();
