// Stall hint: when progress is quiet for ~45s while a job is active.
(function () {
  if (typeof waitForJob !== 'function') return;
  const _orig = waitForJob;
  window.waitForJob = function (task, fillId, labelId, wrapId, formatLabel, timeoutMs) {
    const label = document.getElementById(labelId);
    const STALL_MS = 45000;
    let lastProgressAt = Date.now();
    let stallHintShown = false;
    const p = _orig(task, fillId, labelId, wrapId, formatLabel, timeoutMs);
    const hintTimer = setInterval(() => {
      const wrap = document.getElementById(wrapId);
      if (!wrap || wrap.style.display === 'none') {
        clearInterval(hintTimer);
        return;
      }
      if (!stallHintShown && Date.now() - lastProgressAt > STALL_MS && label) {
        stallHintShown = true;
        const cur = label.textContent || '';
        if (cur.indexOf('Still working') === -1) {
          label.textContent = (cur ? cur + ' · ' : '')
            + 'Still working — large sources can take a minute with no new progress.';
        }
      }
    }, 5000);
    if (label && typeof MutationObserver !== 'undefined') {
      const obs = new MutationObserver(() => {
        lastProgressAt = Date.now();
        stallHintShown = false;
      });
      obs.observe(label, { childList: true, characterData: true, subtree: true });
      p.finally(() => {
        clearInterval(hintTimer);
        try { obs.disconnect(); } catch (e) { /* ignore */ }
      });
    } else {
      p.finally(() => clearInterval(hintTimer));
    }
    return p;
  };
})();
