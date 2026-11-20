const track = document.querySelector('#project-track');
const cards = [...track.children];
const previous = document.querySelector('#previous');
const next = document.querySelector('#next');
const dots = document.querySelector('#project-dots');
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
let positions = [];
let active = 0;

function updateControls() {
  active = positions.reduce((nearest, position, index) =>
    Math.abs(track.scrollLeft - position.scroll) < Math.abs(track.scrollLeft - positions[nearest].scroll) ? index : nearest, 0);
  previous.disabled = active === 0;
  next.disabled = active === positions.length - 1;
  [...dots.children].forEach((button, index) => {
    button.setAttribute('aria-current', index === active ? 'true' : 'false');
  });
}

function goTo(index) {
  const position = positions[Math.max(0, Math.min(index, positions.length - 1))];
  if (position) track.scrollTo({ left: position.scroll, behavior: reducedMotion.matches ? 'instant' : 'smooth' });
}

function measureCarousel() {
  const end = track.scrollWidth - track.clientWidth;
  const first = cards[0].offsetLeft;
  positions = [];
  for (const card of cards) {
    const scroll = Math.min(end, card.offsetLeft - first);
    if (positions.at(-1)?.scroll !== scroll) positions.push({ scroll, name: card.querySelector('h2').textContent });
  }
  if (dots.children.length !== positions.length || [...dots.children].some((dot, index) => dot.dataset.project !== positions[index].name)) {
    dots.replaceChildren(...positions.map((position, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.project = position.name;
      button.setAttribute('aria-label', 'Показать ' + position.name);
      button.addEventListener('click', () => goTo(index));
      return button;
    }));
  }
  updateControls();
}

previous.addEventListener('click', () => goTo(active - 1));
next.addEventListener('click', () => goTo(active + 1));
track.addEventListener('scroll', updateControls, { passive: true });
track.addEventListener('keydown', event => {
  if (event.target !== track) return;
  const directions = { ArrowLeft: active - 1, ArrowRight: active + 1, Home: 0, End: positions.length - 1 };
  if (Object.hasOwn(directions, event.key)) {
    event.preventDefault();
    goTo(directions[event.key]);
  }
});
new ResizeObserver(measureCarousel).observe(track);
measureCarousel();
