(() => {
    "use strict";

    const initialize = () => {
        const root = document.documentElement;
        const toggle = document.querySelector("[data-motion-toggle]");
        const label = toggle?.querySelector("[data-motion-label]");
        const reveals = [...document.querySelectorAll("[data-reveal]")];
        const scene = document.querySelector("[data-parallax-scene]");
        const preview = scene?.querySelector("[data-parallax]");
        const preference = window.matchMedia?.("(prefers-reduced-motion: reduce)");
        const storageKey = "agrosmena-landing-motion";
        let userPaused = false;
        let reducedMotion = Boolean(preference?.matches);
        let observer = null;
        let frame = null;

        try {
            userPaused = window.localStorage.getItem(storageKey) === "paused";
        } catch {
            // Motion controls also work when browser storage is unavailable.
        }

        const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
        const motionDisabled = () => userPaused || reducedMotion;

        const updateScroll = () => {
            frame = null;
            if (document.hidden) return;

            const viewportHeight = window.innerHeight || root.clientHeight;
            const scrollRange = Math.max(0, root.scrollHeight - viewportHeight);
            const progress = scrollRange > 0 ? window.scrollY / scrollRange : 0;
            root.style.setProperty("--reading-progress", clamp(progress, 0, 1).toFixed(4));

            if (!scene || !preview) return;
            let shift = 0;
            let rotation = 0;
            if (!motionDisabled()) {
                const bounds = scene.getBoundingClientRect();
                const distance = (viewportHeight / 2 - bounds.top - bounds.height / 2)
                    / Math.max(viewportHeight, 1);
                shift = clamp(distance * 40, -28, 28);
                rotation = clamp(distance * 2.4, -2, 2);
            }
            scene.style.setProperty("--scene-shift", `${shift.toFixed(2)}px`);
            scene.style.setProperty("--scene-rotate", `${rotation.toFixed(2)}deg`);
        };

        const requestScrollUpdate = () => {
            if (frame !== null || document.hidden) return;
            frame = window.requestAnimationFrame(updateScroll);
        };

        const revealAll = () => {
            observer?.disconnect();
            observer = null;
            root.classList.remove("motion-ready");
            reveals.forEach((element) => element.classList.add("is-visible"));
        };

        const enableReveals = () => {
            if (!("IntersectionObserver" in window)) {
                revealAll();
                return;
            }
            try {
                if (!observer) {
                    observer = new IntersectionObserver((entries) => {
                        entries.forEach((entry) => {
                            if (!entry.isIntersecting) return;
                            entry.target.classList.add("is-visible");
                            observer?.unobserve(entry.target);
                        });
                    }, { threshold: 0.08, rootMargin: "0px 0px -24px 0px" });
                    reveals.forEach((element) => {
                        if (!element.classList.contains("is-visible")) observer.observe(element);
                    });
                }
                root.classList.add("motion-ready");
            } catch {
                // Leave content readable if the observer cannot be initialized.
                revealAll();
            }
        };

        const applyPreferences = () => {
            const paused = motionDisabled();
            root.classList.toggle("reduced-motion", reducedMotion);
            root.classList.toggle("motion-paused", paused || document.hidden);

            if (toggle) {
                toggle.hidden = false;
                toggle.disabled = reducedMotion;
                toggle.setAttribute("aria-pressed", String(paused));
                toggle.setAttribute("aria-label", reducedMotion
                    ? "Анимация отключена в настройках устройства"
                    : paused ? "Включить анимацию страницы" : "Приостановить анимацию страницы");
                if (label) label.textContent = reducedMotion
                    ? "Анимация отключена"
                    : paused ? "Включить анимацию" : "Пауза анимации";
            }

            if (paused) revealAll();
            else enableReveals();
            requestScrollUpdate();
        };

        toggle?.addEventListener("click", () => {
            if (reducedMotion) return;
            userPaused = !userPaused;
            try {
                window.localStorage.setItem(storageKey, userPaused ? "paused" : "playing");
            } catch {
                // Keep the preference for this visit even without persistence.
            }
            applyPreferences();
        });

        const onPreferenceChange = (event) => {
            reducedMotion = event.matches;
            applyPreferences();
        };
        if (preference?.addEventListener) {
            preference.addEventListener("change", onPreferenceChange);
        } else if (preference?.addListener) {
            preference.addListener(onPreferenceChange);
        }

        window.addEventListener("scroll", requestScrollUpdate, { passive: true });
        window.addEventListener("resize", requestScrollUpdate, { passive: true });
        window.addEventListener("pageshow", requestScrollUpdate);
        window.addEventListener("load", requestScrollUpdate, { once: true });
        window.addEventListener("storage", (event) => {
            if (event.key !== storageKey && event.key !== null) return;
            userPaused = event.newValue === "paused";
            applyPreferences();
        });
        document.addEventListener("visibilitychange", () => {
            root.classList.toggle("motion-paused", motionDisabled() || document.hidden);
            if (document.hidden && frame !== null) {
                window.cancelAnimationFrame(frame);
                frame = null;
            } else {
                requestScrollUpdate();
            }
        });
        document.addEventListener("focusin", (event) => {
            let element = event.target instanceof Element
                ? event.target.closest("[data-reveal]") : null;
            while (element) {
                element.classList.add("is-visible");
                observer?.unobserve(element);
                element = element.parentElement?.closest("[data-reveal]");
            }
        });

        applyPreferences();
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initialize, { once: true });
    } else {
        initialize();
    }
})();
