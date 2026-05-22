export function initAnimations(): void {
  const fadeElements = document.querySelectorAll<HTMLElement>('.fade-up');

  const observer = new IntersectionObserver(
    (entries, instance) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) {
          return;
        }

        entry.target.classList.add('visible');
        instance.unobserve(entry.target);
      });
    },
    { threshold: 0.12 }
  );

  fadeElements.forEach((element) => observer.observe(element));
}
