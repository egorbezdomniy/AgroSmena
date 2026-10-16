(() => {
  'use strict';
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const motion = document.querySelector('[data-motion]');
  let paused = reduced.matches;
  try { paused = paused || localStorage.getItem('catalog-motion-paused') === 'true'; } catch (_) {}
  const setMotion = () => {
    document.body.classList.toggle('motion-paused', paused);
    if (motion) {
      motion.textContent = paused ? 'Включить фон' : 'Пауза фона';
      motion.setAttribute('aria-pressed', String(paused));
      motion.hidden = reduced.matches;
    }
  };
  setMotion();
  motion?.addEventListener('click', () => {
    paused = !paused;
    setMotion();
    try { localStorage.setItem('catalog-motion-paused', String(paused)); } catch (_) {}
  });
  reduced.addEventListener('change', () => { paused = reduced.matches; setMotion(); });
  if (!paused && 'IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      }
    }, { threshold: 0.08 });
    document.querySelectorAll('[data-reveal]').forEach(element => {
      element.classList.add('will-reveal');
      observer.observe(element);
    });
  }
  document.querySelector('.filters select[name="type"]')?.addEventListener('change', event => {
    event.target.form.requestSubmit();
  });
  const add = document.querySelector('[data-add-attribute]');
  if (add) {
    const total = document.querySelector('#id_attributes-TOTAL_FORMS');
    const template = document.querySelector('[data-attribute-template]');
    const list = document.querySelector('[data-attribute-list]');
    add.hidden = false;
    const updateButton = () => { add.disabled = Number(total.value) >= 20; };
    updateButton();
    add.addEventListener('click', () => {
      const index = Number(total.value);
      if (index >= 20) return;
      list.insertAdjacentHTML('beforeend', template.innerHTML.replaceAll('__prefix__', String(index)));
      total.value = String(index + 1);
      updateButton();
      list.lastElementChild.querySelector('input')?.focus();
    });
  }
})();
