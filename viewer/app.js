(function () {
  'use strict';

  /** File names look like: horizon-2026-09-02-zh.md */
  var FILE_RE = /^horizon-(\d{4}-\d{2}-\d{2})-([a-z]{2,3})\.md$/;
  var LANG_LABELS = { zh: '中文', en: 'EN', ja: '日本語' };

  var content = document.getElementById('content');
  var fileCache = null; // name list, fetched once
  var inArticle = false; // true while a report (not the list) is on screen

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function langLabel(lang) {
    return LANG_LABELS[lang] || lang.toUpperCase();
  }

  function fetchList(force) {
    if (fileCache && !force) return Promise.resolve(fileCache);
    return fetch('/summaries/', { cache: 'no-store' })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (list) {
        fileCache = list || [];
        return fileCache;
      });
  }

  /** Group files by date: [{date, langs: {zh: name, ja: name}}], newest first */
  function groupByDate(list) {
    var byDate = {};
    (list || []).forEach(function (e) {
      var m = FILE_RE.exec(e.name || '');
      if (!m) return;
      if (!byDate[m[1]]) byDate[m[1]] = {};
      byDate[m[1]][m[2]] = e.name;
    });
    return Object.keys(byDate)
      .sort()
      .reverse()
      .map(function (d) {
        return { date: d, langs: byDate[d] };
      });
  }

  function renderList(groups) {
    inArticle = false;
    if (!groups.length) {
      content.innerHTML =
        '<div class="empty">' +
        '<h1>Horizon 毎日速報</h1>' +
        '<p>暂无内容</p>' +
        '<p class="muted">等待 CronJob 生成首期日报后，内容会自动出现在这里。</p>' +
        '</div>';
      return;
    }
    var html = '<h1>Horizon 毎日速報</h1><ul class="date-list">';
    groups.forEach(function (g) {
      html += '<li class="date-row"><span class="date">' + esc(g.date) + '</span><span class="lang-chips">';
      Object.keys(g.langs)
        .sort()
        .forEach(function (lang) {
          html +=
            '<a class="chip" href="#/' + encodeURIComponent(g.langs[lang]) + '">' +
            esc(langLabel(lang)) +
            '</a>';
        });
      html += '</span></li>';
    });
    html += '</ul>';
    content.innerHTML = html;
  }

  /* ===== Styling helpers (ported from the former Jekyll site's horizon.js) ===== */

  function tier(score) {
    if (score >= 9) return 'high';
    if (score >= 7) return 'good';
    if (score >= 5) return 'mid';
    return 'low';
  }

  /** Replace ⭐️ N/10 with a colored badge in h2, h3, and li elements */
  function processScoreBadges(root) {
    var scoreRe = /⭐️\s*(\d+(?:\.\d+)?)\/10/;
    root.querySelectorAll('h2, h3, li').forEach(function (el) {
      var m = el.innerHTML.match(scoreRe);
      if (!m) return;
      var score = parseFloat(m[1]);
      el.innerHTML = el.innerHTML.replace(
        scoreRe,
        '<span class="score-badge" data-tier="' + tier(score) + '">' + m[1] + '</span>'
      );
    });
  }

  /** Semantic classes for tag lines and source lines */
  function markSemanticElements(root) {
    root.querySelectorAll('.main-content p, p').forEach(function (p) {
      var text = p.textContent.trim();
      if (/^(Tags|标签)\s*:/.test(text)) {
        p.classList.add('tag-line');
        return;
      }
      if (/^(rss|reddit|github|hackernews|hn|telegram)\s*·/i.test(text)) {
        p.classList.add('source-line');
      }
    });
  }

  /** "其他语言" bar when sibling-language files exist for the same date */
  function renderLangSwitcher(name, list) {
    var m = FILE_RE.exec(name);
    if (!m) return;
    var date = m[1];
    var siblings = (list || []).filter(function (e) {
      var sm = FILE_RE.exec(e.name || '');
      return sm && sm[1] === date && sm[2] !== m[2];
    });
    if (!siblings.length) return;
    var bar = document.createElement('nav');
    bar.className = 'lang-switcher';
    bar.innerHTML =
      '其他语言：' +
      siblings
        .map(function (e) {
          var sm = FILE_RE.exec(e.name);
          return (
            '<a class="chip" href="#/' + encodeURIComponent(e.name) + '">' +
            esc(langLabel(sm[2])) +
            '</a>'
          );
        })
        .join('');
    content.insertBefore(bar, content.firstChild);
  }

  function renderArticle(name) {
    inArticle = true;
    content.innerHTML = '<p class="loading">加载中…</p>';
    fetch('/summaries/' + encodeURIComponent(name), { cache: 'no-store' })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.text();
      })
      .then(function (md) {
        content.innerHTML = marked.parse(md);
        processScoreBadges(content);
        markSemanticElements(content);
        return fetchList().then(function (list) {
          renderLangSwitcher(name, list);
        });
      })
      .catch(function (e) {
        content.innerHTML = '<p class="error">加载失败：' + esc(e.message) + '</p>';
      });
    window.scrollTo(0, 0);
  }

  /* ===== Hash routing =====
     The hash is either a report file ("#/horizon-….md") or an in-page anchor
     inside a rendered report ("#item-tech-news-1" from the TOC). Anchor hashes
     are handled natively by the browser — never hijack them, or the click
     would bounce back to the list page. */

  function route() {
    var hash = window.location.hash.replace(/^#\/?/, '');
    var name = '';
    try {
      name = decodeURIComponent(hash);
    } catch (e) {
      name = '';
    }
    if (FILE_RE.test(name)) {
      renderArticle(name);
      return;
    }
    if (!hash || !inArticle) {
      // No hash, or a non-report hash while the list is shown (e.g. a shared
      // anchor link opened cold — nothing to scroll to yet): show the list.
      document.title = 'Horizon 毎日速報';
      fetchList()
        .then(function (list) {
          renderList(groupByDate(list));
        })
        .catch(function (e) {
          content.innerHTML = '<p class="error">加载列表失败：' + esc(e.message) + '</p>';
        });
    }
    // else: in-page anchor in article view → let the browser scroll.
  }

  window.addEventListener('hashchange', route);
  route();
})();
