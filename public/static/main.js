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
  const emptyDetail = document.getElementById('empty-detail');
  const detailContent = document.getElementById('detail-content');
  const filterTabs = document.querySelectorAll('.filter-tab');
  const mainContent = document.getElementById('main-content');
  const btnBackToList = document.getElementById('btn-back-to-list');
  const demoBanner = document.getElementById('demo-banner');
  const btnBannerConnect = document.getElementById('btn-banner-connect');
  const connectModal = document.getElementById('connect-modal');
  const btnCloseModal = document.getElementById('btn-close-modal');
  const btnModalDismiss = document.getElementById('btn-modal-dismiss');

  // -------------------------------------------------------------------------
  // Lifecycle & Fetching
  // -------------------------------------------------------------------------

  function consumeAuthErrorParam() {
    const params = new URLSearchParams(window.location.search);
    const err = params.get('auth_error');
    if (!err) return;

    const messages = {
      access_denied: 'GitHub sign-in was cancelled.',
      invalid_state: 'Sign-in state expired or did not match. Please try again.',
      oauth_failed: 'Could not complete GitHub sign-in. Please try again.',
      oauth_not_configured: 'GitHub OAuth is not configured on this host yet.',
    };
    showToast(messages[err] || `GitHub auth notice: ${err}`);

    params.delete('auth_error');
    const nextQs = params.toString();
    const nextUrl = `${window.location.pathname}${nextQs ? '?' + nextQs : ''}${window.location.hash}`;
    window.history.replaceState({}, '', nextUrl);
  }

  async function loadTriage(forceRefresh = false) {
    const requestGen = ++loadGeneration;
    btnRefresh.classList.add('spinning');
    renderSkeletons();

    try {
      const params = new URLSearchParams(window.location.search);
      const isForcedDemo = params.get('demo') === 'true' || params.get('demo') === '1';
      const url = forceRefresh
        ? `/api/refresh${isForcedDemo ? '?demo=true' : ''}`
        : `/api/triage${isForcedDemo ? '?demo=true' : ''}`;
      const method = forceRefresh ? 'POST' : 'GET';
      const res = await fetch(url, { method });
      const json = await res.json();
      if (requestGen !== loadGeneration) return;

      if (res.status === 401) {
        showToast(json.error || 'GitHub session expired. Showing demo mode.');
        const fallbackRes = await fetch('/api/triage?demo=true');
        const fallbackJson = await fallbackRes.json();
        if (requestGen !== loadGeneration) return;
        if (fallbackJson.status === 'ok') {
          applyTriageResponse(fallbackJson);
          return;
        }
      }

      if (json.status !== 'ok') {
        throw new Error(json.error || 'Failed to fetch triage data');
      }

      applyTriageResponse(json);
    } catch (err) {
      if (requestGen !== loadGeneration) return;
      console.error(err);
      connectionStatus.classList.add('offline');
      statusUser.textContent = 'Error connecting';
      listContainer.innerHTML = `
        <div style="padding: 24px 16px; color: var(--color-red); font-size: 12px; line-height: 1.6;">
          <strong>Error loading triage:</strong><br>${escapeHtml(err.message)}
          <br><br>
          <span style="color: var(--text-muted);">Try refreshing or reconnecting your GitHub account.</span>
        </div>
      `;
    } finally {
      if (requestGen === loadGeneration) {
        btnRefresh.classList.remove('spinning');
      }
    }
  }

  function applyTriageResponse(json) {
    triageData = json.data;
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

  function updateHeader() {
    if (!triageData) return;
    connectionStatus.classList.remove('offline');

    if (demoBanner) {
      demoBanner.style.display = isDemoMode ? 'flex' : 'none';
    }

    if (btnLogout) {
      btnLogout.classList.toggle('hidden', authMode !== 'oauth');
    }

    if (isDemoMode) {
      statusUser.textContent = `@${triageData.username} (sample)`;
    } else {
      statusUser.textContent = `@${triageData.username}`;
    }

    const s = triageData.summary;
    const totalActive = s.needs_you + s.waiting_on_them + s.unlinked_issues + s.ready_to_claim;
    countAll.textContent = totalActive;
    countNeedsYou.textContent = s.needs_you;
    countWaiting.textContent = s.waiting_on_them;
    countIssues.textContent = s.unlinked_issues;
    countClaims.textContent = s.ready_to_claim;
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
    if (!triageData) return [];

    let items = [];

    const prsNeedsYou = (triageData.prs.NEEDS_YOU || []).map(p => ({ ...p, category: 'needs_you' }));
    const prsWaiting = (triageData.prs.WAITING_ON_THEM || []).map(p => ({ ...p, category: 'waiting' }));
    const prsFine = (triageData.prs.PROBABLY_FINE || []).map(p => ({ ...p, category: 'probably_fine' }));
    const issues = (triageData.unlinked_issues || []).map(i => ({ ...i, category: 'issues' }));
    const claims = (triageData.claims || []).map(c => ({ ...c, category: 'claims' }));

    if (activeFilter === 'all') {
      items = [...prsNeedsYou, ...prsWaiting, ...prsFine, ...issues, ...claims];
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
      needs_you: '⚡ Needs Your Attention',
      waiting: '⏳ Waiting on Others',
      issues: '📋 Unlinked Bids & Issues',
      claims: '🏆 Ready to Claim'
    };
    listTitle.textContent = titles[activeFilter] || 'Triage Feed';

    if (flatItemsList.length === 0) {
      listContainer.innerHTML = `
        <div style="padding: 32px 16px; text-align: center; color: var(--text-muted); font-size: 12px;">
          ${searchQuery ? 'No items match your search filter.' : 'No items in this view.'}
        </div>
      `;
      return;
    }

    let html = '';
    let currentCategory = '';

    flatItemsList.forEach(item => {
      if (activeFilter === 'all' && item.category !== currentCategory) {
        currentCategory = item.category;
        const labels = {
          needs_you: '⚡ Needs You',
          waiting: '⏳ Waiting on Them',
          probably_fine: '✅ Probably Fine',
          issues: '📋 Unlinked Issues & Bids',
          claims: '🏆 Ready to Claim'
        };
        html += `<div class="list-section-header">${labels[currentCategory] || escapeHtml(currentCategory)}</div>`;
      }

      const isSelected = selectedItem && getItemId(selectedItem) === getItemId(item);
      const isDimmed = item.is_dimmed || item.bucket === 'PROBABLY_FINE';

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
        ageText = item.their_last_comment_days_ago != null
          ? `${item.their_last_comment_days_ago}d ago`
          : (item.your_activity_days_ago != null ? `${item.your_activity_days_ago}d ago` : '');
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
        ageText = item.days_since_my_comment != null ? `${item.days_since_my_comment}d ago` : '';
      } else if (item.type === 'claim') {
        pillHtml = `<span class="pill pill-purple">ready to claim</span>`;
        ageText = `${item.merged_days_ago}d ago`;
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
    let decisionHeadline = '⏳ Waiting on Maintainer Review';
    let decisionSubtext = 'Your activity is newer than theirs. A clean push is awaiting maintainer feedback or merge.';

    if (item.bucket === 'NEEDS_YOU') {
      decisionBorder = 'border-red';
      if (item.review_state === 'CHANGES_REQUESTED') {
        decisionHeadline = '⚡ Action Required: Changes Requested';
        decisionSubtext = `Reviewer @${escapeHtml(item.review_author || 'maintainer')} requested changes. You have not pushed a subsequent commit yet.`;
      } else {
        decisionHeadline = '⚡ Action Required: Reviewer Spoke Last';
        decisionSubtext = `@${escapeHtml(item.their_last_comment_author || 'Maintainer')} left feedback. Ball is in your court to respond or commit.`;
      }
    } else if (item.bucket === 'PROBABLY_FINE') {
      decisionBorder = 'border-green';
      decisionHeadline = '✅ Probably Fine: Approval or Sign-off';
      decisionSubtext = 'All submitted reviews are approved, or the last comment indicates sign-off (LGTM).';
    }

    const snippet = item.their_last_comment_body || item.review_body || '';
    const snippetAuthor = item.their_last_comment_author || item.review_author || 'maintainer';
    const itemUrl = safeUrl(item.url);

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

      ${snippet ? `
        <div class="detail-section">
          <div class="detail-section-title">Maintainer / Reviewer Snippet</div>
          <div class="feedback-quote">
            <div class="feedback-meta">@${escapeHtml(snippetAuthor)} ${item.their_last_comment_days_ago != null ? `(${item.their_last_comment_days_ago}d ago)` : ''}:</div>
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
            <span class="meta-value">${item.their_activity_days_ago != null ? `${item.their_activity_days_ago} days ago` : 'None recorded'}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Your Last Action</span>
            <span class="meta-value">${item.your_activity_days_ago != null ? `${item.your_activity_days_ago} days ago` : 'None recorded'}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Draft Status</span>
            <span class="meta-value">${item.is_draft ? 'Draft PR' : 'Ready for review'}</span>
          </div>
        </div>
      </div>
    `;
  }

  function renderIssueDetail(item) {
    let decisionBorder = 'border-purple';
    let decisionHeadline = '📋 Bounty Bid / Application Active';
    let decisionSubtext = `You applied for this issue. There are ${item.applicant_count || 1} competing applicants. Issue is currently unassigned.`;

    if (item.role === 'assignee') {
      decisionBorder = 'border-red';
      decisionHeadline = '⚡ Assigned to You: Active Task';
      decisionSubtext = 'The maintainer officially assigned this issue to you. Fork and submit a PR to complete it.';
    } else if (item.role === 'outbid') {
      decisionBorder = 'border-muted';
      decisionHeadline = '🚫 Bid Closed: Assigned to Competitor';
      const competitors = (item.applicant_list || []).map(a => `@${escapeHtml(a)}`).join(', ');
      decisionSubtext = `The maintainer assigned this issue to ${competitors || 'another developer'}.`;
    }

    const forkReport = (triageData.fork_report || []).find(f => f.repo.toLowerCase() === item.repo.toLowerCase());
    const needsFork = forkReport ? forkReport.needs_fork : !item.forked;
    const itemUrl = safeUrl(item.url);

    let forkActionHtml = '';
    if (needsFork) {
      if (canForkViaCli || isDemoMode) {
        forkActionHtml = `<button class="btn btn-secondary" id="btn-fork-repo" data-repo="${escapeHtml(item.repo)}">🍴 Fork Repo</button>`;
      } else {
        forkActionHtml = `<a href="${escapeHtml(safeForkUrl(item.repo))}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary">🍴 Fork on GitHub ↗</a>`;
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
            <div class="feedback-meta">Maintainer ${item.maintainer_comment_days_ago != null ? `(${item.maintainer_comment_days_ago}d ago)` : ''}:</div>
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
            <span class="meta-value">${item.days_since_my_comment != null ? `${item.days_since_my_comment} days ago` : 'None'}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Fork Status</span>
            <span class="meta-value" style="color: ${item.forked ? 'var(--color-green)' : 'var(--color-yellow)'};">
              ${item.forked ? '✓ Already forked' : '✗ Unforked'}
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

      <div class="decision-card border-purple">
        <div class="decision-header">🏆 Merged: Ready to Claim Bounty / Points</div>
        <div class="decision-subtext">This pull request merged ${item.merged_days_ago} days ago. Submit this link in your community Discord or Wave channel to claim rewards.</div>
      </div>

      <div class="detail-section">
        <div class="detail-section-title">Claiming Payload</div>
        <div class="feedback-quote" style="font-family: var(--font-mono); font-size: 12px;">
          ${escapeHtml(item.title)}<br>
          ${escapeHtml(itemUrl)}
        </div>
      </div>
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
        showToast(data.message || `✓ Fork initiated for ${repo}`);
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
      btnElement.textContent = '🍴 Fork Repo';
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

  window.showToast = showToast;
  window.toggleTheme = toggleTheme;

  consumeAuthErrorParam();
  loadTriage(false);
})();
