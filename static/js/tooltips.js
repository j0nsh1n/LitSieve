// Look-themed help text for elements with data-tip.
//
// One delegated tooltip handles static templates and controls rendered later by
// JavaScript. It lives under <body>, so cards and scroll panes cannot clip it.
(function () {
    'use strict';

    var tooltip = null;
    var activeTarget = null;
    var hoverTarget = null;
    var focusTarget = null;
    var dismissedTarget = null;
    var lastPointerType = '';

    function tipTarget(node) {
        return node instanceof Element ? node.closest('[data-tip]') : null;
    }

    function ensureTooltip() {
        if (tooltip) return tooltip;
        tooltip = document.createElement('div');
        tooltip.id = 'app-tooltip';
        tooltip.className = 'app-tooltip';
        tooltip.setAttribute('role', 'tooltip');
        tooltip.hidden = true;
        // The bubble takes the pointer (WCAG 1.4.13: hover text must stay open
        // while the pointer moves onto it), so leaving the bubble is also leaving
        // the control unless the pointer went straight back to it.
        tooltip.addEventListener('pointerleave', function (event) {
            if (!hoverTarget) return;
            if (event.relatedTarget instanceof Node && hoverTarget.contains(event.relatedTarget)) return;
            var left = hoverTarget;
            hoverTarget = null;
            clearDismissalWhenInactive(left);
            refreshTooltip();
        });
        document.body.appendChild(tooltip);
        return tooltip;
    }

    // A control scrolled out of view would otherwise have its bubble clamped to
    // the screen edge, floating there with nothing under it.
    function onScreen(target) {
        var r = target.getBoundingClientRect();
        return r.bottom > 0 && r.top < window.innerHeight && r.right > 0 && r.left < window.innerWidth;
    }

    function addDescription(target) {
        var ids = (target.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
        if (!ids.includes('app-tooltip')) {
            ids.push('app-tooltip');
            target.setAttribute('aria-describedby', ids.join(' '));
        }
    }

    function removeDescription(target) {
        if (!target) return;
        var ids = (target.getAttribute('aria-describedby') || '')
            .split(/\s+/)
            .filter(function (id) { return id && id !== 'app-tooltip'; });
        if (ids.length) target.setAttribute('aria-describedby', ids.join(' '));
        else target.removeAttribute('aria-describedby');
    }

    function hideTooltip() {
        removeDescription(activeTarget);
        activeTarget = null;
        if (!tooltip) return;
        tooltip.hidden = true;
        tooltip.style.removeProperty('left');
        tooltip.style.removeProperty('top');
        tooltip.style.removeProperty('--tooltip-arrow-x');
    }

    function positionTooltip(target) {
        var tip = ensureTooltip();
        var targetRect = target.getBoundingClientRect();
        var tipRect = tip.getBoundingClientRect();
        var gap = 9;  // the bridge in style.css (.app-tooltip::before) is this tall
        var edge = 8;
        var targetCenter = targetRect.left + targetRect.width / 2;
        var left = targetCenter - tipRect.width / 2;
        left = Math.max(edge, Math.min(left, window.innerWidth - tipRect.width - edge));

        var top = targetRect.top - tipRect.height - gap;
        var placement = 'top';
        if (top < edge) {
            top = targetRect.bottom + gap;
            placement = 'bottom';
        }
        top = Math.max(edge, Math.min(top, window.innerHeight - tipRect.height - edge));

        tip.dataset.placement = placement;
        tip.style.left = Math.round(left) + 'px';
        tip.style.top = Math.round(top) + 'px';
        tip.style.setProperty(
            '--tooltip-arrow-x',
            Math.round(Math.max(10, Math.min(targetCenter - left, tipRect.width - 10))) + 'px'
        );
        tip.style.visibility = 'visible';
    }

    function showTooltip(target) {
        var text = target && target.getAttribute('data-tip');
        if (!target || target === dismissedTarget || !text || !text.trim() || !target.isConnected
            || !onScreen(target)) {
            hideTooltip();
            return;
        }
        if (activeTarget !== target) {
            removeDescription(activeTarget);
            activeTarget = target;
            addDescription(target);
        }
        var tip = ensureTooltip();
        tip.textContent = text.trim();
        tip.style.visibility = 'hidden';
        tip.hidden = false;
        positionTooltip(target);
    }

    function refreshTooltip() {
        var next = focusTarget || hoverTarget;
        if (next === dismissedTarget) next = focusTarget === next ? hoverTarget : focusTarget;
        if (next === dismissedTarget) next = null;
        if (next) showTooltip(next);
        else hideTooltip();
    }

    function clearDismissalWhenInactive(target) {
        if (dismissedTarget === target && hoverTarget !== target && focusTarget !== target) {
            dismissedTarget = null;
        }
    }

    document.addEventListener('pointerover', function (event) {
        if (event.pointerType === 'touch') return;
        var target = tipTarget(event.target);
        if (!target || (event.relatedTarget instanceof Node && target.contains(event.relatedTarget))) return;
        hoverTarget = target;
        refreshTooltip();
    });

    document.addEventListener('pointerout', function (event) {
        var target = tipTarget(event.target);
        if (!target || target !== hoverTarget
            || (event.relatedTarget instanceof Node && target.contains(event.relatedTarget))
            || (tooltip && event.relatedTarget instanceof Node && tooltip.contains(event.relatedTarget))) return;
        hoverTarget = null;
        clearDismissalWhenInactive(target);
        refreshTooltip();
    });

    document.addEventListener('pointerdown', function (event) {
        lastPointerType = event.pointerType || '';
        if (lastPointerType === 'touch') {
            hoverTarget = null;
            hideTooltip();
        }
    }, true);

    document.addEventListener('focusin', function (event) {
        var target = tipTarget(event.target);
        focusTarget = lastPointerType === 'touch' ? null : target;
        refreshTooltip();
    });

    document.addEventListener('focusout', function (event) {
        var target = tipTarget(event.target);
        if (target && target === focusTarget
            && !(event.relatedTarget instanceof Node && target.contains(event.relatedTarget))) {
            focusTarget = null;
            clearDismissalWhenInactive(target);
            refreshTooltip();
        }
    });

    document.addEventListener('keydown', function (event) {
        lastPointerType = 'keyboard';
        if (event.key === 'Escape' && activeTarget) {
            dismissedTarget = activeTarget;
            hideTooltip();
        }
    }, true);

    window.addEventListener('resize', refreshTooltip);
    window.addEventListener('scroll', refreshTooltip, true);

    new MutationObserver(function (mutations) {
        if (mutations.some(function (mutation) { return mutation.target === activeTarget; })) {
            refreshTooltip();
        }
    }).observe(document.documentElement, {
        attributes: true,
        subtree: true,
        attributeFilter: ['data-tip']
    });
})();
