const toggle = document.querySelector('.menu-toggle');
const navigation = document.getElementById('navigation');
if (toggle && navigation) {
  toggle.addEventListener('click', () => {
    const expanded = toggle.getAttribute('aria-expanded') === 'true';
    toggle.setAttribute('aria-expanded', String(!expanded));
    navigation.classList.toggle('collapsed', expanded);
  });
}

document.querySelectorAll('[data-quick-choice]').forEach((form) => {
  const choice = form.querySelector('select');
  if (!form.requestSubmit) return;
  form.querySelector('button[type="submit"]').hidden = true;
  choice.addEventListener('change', () => form.requestSubmit());
});

// Stage changes use ordinary CSRF-protected POST forms, including without JavaScript.
const stagePickers = document.querySelectorAll('[data-stage-picker]');
stagePickers.forEach((picker) => {
  picker.addEventListener('toggle', () => {
    if (picker.open) stagePickers.forEach((other) => { if (other !== picker) other.open = false; });
  });
  picker.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      picker.open = false;
      picker.querySelector('summary').focus();
    }
  });
});
if (stagePickers.length) document.addEventListener('click', (event) => {
  stagePickers.forEach((picker) => { if (!picker.contains(event.target)) picker.open = false; });
});

// Decorative backgrounds share one control, separate from all business actions.
const motionButtons = document.querySelectorAll('.auth-motion, .workspace-motion');
if (motionButtons.length) {
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let paused = reducedMotion.matches;
  try { paused = paused || sessionStorage.getItem('agrosmena-motion-paused') === 'true'; } catch (_) { /* Storage is optional. */ }
  const updateMotion = () => {
    document.documentElement.classList.toggle('motion-paused', paused || reducedMotion.matches || document.hidden);
    motionButtons.forEach((button) => {
      button.setAttribute('aria-pressed', String(paused));
      button.textContent = paused ? 'Включить фон' : 'Приостановить фон';
      button.hidden = reducedMotion.matches;
    });
  };
  motionButtons.forEach((button) => button.addEventListener('click', () => {
    paused = !paused;
    try { sessionStorage.setItem('agrosmena-motion-paused', String(paused)); } catch (_) { /* Storage is optional. */ }
    updateMotion();
  }));
  reducedMotion.addEventListener('change', updateMotion);
  document.addEventListener('visibilitychange', updateMotion);
  updateMotion();
  document.documentElement.classList.add('motion-ready');
}
